# -*- coding: utf-8 -*-
"""
kitconfig — єдине джерело шляхів для всього конвеєра.

Усі скрипти в tools/pipeline імпортують константи звідси, а не тримають
захардкоджені шляхи. Реальні значення живуть у `config.local.json` у корені
kit (він у .gitignore). Шаблон — `config.example.json`.

Пошук конфіга: вгору від цього файла, доки не знайдеться config.local.json.
"""

from __future__ import annotations

import json
import os

_KEYS = (
    "game_data",
    "work_dir",
    "font_accent",
    "font_body",
)

_HINT = """\
config.local.json not found.

Copy config.example.json -> config.local.json in the kit root and fill in:
  game_data   - path to NoRestForTheWicked_Data
  work_dir    - writable working directory (scan/backup output)
  font_accent - path to the accent .otf/.ttf you provide yourself
  font_body   - path to the body .otf/.ttf you provide yourself

Or run:  python bootstrap.py
"""


def _find_root() -> str:
    """Кореневу теку kit шукаємо вгору від цього файла."""
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.exists(os.path.join(d, "config.local.json")):
            return d
        if os.path.exists(os.path.join(d, "config.example.json")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            # нічого не знайшли — вважаємо коренем два рівні вгору
            return os.path.dirname(os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))))
        d = parent


KIT_ROOT = _find_root()
CONFIG_PATH = os.path.join(KIT_ROOT, "config.local.json")
EXAMPLE_PATH = os.path.join(KIT_ROOT, "config.example.json")


def load(path: str | None = None) -> dict:
    """Читає і валідує config.local.json. Кидає зрозумілу помилку, якщо його нема."""
    path = path or CONFIG_PATH
    if not os.path.exists(path):
        raise SystemExit("[kitconfig] " + _HINT)
    try:
        with open(path, encoding="utf-8") as fh:
            cfg = json.load(fh)
    except json.JSONDecodeError as exc:
        raise SystemExit("[kitconfig] %s is not valid JSON: %s" % (path, exc))

    missing = [k for k in _KEYS if not str(cfg.get(k) or "").strip()]
    if missing:
        raise SystemExit(
            "[kitconfig] %s: missing or empty keys: %s\n\n%s"
            % (path, ", ".join(missing), _HINT))
    return cfg


CONFIG = load()


def _p(key: str) -> str:
    return os.path.normpath(os.path.expandvars(
        os.path.expanduser(str(CONFIG[key]))))


# --- гра ---------------------------------------------------------------
GAME = _p("game_data")
AA = os.path.join(GAME, "StreamingAssets", "aa", "StandaloneWindows64")
RES = os.path.join(GAME, "resources.assets")
RESS = os.path.join(GAME, "resources.assets.resS")

# головний бандл зі шрифтами (duplicate asset isolation)
BUNDLE = "duplicateassetisolation_assets_all_1241714521824fe3cb084d28d2b047b9.bundle"

# --- робочі теки -------------------------------------------------------
WORK = _p("work_dir")
SCAN = os.path.join(WORK, "fonts_scan")
BACKUP = os.path.join(WORK, "fonts_backup")
PREVIEW = os.path.join(WORK, "fonts_preview")
EXTRACTED = os.path.join(WORK, "fonts_extracted")

# --- шрифти (користувач приносить сам) ---------------------------------
FONT_ACCENT = _p("font_accent")          # акцентний/заголовковий
FONT_BODY = _p("font_body")              # основний текстовий
# цифри можуть бути окремим накресленням тіла; за замовчуванням = FONT_BODY
FONT_DIGITS = (_p("font_digits")
               if str(CONFIG.get("font_digits") or "").strip() else FONT_BODY)

# витягнутий із гри Noto (створюється конвеєром, не постачається з kit)
FONT_NOTO = os.path.join(EXTRACTED, "NotoSerif-Regular.ttf")

for _d in (SCAN, BACKUP):
    os.makedirs(_d, exist_ok=True)
