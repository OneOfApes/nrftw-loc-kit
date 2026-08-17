"""
Повний відкат усіх побайтових правок із бекапів у <work_dir>/fonts_backup.

Підтримує два формати журналу:
  {file, offset, size, backup: "<файл.bin>"}   — inplace_font / inplace_resources
  {file, offset, size, old: "<hex>"}           — repoint_fonts

  python restore_all.py            # відкатити все
  python restore_all.py <tag>      # лише один журнал
"""

from __future__ import annotations

import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402

BACKUP = kitconfig.BACKUP


def main():
    only = sys.argv[1] if len(sys.argv) > 1 else None
    # 🔴 ПОРЯДОК ВАЖЛИВИЙ. Частина інструментів бекапить ЦІЛІ обʼєкти шрифтів
    # (hide_base_punct), інша — по 8 байтів усередині тих самих обʼєктів.
    # Тому відкат мусить іти у ЗВОРОТНОМУ до застосування порядку: спершу
    # найновіші бекапи, останнім — найдавніший, у якому лежать найванільніші
    # байти. Порядок беремо за часом створення журналів.
    tags = [f[:-5] for f in sorted(os.listdir(BACKUP),
                                   key=lambda f: os.path.getmtime(os.path.join(BACKUP, f)),
                                   reverse=True) if f.endswith(".json")]
    if only:
        tags = [t for t in tags if t == only]
    total = 0
    for t in tags:
        meta = json.load(open(os.path.join(BACKUP, f"{t}.json"), encoding="utf-8"))
        n = 0
        for m in meta:
            if "backup" in m:
                blob = open(os.path.join(BACKUP, m["backup"]), "rb").read()
            else:
                blob = bytes.fromhex(m["old"])
            if len(blob) != m["size"]:
                print(f"  🔴 {t}: розмір бекапу не збігається на зсуві {m['offset']}")
                continue
            with open(m["file"], "r+b") as f:
                f.seek(m["offset"])
                f.write(blob)
            n += 1
            total += len(blob)
        print(f"  {t}: повернуто {n}/{len(meta)} діапазонів")
    print(f"усього повернуто {total/1e6:.2f} МБ")


if __name__ == "__main__":
    main()
