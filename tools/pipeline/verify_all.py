"""
Наскрізна перевірка по ВСІХ бандлах + resources.assets. Гру не запускає.

Перевіряє чотири речі, кожна з яких колись уже ламала гру або вигляд:
  1. чи ніде немає посилань на кириличні асети ЧУЖОГО КЛАСУ
     (Regular SDF / Bold SDF — саме вони валили гру до меню);
  2. маршрутизацію кожного базового шрифта: Fixel чи Kyiv, і чи не лишився Noto;
  3. чи в кожної цілі <b> (m_FontWeightTable) кирилиця з ТОГО САМОГО слота,
     що й у шрифта, який на неї посилається — інакше змішування в реченні;
  4. чи не лишилось у базових шрифтах латинської пунктуації та цифр.

  python verify_all.py
"""

from __future__ import annotations

import glob
import io
import json
import os
import struct
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kitconfig  # noqa: E402
from scan_all_fonts import Window, bundle_nodes  # noqa: E402
from repoint_fonts import build_cab_index, CYR_TMP, CYR_BOLD_TMP  # noqa: E402
from hide_base_punct import HIDE  # noqa: E402

SCAN = kitconfig.SCAN
GAME = kitconfig.GAME
RES = os.path.join(GAME, "resources.assets")
FOREIGN = {775181479505102588: "Regular SDF", -5519819465463294359: "Bold SDF"}


def script_of(sf, pid):
    """pathID MonoScript обʼєкта. 19001 -> Library/unity default resources,
    тобто FontAsset від UI Toolkit, а не TMP_FontAsset."""
    import struct
    try:
        raw = sf.objects[pid].get_raw_data()
        return struct.unpack_from("<q", raw, 20)[0]
    except Exception:
        return None


def main():
    import UnityPy

    fonts = {}
    for f in glob.glob(os.path.join(SCAN, "usage_*.json")):
        for r in json.load(open(f, encoding="utf-8")).get("fonts", []):
            fonts[(r["file"], int(r["path_id"]))] = r
    idx = build_cab_index()
    bycab = defaultdict(list)
    for (cab, pid), r in fonts.items():
        bycab[cab].append((pid, r["name"]))

    problems = []
    route = Counter()
    punct_left = Counter()
    bold_pairs = []
    detail = defaultdict(list)

    for cab, items in sorted(bycab.items()):
        if cab not in idx:
            continue
        p, ds, off, size = idx[cab]
        fh = open(p, "rb")
        sf = UnityPy.Environment().load_file(
            io.BufferedReader(Window(fh, ds + off, size), buffer_size=1 << 20), name=cab)
        trees = {}
        for pid, nm in items:
            if pid not in sf.objects:
                continue
            try:
                d = sf.objects[pid].read_typetree()
            except Exception:
                continue
            if isinstance(d, dict) and "m_FaceInfo" in d:
                trees[pid] = d
        for pid, d in trees.items():
            nm = d.get("m_Name") or ""
            fb = [x.get("m_PathID") for x in (d.get("m_FallbackFontAssetTable") or [])]
            # 1. 🔴 НЕ «чужий клас», а РОЗБІЖНІСТЬ КЛАСІВ.
            # `Regular SDF` / `Bold SDF` — це не мертві залишки старого TMP, як
            # вважали дві попередні сесії, а шрифти UI Toolkit
            # (`m_Script` -> Library/unity default resources, pathID 19001).
            # Гра їх ЗАВАНТАЖУЄ: на них тримаються панелі мапи, журналу й
            # активностей. Ламає гру не сама згадка про них, а МІШАНИНА:
            # UITK-шрифт із запасним TMP-класу (або навпаки). Кожен мусить
            # вести у свій клас.
            # ⚠️ Сама згадка чужого класу НЕ фатальна: у ваніли UITK-шрифти
            # тримають у запасних CJK-заглушки TMP-класу. Але в них 0 гліфів,
            # тож підсистема туди ніколи не лізе. Вбиває спроба ВЗЯТИ ГЛІФ із
            # чужого класу — тобто запасний, у якому гліфи є.
            is_uitk = script_of(sf, pid) == 19001
            for x in fb:
                if is_uitk and x in (CYR_TMP, CYR_BOLD_TMP):
                    problems.append(f"{nm} ({cab[:14]}) — UITK-шрифт веде в НАШ "
                                    f"TMP-слот: гра впаде на мапі/журналі")
                if not is_uitk and x in FOREIGN:
                    problems.append(f"{nm} ({cab[:14]}) — TMP-шрифт веде в "
                                    f"UITK-асет {FOREIGN[x]}: гра впаде до меню")
            if is_uitk:
                continue        # UITK живе своїм ланцюгом, наші слоти йому чужі
            if nm.startswith("NotoSerifCyrillic"):
                continue
            r = "FIXEL" if CYR_TMP in fb else ("KYIV" if CYR_BOLD_TMP in fb else None)
            if r is None:
                continue
            route[r] += 1
            detail[r].append(nm)
            # 4. пунктуація
            left = sum(1 for c in d["m_CharacterTable"] if c["m_Unicode"] in HIDE)
            punct_left[left] += 1
            if left:
                problems.append(f"{nm} ({cab[:14]}): лишилось {left} латинських знаків")
            # 3. <b>
            for w in d.get("m_FontWeightTable") or []:
                t = (w.get("regularTypeface") or {}).get("m_PathID", 0)
                if not t:
                    continue
                td = trees.get(t)
                if td is None:
                    continue
                tfb = [x.get("m_PathID") for x in (td.get("m_FallbackFontAssetTable") or [])]
                tr = "FIXEL" if CYR_TMP in tfb else ("KYIV" if CYR_BOLD_TMP in tfb else "НЕМА")
                if (td.get("m_GlyphTable") or []) and tr != r:
                    problems.append(f"<b> у «{nm}» ({r}) веде в «{td.get('m_Name')}» "
                                    f"({tr}) — ЗМІШУВАННЯ в одному реченні")
                bold_pairs.append((nm, r, td.get("m_Name"), tr))
        fh.close()

    print("=" * 78)
    print("МАРШРУТИЗАЦІЯ (усі бандли)")
    print("=" * 78)
    for k in ("FIXEL", "KYIV"):
        print(f"\n{k} — {route[k]} шрифтів:")
        for n in sorted(set(detail[k])):
            print(f"    {n}")
    print(f"\nлатинської пунктуації/цифр лишилось: {dict(punct_left)}")

    print("\n" + "=" * 78)
    print("ПАРИ <b> (шрифт -> жирний варіант) — гарнітури мусять збігатися")
    print("=" * 78)
    seen = set()
    for a, ra, b, rb in bold_pairs:
        key = (ra, b, rb)
        if key in seen:
            continue
        seen.add(key)
        mark = "✅" if ra == rb else "🔴"
        print(f"  {mark} {ra:5s} -> {b:48s} {rb}")

    print("\n" + "=" * 78)
    if problems:
        print(f"🔴 ПРОБЛЕМ: {len(problems)}")
        for q in problems[:40]:
            print("   ", q)
    else:
        print("✅ ПРОБЛЕМ НЕ ЗНАЙДЕНО: чужий клас ніде не використовується, "
              "гарнітури <b> збігаються, латинських знаків у базових немає")


if __name__ == "__main__":
    main()
