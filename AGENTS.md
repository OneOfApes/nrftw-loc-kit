# AGENTS.md — read this before you touch a single byte

You are about to make a new language version of _No Rest for the Wicked_ by
patching the shipped game files in place. This document is the map. Everything
in it was paid for in failed builds, silent native crashes and days of
bisecting; none of it is theory.

**Three rules first.**

1. The game must be **closed** while patching.
2. **No file may change size.** Every write is an in-place overwrite of the
   exact same number of bytes. The moment a file grows, you are no longer doing
   this — you are repacking a 10.8 GB bundle and the installer's binary diffs
   are worthless.
3. **Do not improvise.** Every "obvious improvement" listed in §4 has already,
   at least once, either killed the game or ruined the look.

Reading order after this file: `docs/ARCHITECTURE.md` → `docs/FONTS_MAP.md`
(the measured structural map) → `docs/HANDOFF_FONTS_V2.md` (the full decision
and failure history).

---

## 1. The game renders text through TWO independent subsystems

This is the single most expensive lesson in the whole project. Fixing one of
them and declaring victory is why "the old Cyrillic" kept coming back.

| | **TextMeshPro (TMP)** | **UI Toolkit (UITK)** |
|---|---|---|
| Asset class | `TMPro.TMP_FontAsset` (MonoScript in `monoscripts`, 42 typetree fields) | `UnityEngine.TextCore.Text.FontAsset` (`m_Script` → `Library/unity default resources` pathID **19001**, 38 fields) |
| Draws | essentially the whole HUD and menus: subtitles, item descriptions, quests, stats, buttons, loading hints | the activity journal list, map chunk details panel, activity/reward panels, the stylesheets behind them |
| Glyph lookup | builds a dictionary — table order is irrelevant | **binary search over `m_CharacterTable`** — the table must stay sorted by Unicode |
| Routing | `m_FallbackFontAssetTable` + `m_FontWeightTable` | `m_FallbackFontAssetTable` + StyleSheet objects that name a font directly |

They are **different classes**. They do not share fallback chains. You must fix
both.

🔴 **Never cross the classes.** Pointing a TMP font at a UITK Cyrillic asset (or
the reverse) is what produced the two worst failure modes in the project:

- a TMP font whose fallback was a UITK asset **with glyphs in it** →
  `TMP_FontAsset.ReadFontAssetDefinition` → `NullReferenceException` in
  `MainMenu.Initialize`, dead before the main menu ever drew;
- 12 UITK fonts repointed at TMP slots → **silent native crash** on the map and
  in the journal: no exception in `Player.log`, no dump in `CrashDumps`, the
  process just vanishes.

Merely *mentioning* a foreign-class asset is not fatal — vanilla itself keeps
TMP CJK stubs in UITK fallback lists, but those stubs have **0 glyphs**, so the
runtime never reaches into them. What kills the game is **fetching a glyph**
from a foreign class.

---

## 2. There are TWO font sources, and the second one is the one people forget

| Source | What it is | Font assets | Cyrillic slots |
|---|---|---|---|
| `duplicateassetisolation…bundle` (CAB `…c96cdae2…`) | an asset bundle | 52 | 4 |
| `resources.assets` | a plain serialized file, **no typetree** | 41 | 4 |

Plus `pooled_prefabs` (6 fonts) and `static_scenes` (2) — these hold no Cyrillic
assets of their own; they *reference* the bundle through an external `fileID`,
so they only ever need repointing, never a new typeface.

🔴 `resources.assets` carries a **completely independent set**. It is why the
loading-screen hints (`hintTitle`, `hintText`) never changed through several
sessions of "successful" patching: they live in `resources.assets` and take
Cyrillic from *its own* copy of the slot, which bundle-only tools never touched.
`resources.assets` is also where the menu, the multiplayer windows and the
legal screens get their fonts.

Also present: `static_scenes` has its **own copy** of some TTF fonts (e.g. the
UITK theme default), which is why swapping the `resources.assets` copy alone
appeared to do nothing.

---

## 3. The four slots per source, and how routing actually works

Each of the two sources contains **four** Cyrillic font assets — two per
subsystem. So for each subsystem you get exactly **two usable slots per source**:
one per typeface.

| Slot | Bundle `path_id` | `resources.assets` `path_id` | Class | Ukrainian version used it for |
|---|---|---|---|---|
| `NotoSerifCyrillic-Regular TMP` | `-2444889057261992194` | `3335` | TMP | body typeface (Fixel), `m_Scale` 0.7801 |
| `NotoSerifCyrillic-Bold TMP` | `-5959213582716284887` | `3333` | TMP | display typeface (Kyiv), `m_Scale` 0.8242 |
| `NotoSerifCyrillic-Regular SDF` | `775181479505102588` | `3334` | **UITK** | body typeface, 42 336 B, pt 112, cap 80 |
| `NotoSerifCyrillic-Bold SDF` | `-5519819465463294359` | `3332` | **UITK** | display typeface, 42 328 B, pt 106, cap 76 |

