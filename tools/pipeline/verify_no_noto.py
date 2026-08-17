"""
Наскрізна перевірка: чи може ХОЧ ДЕСЬ у грі виринути ванільна кирилиця
Noto Serif (та, що йшла з російською локалізацією).

Перевіряє три ланки, а не одну (перші дві сесії ловили лише першу і через це
двічі проґавили проблему):

  1. ЗАПАСНІ  — для кожного шрифта з живими посиланнями UI перший асет
     у ланцюгу `m_FallbackFontAssetTable`, що має кирилицю, мусить бути
     нашим слотом (Fixel або Kyiv).
  2. ВАГОВА ТАБЛИЦЯ НАШИХ СЛОТІВ — позиції 400 і 700, пряме й курсивне,
     мусять вести НА САМ СЛОТ. Порожня позиція НЕ означає «узяти власні
     гліфи»: перевірено в грі — TMP іде далі й дістає ванільний Noto.
  3. ЖИРНІ ВАРІАНТИ базових шрифтів (`ArconBold-...Variant` тощо) —
     їхній власний кириличний ланцюг теж мусить вести в наш слот.

  python verify_no_noto.py
"""

from __future__ import annotations

import glob
import json
import os
import struct
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402
from repoint_fonts import View, build_cab_index, DUP, CYR_TMP, CYR_BOLD_TMP  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCAN = kitconfig.SCAN
GAME = kitconfig.GAME
RES = os.path.join(GAME, "resources.assets")
RES_FIXEL, RES_KYIV = 3335, 3333
CYR_RANGE = range(0x400, 0x530)


