# data/ — pre-computed asset maps

**This is metadata, not game content.** Every file here is a JSON index that
*describes* where things live inside the game's asset files: bundle names, Unity
`CAB-*` file names, `path_id` values, asset names, font family/style, and which
component references which font. There are no textures, no fonts, no meshes, no
audio, no text from the game — nothing that could substitute for owning a copy.

## Why it is committed

Producing these maps means walking roughly 7 GB of Unity bundles with UnityPy,
which takes a long time and requires an installed copy of the game. Shipping the
maps lets a new contributor read the structure, plan a patch, and understand the
subsystems immediately, then only touch the game files when actually applying
something.

Total size is under 10 MB.

## fonts_scan/

| File | What it indexes |
|---|---|
| `usage_*.json` | per-bundle-group font usage: every font asset found (`bundle`, `file`, `path_id`, `name`, `family`, `style`) plus every *holder* — the components that reference a font. This is the core map. |
| `scripts_map.json` | MonoScript class-name lookup, so a `MonoBehaviour` can be resolved to the component type that draws text. |
| `resources_*.json` | the same breakdown for `resources.assets` / `globalgamemanagers` / `sharedassets0`: `resources_fonts.json` (font assets), `resources_holders.json` (referencing components), `resources_usage.json` (combined). |
| `fonts_*.json` | condensed per-bundle font inventories. |
| `inplace_plan.json` | the in-place byte-patch plan derived from the maps above. |
| `tmpfont_typetree.json` | the TMP font-asset TypeTree, needed to read/write TMP assets without Unity. |

`usage_monoscripts_unitybuiltinassets_static_early_world_assets_qdb_binary_static_assets_static_scenes_qdb_assets.json`
has a long name because it is a merged scan across that whole set of bundles;
the file name records exactly which groups went into it.

## Regenerating

Nothing here is hand-written. All of it is produced by the scan scripts, which
read paths from the kit config:

```
python tools/pipeline/scan_all_fonts.py
python tools/pipeline/scan_font_usage.py
python tools/pipeline/scan_resources_v2.py
```

After a game update the maps go stale — `path_id`s and bundle hashes change.
Re-run the scans rather than editing the JSON.