All four are 441 glyphs / 441 characters / 441 used rects / 2048² Alpha8 atlas
in both sources, so each can be rewritten in place at identical size.

In vanilla, the `Bold TMP` slots have **zero references** — they are genuinely
free, which is what makes two simultaneous typefaces possible without creating
any new asset.

### Routing mechanism

Every base Latin font (`Arcon-*`, `friz-quadrata-*`, `Liberation*`,
`MarcellusSC*`, `standard-graf*`, …) carries a `m_FallbackFontAssetTable`. Its
first entry is a `PPtr` at a Cyrillic asset. **Switching a font from one
typeface to the other is an 8-byte write** (`m_PathID`) — the asset does not
change size. 14 286 UI references across the game resolve through 32 base fonts,
so 32 eight-byte writes decide the entire look.

Three further levers, in increasing precision:

- **`m_FontWeightTable`** on the *slot itself* — where `<b>` goes (see §4.7).
- **Per-component retargeting** (`m_fontAsset` + `m_sharedMaterial`, 2×8 bytes)
  when a single font draws both display-ish and body-ish content. Take the
  material from a donor component in the same CAB, or outlines and shadows are
  lost.
- **UITK StyleSheet objects**, which name fonts directly. The *live* stylesheets
  for the journal are scene objects in `static_scenes` — not the
  `resources.assets` copies of the same panels. `PreloadData` (pid 1) — never
  touch.

---

## 4. Pitfalls. Every one of these has already fired.

### 4.1 `ObjectReader.byte_start` ALREADY includes `header.data_offset`

Add it a second time and your write lands ~8 MB downstream — on a big file,
**past the end of it**. `world_scenes` grew by 173 KB this way. Absolute offsets:

```
bundle        = data_start + node_off + byte_start
plain file    = byte_start
atlas texture = data_start + resS_node_off + m_StreamData.offset
```

Every tool must assert `offset + size <= filesize` before writing.

### 4.2 Do not touch `m_FreeGlyphRects` or `m_FontFeatureTable`

Generate only what you must. The build must run in **conservative mode**: it
replaces glyph metrics, glyph rectangles and the atlas pixels — and nothing
else. `m_CharacterTable` (byte for byte), `m_FaceInfo`, `m_FontFeatureTable`,
`m_FreeGlyphRects`, glyph indices and glyph order all stay native.

### 4.3 `m_CharacterTable` must stay SORTED (UI Toolkit only)

The first generator wrote its own table in arbitrary order. TMP did not care —
it builds a dictionary. **UI Toolkit silently discarded the whole slot**,
because TextCore binary-searches that table. Having rejected the slot, UITK
walked further down the chain and pulled Cyrillic out of dynamic CJK serif TTFs
and out of the theme default font — the exact "old serif Cyrillic" symptom.
Validate sortedness of any generated UITK asset.

### 4.4 Keep the record count fixed at 441

441 glyphs, 441 characters, 441 used rects. Change the count and the asset
changes size, and in-place patching is over. Your character set must be
*exactly* 441 entries — which means budgeting (see §4.9).

### 4.5 `m_FamilyName` / `m_StyleName` stay native

They live in `m_FaceInfo`, which conservative mode does not rewrite. They are
also variable-length strings: touching them changes the asset size. The slot
keeps calling itself `NotoSerifCyrillic`. That is correct and intended.

### 4.6 `resources.assets` has no typetree — borrow one

There is no typetree in that file. Borrow the node from the
`duplicateassetisolation` bundle (`borrow_node()`), and determine the
MonoBehaviour class from `m_Script` via `data/fonts_scan/scripts_map.json`.
Related: `GameObject` / `Material` / `RectTransform` are not readable through
UnityPy's built-in typetrees — parse GameObject names from raw bytes.

### 4.7 An empty `m_FontWeightTable` slot does NOT mean "use my own glyphs"

This one wasted the most time. `<b>` in TMP is **not** synthetic thickening —
it switches to a *different asset* named by the weight table.

In vanilla, the body slot's `m_FontWeightTable[7].regularTypeface` points at the
**other** slot. So every bold word inside a body sentence rendered in the
display typeface. Zeroing that entry does not fall back to the slot's own
glyphs: TMP walks on down the global chain and returns **vanilla Noto Serif**.

