# ARCHITECTURE — how the game stores text and fonts, and why in-place patching works

This is the structural summary. The measured detail is in `FONTS_MAP.md`; the
decision and failure history is in `HANDOFF_FONTS_V2.md`; the operational rules
are in `../AGENTS.md`.

Everything below was established by scanning **all** game files without ever
launching the game.

---

## 1. Where the text lives

Two distinct storage forms, and a localization job has to handle both:

1. **Localization records** — `LocalizedMessage` entries, the ordinary
   translatable string table. This is the bulk of the ~11 000 lines and the easy
   part.
2. **Hardcoded literals in prefabs** — some labels are stored as a UI
   component's `m_text` inside the prefab and are *not* rewritten at runtime.
   The HUD danger badge was the found case: the localization record was
   translated, the component still read `"Dangerous"`. There is no static way to
   tell an authoritative literal from an editor placeholder the game overwrites
   — of ~2 000 candidates across ~400 rows, the overwhelming majority are
   placeholders. Only looking at the running game settles it.

Replacing a literal with a longer string makes the object grow. That is
survivable **without repacking**: the extra bytes are financed from the 4-byte
alignment gap that follows most objects in that file plus 4 bytes freed by
emptying `m_ActiveFontFeatures`, and the object's `byteSize` in the serialized
file's object table is corrected to match. The *file* size is unchanged. Because
the object's internal layout shifts, this step must run **first** in the
pipeline, before any font offsets inside it are computed.

---

## 2. Where the fonts live

101 font assets total, in five files. Only two of them hold Cyrillic:

| File | Font assets | Cyrillic assets |
|---|---|---|
| `duplicateassetisolation…bundle` | 52 | **4** |
| `resources.assets` (not a bundle, **no typetree**) | 41 | **4** |
| `pooled_prefabs` | 6 | 0 |
| `static_scenes` | 2 | 0 |
| `qdb`, `world_assets`, `static_assets`, `monoscripts`, `globalgamemanagers*`, `sharedassets0`, … | 0 | 0 |

`pooled_prefabs` and `static_scenes` reference the bundle's assets through an
external `fileID`, so they never need a typeface written into them — only
repointing.

The two sources are **independent**. `resources.assets` backs the main menu,
loading screens, multiplayer windows and legal screens; it was the reason
several rounds of "successful" patching left loading hints untouched.

### Two subsystems, four slots per source

The game draws text through **TextMeshPro** and **UI Toolkit**, which are
separate classes with separate fallback chains:

| Slot name | Class | Script |
|---|---|---|
| `NotoSerifCyrillic-Regular TMP` / `-Bold TMP` | `TMPro.TMP_FontAsset` | `monoscripts` pathID `-3075889661304172018`, 42 typetree fields |
| `NotoSerifCyrillic-Regular SDF` / `-Bold SDF` | `TextCore.Text.FontAsset` (UI Toolkit) | `Library/unity default resources` pathID **19001**, 38 fields |

Both sources carry all four. In vanilla the two `Bold TMP` slots have **zero
references** — genuinely free — which is what makes two simultaneous typefaces
possible without creating any new asset. All eight are 441 glyphs / 441
characters / 441 used rects, atlas 2048² Alpha8, pt 112 (Bold 106), pad 10,
gradient 11 — identical in both files, which is what makes a byte-for-byte
rewrite possible.

Since the two `Regular SDF` / `Bold SDF` assets are a *different class*, they
are not spare TMP slots; they are the UI Toolkit's own pair, and the game does
load them. Crossing the classes is fatal — see `../AGENTS.md` §1.

### Routing

Every base Latin font carries `m_FallbackFontAssetTable`, whose first entry is a
`PPtr` at a Cyrillic asset. Retargeting a font is an **8-byte write**
(`m_PathID`); the asset size is unaffected. 14 286 UI references resolve through
32 base fonts with live references, so the entire look is decided by ~32 writes.

Finer-grained levers, when one font draws content that should be two typefaces:

