# nrftw-loc-kit

**A toolkit for building your own language version of _No Rest for the Wicked_
— without a loader, without a modding framework, without runtime hooks.**

The kit patches the shipped game files directly, byte for byte, in place. No DLL
is injected, nothing is hooked at runtime, and no file changes size.

---

## What this is

Machinery and documentation for two jobs the game makes hard:

1. **Text** — replacing the localized string records the game ships with, plus
   the English literals that sit hardcoded inside prefab components and are
   never overwritten at runtime.
2. **Fonts** — putting a real typeface with your alphabet into the game's
   Cyrillic/fallback font slots, and routing every base font, bold variant,
   digit and punctuation mark to the right slot so a single sentence never
   mixes two typefaces.

The kit is **language-neutral**. It describes how the game is built and gives
you the patching machinery. It does not contain a translation or a typeface.

## Precedent

The Ukrainian version (**NRFTW-UA**) was made with exactly this: ~11 000 lines
of text and two Cyrillic typefaces, applied by one command and reverted by
another. **Verified on the official Steam build of the game.**

## Why this is not an ordinary mod

| Ordinary mod | This kit |
|---|---|
| BepInEx / MelonLoader / a custom loader | nothing — the game is unmodified software |
| an injected DLL, runtime hooks | zero code runs inside the game |
| breaks on every game update | breaks on every game update too, but leaves nothing behind |
| uninstall = remove the loader | uninstall = Steam "Verify integrity of game files" |

Because the patch is written *into* the game's own files, the rollback story is
the platform's own: either run `restore_all` from the kit's journals, or let
Steam re-download the touched files. The kit also keeps its own byte-level
backup journals for every write.

## Quick start

```
git clone <this repo>
cd nrftw-loc-kit
pip install -r requirements.txt
python bootstrap.py                     # checks the game install + deps
#   -> writes config.local.json — fill it in:
#      * path to the game directory
#      * paths to YOUR TWO typefaces (one for body text, one for display)
python tools/pipeline/apply_all.py      # one pass, game must be CLOSED
python tools/pipeline/verify_all.py
python tools/pipeline/verify_no_noto.py
```

To go back:

```
python tools/pipeline/restore_all.py
```

Read **[AGENTS.md](AGENTS.md) before you run anything.** It is the entry point
for whoever (or whatever) does the porting work: the two text subsystems, the
two font sources, the four slots, and the pitfalls that each cost a day.

## What is **not** in this repo

- **No translation.** No strings, no glossary, no style guide.
- **No fonts.** Bring your own two typefaces and check their licences yourself.
- **No game files.** Nothing extracted from the game ships here.
- **No prebuilt installer executable.** Installer *sources* are included; the
  built `.exe` lives in GitHub Releases, not in git.
- **No audio/dubbing pipeline.** That is a separate repository.

## Layout

```
AGENTS.md              start here — subsystems, slots, pitfalls, checks
requirements.txt       UnityPy, Pillow, numpy, fonttools
bootstrap.py           environment check -> config.local.json
config.example.json    template: game path, font paths, work dir
tools/pipeline/        the patching machinery (apply/verify/restore/scan)
installer/             installer sources (C#/XAML) + build script
docs/                  ARCHITECTURE.md, FONTS_MAP.md, HANDOFF_FONTS_V2.md
data/fonts_scan/       asset metadata map, so you don't rescan ~7 GB
```

## Licence

**MIT** for the code in this repository — see [LICENSE](LICENSE).

Documentation and asset maps describe the game's structure; they contain no
game content.

## Font attribution (Ukrainian version)

The typefaces themselves are **not distributed with this kit**. The Ukrainian
version used:

- **Kyiv Region** — Dmytro Rastvortsev, for the Kyiv Region identity
  (White Studio Design). Licensed **CC BY-ND 4.0**.
- **Fixel** — MacPaw + AlfaBravo. Licensed **SIL Open Font License 1.1**.

Obtain them from their publishers and respect their terms. If you build another
language version, pick your own typefaces and check their licences before
shipping anything.

---

_No Rest for the Wicked_ is a trademark of its respective owners. This project
is unaffiliated with Moon Studios and Private Division.
