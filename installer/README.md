# installer/ — the one-file patch applier

A small WPF (.NET 9, Windows) application that applies the localization to an
installed copy of *No Rest for the Wicked*. It ships to users as a single
self-contained `.exe`: no launcher, no runtime to install, no mod loader, no
files left running in the background.

## What it does

1. **Finds the game the way Steam does** — reads `SteamPath`/`InstallPath` from
   the registry, walks `steamapps/libraryfolders.vdf` for every library folder,
   then falls back to the conventional `<drive>:\SteamLibrary\steamapps\common\`
   layout on each fixed drive. If nothing matches, the user points at
   `NoRestForTheWicked.exe` manually.
2. **Verifies the game is untouched.** `payload/sizes.txt` holds the byte size
   of every original target file. Binary patching only works against the exact
   original bytes, so a size mismatch means the game was already patched (or
   updated) and the installer refuses to run rather than corrupting anything.
3. **Applies binary patches.** Each `payload/*.hdiff` is applied with `hpatchz`
   to a `.ua_tmp` file next to the target, which replaces the target only after
   the patch succeeds. A failure leaves the original file untouched.
4. **Rollback** launches `steam://validate/<appid>`, so Steam's own integrity
   check restores the stock files. Nothing is uninstalled by hand.

The payload (`*.hdiff` + `hpatchz.exe` + `sizes.txt`) is embedded into the exe
as assembly resources and unpacked to a temp folder on first launch.

## Layout

| File | Role |
|---|---|
| `MainWindow.xaml` / `.xaml.cs` | the whole UI and all patching logic |
| `App.xaml` / `.xaml.cs` | WPF entry point and control styles |
| `UAInstaller.csproj` | single-file, self-contained `win-x64` publish settings |
| `build_release.py` | generates the payload, then runs `dotnet publish` |
| `ua.ico`, `tryzub.png` | application icon and window artwork |

## Building

Requires the .NET 9 SDK.

```
dotnet publish -c Release
```

That produces a self-contained single-file `NRFTW-UA-TEXT.exe` for `win-x64`.

To rebuild the payload as well:

```
python build_release.py            # diffs, then publishes
python build_release.py --skip-diff    # reuse the existing payload
python build_release.py --skip-publish # only rebuild the payload
```

## Payload is not in this repository

`payload/`, `bin/`, `obj/` and `_publish/` are **not committed**, and neither is
any built exe.

The payload consists of binary diffs against the game's own asset files. They
are derived from copyrighted game data, they are gigabytes' worth of input, and
they are specific to one exact game build — so they are generated locally by
`build_release.py` from your own installed copy of the game, using the pipeline
in `tools/pipeline/`. Released binaries are published as GitHub Releases, not
tracked in git.

`build_release.py` takes every path from the kit config (`config.local.json` in
the kit root — see `config.example.json`) or from the `NRFTW_KIT_WORK`
environment variable. Nothing here is tied to a particular machine.

## Localization of the UI

The installer's own interface strings are Ukrainian, since that is the audience
of the current release. They are plain string literals in `MainWindow.xaml(.cs)`
and can be swapped for another language without touching the patching logic.
