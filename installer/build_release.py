"""
build_release — assembles the installer payload, then builds the exe.

    python build_release.py [--skip-diff] [--skip-publish]

Two steps:
  1. hdiffz over every file in <work>/originals vs <work>/staging, writing
     binary patches into ./payload/. The patch file name is the file's path
     relative to the game root with separators replaced by '~' — that is the
     encoding MainWindow.xaml.cs expects when it maps a patch back to a target.
  2. `dotnet publish -c Release`, then copy the resulting single-file exe out.

NOTE ON PATHS
  Nothing here is hardcoded to a particular machine. Every location comes from
  the kit config (`config.local.json` in the kit root, see config.example.json)
  or from the NRFTW_KIT_WORK environment variable. `originals/`, `staging/`
  and `payload/` are large and are never committed to git.
"""
import json
import os
import shutil
import subprocess
import sys
import time

# redirecting stdout to a file on Windows picks cp1252 and dies on Cyrillic
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
KIT_ROOT = os.path.dirname(HERE)


def _config():
    """work_dir / hdiffpatch_dir / release_dir come from the kit config."""
    path = os.path.join(KIT_ROOT, "config.local.json")
    cfg = {}
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    work = os.environ.get("NRFTW_KIT_WORK") or cfg.get("work_dir")
    if not work:
        raise SystemExit(
            "build_release: no work_dir.\n"
            "  Copy config.example.json -> config.local.json in the kit root\n"
            "  and set \"work_dir\", or set NRFTW_KIT_WORK.")
    work = os.path.normpath(os.path.expandvars(os.path.expanduser(work)))
    hdiff = cfg.get("hdiffpatch_dir") or os.path.join(work, "hdiffpatch", "windows64")
    release = cfg.get("release_dir") or os.path.join(work, "release", "NRFTW-UA-TEXT")
    return work, os.path.normpath(hdiff), os.path.normpath(release)


WORK, HDIFF_DIR, RELEASE = _config()
ORIG = os.path.join(WORK, "originals")       # pristine copies of the game files
STAGE = os.path.join(WORK, "staging")        # patched copies produced by the pipeline
PAYLOAD = os.path.join(HERE, "payload")      # generated; gitignored
HDIFFZ = os.path.join(HDIFF_DIR, "hdiffz.exe")
HPATCHZ = os.path.join(HDIFF_DIR, "hpatchz.exe")
CSPROJ = os.path.join(HERE, "UAInstaller.csproj")
PUBLISH = os.path.join(HERE, "_publish")     # generated; gitignored
EXE_NAME = "NRFTW-UA-TEXT.exe"

# Bundles live under StreamingAssets/aa/...; resources.assets and its .resS sit
# directly in the *_Data folder. Same layout the scan/apply scripts assume.
DATA_DIR = "NoRestForTheWicked_Data"
AA = os.path.join(DATA_DIR, "StreamingAssets", "aa", "StandaloneWindows64")


def targets():
    out = []
    for f in sorted(os.listdir(ORIG)):
        rel = os.path.join(AA, f) if f.endswith(".bundle") else os.path.join(DATA_DIR, f)
        out.append((rel, f))
    return out


def main():
    skip_diff = "--skip-diff" in sys.argv
    skip_pub = "--skip-publish" in sys.argv
    os.makedirs(PAYLOAD, exist_ok=True)

    if not skip_diff:
        for rel, name in targets():
            orig = os.path.join(ORIG, name)
            new = os.path.join(STAGE, rel)
            if not os.path.isfile(new):
                print(f"SKIP (not in staging): {rel}")
                continue
            out = os.path.join(PAYLOAD, rel.replace("\\", "~").replace("/", "~") + ".hdiff")
            t = time.time()
            print(f"diff {name} ({os.path.getsize(new)/1e9:.1f} GB) ...", flush=True)
            r = subprocess.run([HDIFFZ, "-f", "-s-64", orig, new, out],
                               capture_output=True, text=True, errors="ignore")
            if r.returncode != 0:
                print(r.stdout[-2000:])
                print(r.stderr[-2000:])
                print(f"ERROR: hdiffz failed on {name}")
                return 1
            print(f"  -> {os.path.basename(out)}  {os.path.getsize(out)/1e6:.1f} MB "
                  f"in {(time.time()-t)/60:.1f} min", flush=True)

        hp = os.path.join(PAYLOAD, "hpatchz.exe")
        if not os.path.isfile(hp):
            shutil.copy(HPATCHZ, hp)

    total = sum(os.path.getsize(os.path.join(PAYLOAD, f)) for f in os.listdir(PAYLOAD))
    print(f"\npayload: {len(os.listdir(PAYLOAD))} files, {total/1e6:.0f} MB")

    if skip_pub:
        return 0

    if os.path.isdir(PUBLISH):
        shutil.rmtree(PUBLISH)
    print("\ndotnet publish ...", flush=True)
    r = subprocess.run(["dotnet", "publish", CSPROJ, "-c", "Release", "-o", PUBLISH],
                       capture_output=True, text=True, errors="ignore")
    print(r.stdout[-3000:])
    if r.returncode != 0:
        print(r.stderr[-3000:])
        return 1
    exe = os.path.join(PUBLISH, EXE_NAME)
    if not os.path.isfile(exe):
        print("ERROR: exe was not produced")
        return 1
    os.makedirs(RELEASE, exist_ok=True)
    dst = os.path.join(RELEASE, EXE_NAME)
    shutil.copy(exe, dst)
    print(f"\nDONE: {dst}  ({os.path.getsize(dst)/1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
