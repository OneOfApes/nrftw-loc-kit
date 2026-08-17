# -*- coding: utf-8 -*-
"""
bootstrap.py -- environment check for nrftw-loc-kit.

Verifies python dependencies, the game installation, and the two fonts the
user supplies. Creates config.local.json from config.example.json on first run.

All output is plain ASCII on purpose: the default Windows console codepage
(cp1252/cp866) cannot render Cyrillic and would crash on print().

    python bootstrap.py
"""

from __future__ import annotations

import importlib
import json
import os
import shutil
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(ROOT, "config.local.json")
EXAMPLE = os.path.join(ROOT, "config.example.json")

BUNDLE = "duplicateassetisolation_assets_all_1241714521824fe3cb084d28d2b047b9.bundle"

# import name -> pip name
DEPS = [
    ("UnityPy", "UnityPy"),
    ("PIL", "Pillow"),
    ("numpy", "numpy"),
    ("fontTools", "fonttools"),
    ("scipy", "scipy"),
    ("lz4.block", "lz4"),
]

REQUIRED_KEYS = ("game_data", "work_dir", "font_accent", "font_body")

OK = "[ ok ]"
BAD = "[fail]"
WARN = "[warn]"


def check_python():
    v = sys.version_info
    if v < (3, 9):
        print("%s python %d.%d -- 3.9 or newer required" % (BAD, v[0], v[1]))
        return False
    print("%s python %d.%d.%d" % (OK, v[0], v[1], v[2]))
    return True


def check_deps():
    missing = []
    for mod, pkg in DEPS:
        try:
            importlib.import_module(mod)
        except Exception:
            missing.append(pkg)
    if missing:
        print("%s missing packages: %s" % (BAD, ", ".join(missing)))
        print("       fix: python -m pip install -r requirements.txt")
        return False
    print("%s python dependencies (%d packages)" % (OK, len(DEPS)))
    return True


def ensure_config():
    """Returns the parsed config, or None if it was just created / is unusable."""
    if not os.path.exists(CONFIG):
        if not os.path.exists(EXAMPLE):
            print("%s neither config.local.json nor config.example.json found" % BAD)
            return None
        shutil.copyfile(EXAMPLE, CONFIG)
        print("%s created config.local.json from the example template" % WARN)
        print("       edit it and set: %s" % ", ".join(REQUIRED_KEYS))
        print("       then run: python bootstrap.py")
        return None
    try:
        with open(CONFIG, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except json.JSONDecodeError as exc:
        print("%s config.local.json is not valid JSON: %s" % (BAD, exc))
        return None
    missing = [k for k in REQUIRED_KEYS if not str(cfg.get(k) or "").strip()]
    if missing:
        print("%s config.local.json: fill in %s" % (BAD, ", ".join(missing)))
        return None
    print("%s config.local.json" % OK)
    return cfg


def _norm(p):
    return os.path.normpath(os.path.expandvars(os.path.expanduser(str(p))))


def check_game(cfg):
    game = _norm(cfg["game_data"])
    if not os.path.isdir(game):
        print("%s game_data not found: %s" % (BAD, game))
        return False
    ok = True
    aa = os.path.join(game, "StreamingAssets", "aa", "StandaloneWindows64")
    if not os.path.isdir(aa):
        print("%s not a NRFTW install: missing StreamingAssets/aa/StandaloneWindows64" % BAD)
        return False
    if not os.path.isfile(os.path.join(aa, BUNDLE)):
        print("%s font bundle not found in aa/StandaloneWindows64:" % BAD)
        print("       %s" % BUNDLE)
        print("       wrong folder, or a game version this kit was not mapped against")
        ok = False
    else:
        print("%s game_data + font bundle" % OK)
    res = os.path.join(game, "resources.assets")
    if not os.path.isfile(res):
        print("%s resources.assets not found -- UI Toolkit steps will fail" % WARN)
    return ok


def check_work(cfg):
    work = _norm(cfg["work_dir"])
    try:
        os.makedirs(os.path.join(work, "fonts_scan"), exist_ok=True)
        os.makedirs(os.path.join(work, "fonts_backup"), exist_ok=True)
    except OSError as exc:
        print("%s work_dir is not writable: %s (%s)" % (BAD, work, exc))
        return False
    print("%s work_dir ready: %s" % (OK, work))
    return True


def check_fonts(cfg):
    ok = True
    for key in ("font_accent", "font_body", "font_digits"):
        raw = str(cfg.get(key) or "").strip()
        if not raw:
            if key == "font_digits":
                print("%s font_digits empty -- reusing font_body" % OK)
                continue
            print("%s %s is empty" % (BAD, key))
            ok = False
            continue
        path = _norm(raw)
        if not os.path.isfile(path):
            print("%s %s not found: %s" % (BAD, key, path))
            ok = False
            continue
        if os.path.splitext(path)[1].lower() not in (".otf", ".ttf", ".ttc"):
            print("%s %s is not an .otf/.ttf file: %s" % (BAD, key, path))
            ok = False
            continue
        print("%s %s: %s" % (OK, key, os.path.basename(path)))
    if not ok:
        print("       fonts are NOT shipped with this kit -- supply your own licensed files")
    return ok


def main():
    print("nrftw-loc-kit bootstrap")
    print("-" * 46)
    fine = check_python()
    fine = check_deps() and fine

    cfg = ensure_config()
    if cfg is None:
        print("-" * 46)
        print("NOT READY -- see the messages above")
        return 1

    fine = check_game(cfg) and fine
    fine = check_work(cfg) and fine
    fine = check_fonts(cfg) and fine

    print("-" * 46)
    if fine:
        print("READY -- next: python tools/pipeline/apply_all.py")
        return 0
    print("NOT READY -- see the messages above")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