The fix: in **both** slots, weight positions 400 and 700, upright and italic,
must point **at the slot itself** (20 ranges, 87 bytes), plus `boldSpacing`
7.0 → 0. Cost: `isUsingAlternateTypeface = true`, so TMP will not synthesize
extra weight — bold words are the same thickness as the line. There is no third
slot to put a real bold in (see §4.11).

Do **not** zero the reference to the bold variant instead — TMP then applies its
own thickening plus `boldSpacing 7.0` and the result reads as two fonts.

### 4.8 You cannot split a font family

All `Arcon-*` share one bold variant, `ArconBold-Regular SDF - Variant`. All
`friz-quadrata-*` share `friz-quadrata-std-medium-bold SDF TMP - Variant`. If
half a family routes to one typeface and half to the other, `<b>` mid-sentence
yields the wrong typeface. **A family goes to one slot, whole.** This is why the
button font `Arcon-RegularButton SDF` ended up with the body typeface even
though it had been requested as a display font.

Those bold variants have an **empty** `m_FallbackFontAssetTable` in vanilla. A
`PPtr` is 12 B, so inserting one entry without changing the asset size requires
a trade: **+4 fallback entries (48 B) and −3 free glyph rects (16 B × 3)**.
Those assets have 203 and 241 free rects and they matter only to the editor, so
three are affordable.

### 4.9 Digits and punctuation must live in every slot and be hidden in the base fonts

Digits and punctuation are otherwise taken from the *base Latin* font, so a
number inside a display-typeface sentence renders in the Latin face — mixing,
again. Fix in two halves:

- **32 punctuation marks + 10 digits go into each slot**, paid for by dropping
  the rarest Church Slavonic tail (`U+A640..A69F`) — the 441 budget holds.
- The same 40 characters are **hidden in the base fonts** by rewriting their
  `m_Unicode` to the `U+E000+` private-use area (49 base fonts in the Ukrainian
  build). Do not touch the space character or the angle brackets — line
  breaking and rich-text markup depend on them.

Result: a digit inside a display sentence is the display face; inside a body
sentence, the body face.

### 4.10 An old-format asset with a new-format fallback = silent native crash

`resources.assets` contains five **old-format** fonts (`3324`, `3326`, `3329`,
`3330`, `3354`) that legitimately point at the old-format Cyrillic asset
`3334`. Repointing them at the new-format slots crashed the game natively — no
managed exception, no dump — on the map and in the journal, because exactly
those five back `MapChunkDetailsPanel`, `ActivityJournalEntryLabel`,
`ActivityDetailsPanel`, `ActivityRewardPanel` and `FontsStyleSheet`.

The bug survived months undetected simply because nobody opened the map during
verification. **Always test the map, the journal and the legal screens
separately** — they run on old-format assets. The correct fix is to retarget the
*components* of those panels onto their new-format twins, not to repoint the
old-format fonts.

### 4.11 There is no third slot

Measured, not assumed. The UITK slots are 42 336 / 42 328 B; the 18 CJK stubs
are 724–844 B with 1024² atlases and 0 glyphs (the largest, 496 KB, still has 0
glyphs). Holding 441 glyphs at pt 112 needs roughly a 2.96 MB asset with a 2048²
atlas — so any of them would have to **grow**, which ends in-place patching and
breaks the installer's diffs. Two typefaces per subsystem is the ceiling.

### 4.12 Rollback order matters

The step that hides punctuation backs up **whole font objects**; every other
step backs up 8-byte ranges *inside those same objects*. Therefore
`restore_all` must unwind in **reverse chronological order** (by journal
creation time). Get this wrong and the weight tables "revert" to an intermediate
state — which has happened, twice, and once silently undid a set of repoints.
After any partial rollback, run `verify_all` before believing anything.

On re-runs: **rename the old journals** before applying again, or the writer
overwrites its own backup and breaks the rollback chain. Alternatively
`restore_all <tag>` first and delete the journal.

### 4.13 Hardcoded literals: the growing-object step must run FIRST

Some UI strings are not localization records at all — they sit in the prefab as
a component's `m_text` and the game never overwrites them at runtime (found on
the HUD danger badge: the localization record was translated, the component
still said `"Dangerous"`).

A longer replacement makes the object grow by 8 B. Those 8 B are financed from
the 4 B alignment gap after the object plus 4 B freed by emptying
`m_ActiveFontFeatures` (one `kern` tag, kerning off for that one label), and
`byteSize` in the serialized file's object table is corrected. File size
unchanged.

🔴 This step must be **first** in the pipeline. The object grows, so every font
offset inside it is computed relative to the new layout. Run it later and
`restore_all` writes font bytes to the wrong place.

### 4.14 The scan data is a VANILLA snapshot

`data/fonts_scan/*.json` reflects the state **before** any patching. Never
filter fonts by the `fallbacks` field in it — doing so once made the
punctuation-hiding step skip the bold variants entirely. Check for a Cyrillic
fallback against the **live file**.