- **`m_FontWeightTable`** on a slot — where `<b>` and italic resolve.
- **Per-component retargeting** — `m_fontAsset` + `m_sharedMaterial`, 2×8 bytes
  per component. Does not split families and does not affect `<b>`. The material
  must be copied from a donor component already sitting on the target font, or
  outlines and shadows are lost.
- **UI Toolkit StyleSheets** — which name fonts directly. The live journal
  stylesheets are scene objects in `static_scenes`, not the `resources.assets`
  copies of the same panels.

---

## 3. Why patching in place works

Four independent properties, all verified:

**1. The data blocks in the bundles are not compressed.** Each `SerializedFile`
can be read straight off disk through a streaming window. Peak memory is tens of
megabytes rather than the 7–20 GB a full load would take, and the game does not
have to be uninstalled, unpacked or repacked. It also means an offset computed
from the bundle header maps directly to a file offset:

```
bundle        = data_start + node_off + byte_start
plain file    = byte_start
atlas texture = data_start + resS_node_off + m_StreamData.offset
```

(⚠️ `ObjectReader.byte_start` **already includes** `header.data_offset`. Adding
it again writes megabytes downstream — past the end of file on large ones.)

**2. There is no per-block hash in `blockinfo`.** Nothing validates the block
contents against a checksum, so an in-place rewrite of the same byte length is
accepted verbatim. There is no integrity gate to defeat and none to forge.

**3. `write_typetree` is byte-exact for an unchanged structure.** Reading an
object through its typetree and writing it back with the same field values
produces **the same bytes**. That is the guarantee that makes surgical edits
safe: you can serialize a modified object and know that everything you did not
intend to change is untouched. Sizes only move when a variable-length field
changes length — which is why record counts stay at 441, names stay native, and
any insertion into a list is paid for by a removal elsewhere (e.g. +4 fallback
entries at 12 B against −3 free glyph rects at 16 B).

`resources.assets` has **no typetree of its own**; the node is borrowed from the
bundle, and the MonoBehaviour class is resolved through `m_Script` against a
prebuilt script map.

**4. No file changes size.** Because of the three points above, every file in
the game keeps its exact original length. Consequences:

- The installer can ship **binary diffs** instead of gigabytes of assets.
- Every write can be journaled as `{file, offset, size, old bytes}` and undone
  exactly. Rollback is arithmetic, not a re-download.
- ⚠️ Corollary: a "have we already patched this?" check based on file size does
  not work for the files the fonts touch, since those are unchanged in length.
  The text-carrying files still change size and catch it.

### Rollback

Every step writes a backup journal. Two journal shapes exist — whole-object
backups (used by the step that hides punctuation across the base fonts) and
8-byte range backups (everything else). Because the range writes land *inside*
the same objects the whole-object backups captured, the rollback must run in
**reverse chronological order**. Restoring out of order yields a plausible-
looking intermediate state rather than vanilla — a failure that has occurred
more than once. For a user, the platform's own file-integrity check is the
guaranteed escape hatch.

---

## 4. What the pipeline does, in order

1. **Hardcoded text** — the only step that grows an object; must be first.
2. **Bold fallbacks** — give the families' bold variants a Cyrillic fallback,
   inserted without changing asset size.
3. **Repoint base fonts** — distribute the 32 live base fonts between the two
   slots; lift tooltips off zero-glyph CJK stubs.
4. **Hide punctuation and digits** in the base fonts (rewrites whole objects, so
   it must follow the byte-level edits inside those same objects).
5. **Write the typefaces** into the slots — asset + atlas, bundle first, then
   `resources.assets`, then the UI Toolkit slots.
6. **Weight tables** — lock 400/700, upright and italic, onto the slot itself in
   both slots.
7. **UI Toolkit chain and routing** — stylesheets, the zero-glyph Loc fonts, the
   theme default TTF.
8. **Per-component retargeting** — the last pass, resolving cases where one font
   legitimately draws both kinds of content.

Then: `verify_all`, `verify_no_noto`, `verify_inplace` — and only then the game.