def live_refs():
    refs = Counter()
    for f in glob.glob(os.path.join(SCAN, "usage_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for h in d.get("holders", []):
            for fld, cab, pid in h["refs"]:
                if fld == "m_fontAsset":
                    refs[(cab, int(pid))] += 1
    return refs


def read_fonts_bundle(cab, idx):
    """{path_id: dict} усіх шрифтових асетів у CAB"""
    if cab not in idx:
        return {}, None
    p, ds, off, size = idx[cab]
    v = View(p, ds, off, size, cab)
    out = {}
    for pid, o in v.sf.objects.items():
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read_typetree(o.serialized_type.node)
        except Exception:
            continue
        if "m_FaceInfo" in d:
            out[pid] = d
    v.close()
    return out, p


def read_fonts_resources():
    import UnityPy
    from inplace_resources import borrow_node
    node, _ = borrow_node()
    smap = json.load(open(os.path.join(SCAN, "scripts_map.json"), encoding="utf-8"))
    sf = UnityPy.Environment().load_file(open(RES, "rb"), name="resources.assets")
    out = {}
    for pid, o in sf.objects.items():
        if o.type.name != "MonoBehaviour":
            continue
        raw = o.get_raw_data()
        fid, spid = struct.unpack_from("<iq", raw, 16)
        if not (fid == 2 and smap.get(f"ggm:{spid}") == "TMP_FontAsset"):
            continue
        try:
            d = o.read_typetree(node)
        except Exception:
            continue
        out[pid] = d
    return out


def cyr_count(d):
    return sum(1 for c in d.get("m_CharacterTable") or []
               if c["m_Unicode"] in CYR_RANGE)


def classify(pid, slots):
    return slots.get(pid)


def chain_source(pid, fonts, slots, seen=None):
    """перший асет у ланцюгу (сам -> запасні), що має кирилицю"""
    seen = seen or set()
    if pid in seen:
        return None
    seen.add(pid)
    d = fonts.get(pid)
    if d is None:
        return ("ЗОВНІШНІЙ", pid)
    if cyr_count(d):
        return (slots.get(pid, "ЧУЖИЙ:" + (d.get("m_Name") or "?")), pid)
    for ref in d.get("m_FallbackFontAssetTable") or []:
        tp = ref.get("m_PathID")
        if not tp:
            continue
        r = chain_source(tp, fonts, slots, seen)
        if r:
            return r
    return None


def main():
    refs = live_refs()
    idx = build_cab_index()
    problems = []

    cabs = sorted({cab for cab, _ in refs})
    allfonts = {}
    for cab in cabs:
        allfonts[cab], _ = read_fonts_bundle(cab, idx)
    allfonts["resources.assets"] = read_fonts_resources()

    print("=" * 78)
    print("1. ЗАПАСНІ: звідки кожен живий шрифт бере кирилицю")
    print("=" * 78)
    for cab in cabs:
        fonts = dict(allfonts[cab])
        # зовнішні посилання ведуть у DUP — доклеюємо його асети
        if cab != DUP:
            fonts.update({k: v for k, v in allfonts.get(DUP, {}).items()
                          if k not in fonts})
        slots = {CYR_TMP: "FIXEL", CYR_BOLD_TMP: "KYIV"}
        for pid, d in sorted(allfonts[cab].items(),
                             key=lambda kv: -refs.get((cab, kv[0]), 0)):
            n = refs.get((cab, pid), 0)
            if not n:
                continue
            name = d.get("m_Name") or "?"
            src = chain_source(pid, fonts, slots)
            tag = src[0] if src else "НЕМАЄ КИРИЛИЦІ"
            bad = tag.startswith("ЧУЖИЙ") or tag == "ЗОВНІШНІЙ"
            if bad:
                problems.append(f"{name} ({cab[:18]}, {n} посилань) -> {tag}")
            if bad or n >= 25:
                print(f"  {'🔴' if bad else '  '} {n:6}  {name[:44]:44} -> {tag}")

    print("\n" + "=" * 78)
    print("2. ВАГОВА ТАБЛИЦЯ НАШИХ СЛОТІВ (жирне / курсивне)")
    print("=" * 78)
    for label, fonts, pairs in (
            ("бандл", allfonts[DUP], ((CYR_TMP, "FIXEL"), (CYR_BOLD_TMP, "KYIV"))),
            ("resources.assets", allfonts["resources.assets"],
             ((RES_FIXEL, "FIXEL"), (RES_KYIV, "KYIV")))):
        for pid, nm in pairs:
            d = fonts.get(pid)
            if d is None:
                problems.append(f"{label}/{nm}: слот не знайдено")
                continue
            wt = d.get("m_FontWeightTable") or []
            ok = True
            for i in (4, 7):
                for fld in ("regularTypeface", "italicTypeface"):
                    tp = (wt[i].get(fld) or {}).get("m_PathID") if i < len(wt) else None
                    if tp != pid:
                        ok = False
                        problems.append(f"{label}/{nm}: вага[{i}].{fld} = {tp}, "
                                        f"а мусить бути {pid} (сам слот)")
            print(f"  {'✅' if ok else '🔴'} {label}/{nm}: ваги 400 і 700, пряме й "
                  f"курсивне {'замкнені на себе' if ok else 'РОЗІМКНЕНІ'}; "
                  f"boldSpacing={d.get('boldSpacing')}")

    print("\n" + "=" * 78)
    print("3. ЖИРНІ ВАРІАНТИ базових шрифтів")
    print("=" * 78)
    for cab in cabs:
        fonts = dict(allfonts[cab])
        if cab != DUP:
            fonts.update({k: v for k, v in allfonts.get(DUP, {}).items()
                          if k not in fonts})
        slots = {CYR_TMP: "FIXEL", CYR_BOLD_TMP: "KYIV"}
        done = set()
        for pid, d in allfonts[cab].items():
            if not refs.get((cab, pid)):
                continue
            for i, w in enumerate(d.get("m_FontWeightTable") or []):
                for fld in ("regularTypeface", "italicTypeface"):
                    tp = (w.get(fld) or {}).get("m_PathID")
                    if not tp or tp in done:
                        continue
                    done.add(tp)
                    src = chain_source(tp, fonts, slots)
                    tag = src[0] if src else "НЕМАЄ КИРИЛИЦІ"
                    nm = (fonts.get(tp) or {}).get("m_Name", f"pid={tp}")
                    if tag.startswith("ЧУЖИЙ"):
                        problems.append(f"жирний варіант {nm} -> {tag}")
                        print(f"  🔴 {nm[:48]:48} -> {tag}")
                    else:
                        print(f"     {nm[:48]:48} -> {tag}")

    print("\n" + "=" * 78)
    if problems:
        print(f"🔴 ЗНАЙДЕНО {len(problems)} ПРОБЛЕМ:")
        for p in problems:
            print("   ", p)
        return 1
    print("✅ СТАРОЇ КИРИЛИЦІ НІДЕ НЕМАЄ: усі живі шрифти беруть кирилицю лише з "
          "наших слотів, жирне й курсивне замкнені на власний слот")
    return 0


if __name__ == "__main__":
    sys.exit(main())