### 4.15 TTF-level surgery: rebuild cmap subtables, never edit segment bounds

If you go as far as removing a Unicode range from a TTF's `cmap` (formats 4 and
12) to starve a fallback chain of the wrong alphabet: editing segment boundaries
in place breaks the sort order, FreeType rejects the whole table and falls
through to a neighbouring one, or corrupts CJK. Only a **full, valid rebuild of
the subtable in place** works. Verify with a FreeType render afterwards.

### 4.16 Do not touch materials, scale, point size, padding or gradient

Materials are absent from the Cyrillic assets' typetree (`None`). TMP takes the
shader from the base font and only the atlas and `_GradientScale` from the slot
(11.0 everywhere, matching pad 10). Keep native `pt 112` (Bold 106), `pad 10`,
`grad 11`, 2048² Alpha8. Scale is a *design* decision, not a fix: raising it to
match Latin cap height was tried and rejected.

---

## 5. The golden rule

> **Two typefaces must never meet inside one sentence.**

This is the whole quality bar. A user does not file a bug about
`m_FontWeightTable`; they file a bug that says one word in the sentence looks
wrong. There are exactly **three technical paths** by which a second typeface
gets into a sentence, and each has one fix:

| Path | Fix |
|---|---|
| `<b>` switches to the family's bold variant, which is routed elsewhere (or nowhere) | the bold variant, and the slot's own weight table, must resolve to the **same** slot — §4.7, §4.8 |
| digits come from the base Latin font | digits embedded in **every** slot, hidden in the base fonts — §4.9 |
| punctuation, likewise | same treatment — §4.9 |

And the corollary: **never split a family**, because the shared bold variant can
only point at one slot.

**What this rule does not cover.** A label and its value are two separate UI
components on one line (`Cost` drawn by one font, `14` beside it by another).
That is the game's own UI construction, not a sentence, and separating it means
retargeting each component individually (~2 200 eight-byte writes) — which also
changes the English build's appearance. Likewise, Latin words inside a
translated sentence come from the base font; that is a property of TMP, not a
defect you introduced.

---

## 6. Verification commands — and what each one actually catches

Run these with the game closed. None of them launches the game.

| Command | Catches |
|---|---|
| `check_state.py` | **A snapshot, not a test.** Which typeface is in each slot (identified by `m_Scale` and atlas peak), record counts, where each base font's `<b>` leads and whether that target has Cyrillic, whether Latin punctuation/digits are still present in base fonts, and the routing of every base font. Use it to find out what is in the files right now. |
| `verify_all.py` | End-to-end, four checks: (1) no reference anywhere to a **foreign-class** Cyrillic asset, in either direction (TMP→UITK, UITK→our TMP slot); (2) routing of every base font — body, display, or leftover vanilla; (3) each `<b>` target resolves to the **same slot** as the font referencing it; (4) no Latin punctuation or digits left in base fonts. ⚠️ It does **not** check asset *format* (old vs new), which is how §4.10 slipped through while it reported clean. |
| `verify_no_noto.py` | The vanilla-Cyrillic hunt, across **three** links rather than one: (1) fallback chains — the first Cyrillic-bearing asset must be one of our slots; (2) the **weight tables of our own slots** — positions 400/700, upright and italic, must point at the slot itself; (3) the bold variants' own Cyrillic chains. Link 2 is the one `verify_all` and `check_state` do not look at, and the one that let bold words render in the wrong typeface while everything reported ✅. |
| `verify_inplace.py` | Proof by rendering: reads the atlases **out of the game files**, checks each Cyrillic asset's format against the native contract, draws sample strings from those atlases to a PNG, and prints where each base font now points. This is what tells you the glyphs are really in there, as opposed to the references merely being tidy. |
| `restore_all.py` | Full rollback from the byte-level journals, in **reverse chronological order** (§4.12). `restore_all.py <tag>` unwinds a single journal. |

**"Zero exceptions in `Player.log`" ≠ "the fonts work."** That mistake has been
made repeatedly here — including while the game was crashing natively with no
log entry at all. Every tool in this list checks the files; only a human looking
at the running game gives the verdict.

---

## 7. One work cycle

```
python tools/pipeline/check_state.py           # what is in the files now
python tools/pipeline/restore_all.py           # back to vanilla (game CLOSED)
#   … edit the settings in the relevant script …
python tools/pipeline/apply_all.py             # one pass, ~1 minute
python tools/pipeline/verify_all.py
python tools/pipeline/verify_no_noto.py
python tools/pipeline/verify_inplace.py        # renders a preview from game files
#   … archive Player.log so the next run starts clean, then look at the game …
```
