"""
Знімок поточного стану шрифтів у файлах гри — щоб не гадати, що там лежить.

  python check_state.py

Показує:
  * кириличні слоти: гарнітура (за m_Scale і піком атласу), кількості записів;
  * таблиці ваг базових шрифтів (куди веде <b>) і чи має та ціль кирилицю;
  * чи лишилась у базових шрифтах латинська пунктуація й цифри;
  * маршрутизацію кожного базового шрифта.
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
from repoint_fonts import build_cab_index, DUP, CYR_TMP, CYR_BOLD_TMP  # noqa: E402

SCAN = kitconfig.SCAN
GAME = kitconfig.GAME
RES = os.path.join(GAME, "resources.assets")
CYR = {
    -2444889057261992194: "Regular TMP",
    -5959213582716284887: "Bold TMP",
    775181479505102588: "Regular SDF (чужий клас)",
    -5519819465463294359: "Bold SDF (чужий клас)",
}
PUNCT_DIGITS = [ord(c) for c in ".,!?:;-—–…«»()’‘“”„'\"№·•/*%°−+" "0123456789"]


def read_fonts(sf, node=None, only_real=True):
    out = {}
    for pid, o in sf.objects.items():
        if o.type.name != "MonoBehaviour":
            continue
        try:
            d = o.read_typetree(node) if node else o.read_typetree()
        except Exception:
            continue
        if isinstance(d, dict) and "m_FaceInfo" in d:
            out[pid] = d
    return out


def main():
    import UnityPy

    idx = build_cab_index()
    p, ds, off, size = idx[DUP]
    fh = open(p, "rb")
    sf = UnityPy.Environment().load_file(
        io.BufferedReader(Window(fh, ds + off, size), buffer_size=1 << 20), name=DUP)
    fonts = read_fonts(sf)

    print("=" * 78)
    print("КИРИЛИЧНІ СЛОТИ У БАНДЛІ")
    print("=" * 78)
    for pid, label in CYR.items():
        d = fonts.get(pid)
        if not d:
            print(f"  {label}: НЕ ПРОЧИТАВСЯ")
            continue
        fi = d["m_FaceInfo"]
        digits = sum(1 for c in d["m_CharacterTable"] if 0x30 <= c["m_Unicode"] <= 0x39)
        punct = sum(1 for c in d["m_CharacterTable"] if c["m_Unicode"] < 0x400)
        print(f"  {label:26s} scale={fi['m_Scale']:.4f} гліфів {len(d['m_GlyphTable'])} "
              f"символів {len(d['m_CharacterTable'])} з них латинських/знаків {punct} "
              f"(цифр {digits})")

    print("\n" + "=" * 78)
    print("КУДИ ВЕДЕ <b> (m_FontWeightTable)")
    print("=" * 78)
    tgt = Counter()
    for pid, d in fonts.items():
        for w in d.get("m_FontWeightTable") or []:
            t = (w.get("regularTypeface") or {}).get("m_PathID", 0)
            if t:
                tgt[t] += 1
    if not tgt:
        print("  усі посилання ОБНУЛЕНІ (<b> товстить поточний шрифт)")
    for t, n in tgt.most_common():
        d = fonts.get(t, {})
        fb = [x.get("m_PathID") for x in (d.get("m_FallbackFontAssetTable") or [])]
        cyr = [CYR.get(x) for x in fb if x in CYR]
        print(f"  -> {d.get('m_Name', t):44s} посилань {n:>3}  "
              f"кирилиця: {cyr or 'НЕМА'}  free_rects {len(d.get('m_FreeGlyphRects') or [])}")

    print("\n" + "=" * 78)
    print("МАРШРУТИЗАЦІЯ Й ПУНКТУАЦІЯ БАЗОВИХ ШРИФТІВ")
    print("=" * 78)
    route, left = Counter(), Counter()
    for pid, d in fonts.items():
        nm = d.get("m_Name") or ""
        if nm.startswith("NotoSerifCyrillic"):
            continue
        fb = [x.get("m_PathID") for x in (d.get("m_FallbackFontAssetTable") or [])]
        r = "FIXEL" if CYR_TMP in fb else ("KYIV" if CYR_BOLD_TMP in fb else None)
        if r is None:
            continue
        route[r] += 1
        left[sum(1 for c in d["m_CharacterTable"] if c["m_Unicode"] in PUNCT_DIGITS)] += 1
    print(f"  маршрутизація: {dict(route)}")
    print(f"  латинської пунктуації/цифр лишилось у базових: {dict(left)}")
    fh.close()

    # ── resources.assets
    from inplace_resources import borrow_node, SLOT_FIXEL, SLOT_KYIV
    node, _ = borrow_node()
    smap = json.load(open(os.path.join(SCAN, "scripts_map.json"), encoding="utf-8"))
    sfr = UnityPy.Environment().load_file(open(RES, "rb"), name="resources.assets")
    print("\n" + "=" * 78)
    print("resources.assets")
    print("=" * 78)
    rf = {}
    for pid, o in sfr.objects.items():
        if o.type.name != "MonoBehaviour":
            continue
        raw = o.get_raw_data()
        fid, spid = struct.unpack_from("<iq", raw, 16)
        if not (fid == 2 and smap.get(f"ggm:{spid}") == "TMP_FontAsset"):
            continue
        try:
            rf[pid] = o.read_typetree(node)
        except Exception:
            pass
    for pid, lbl in ((SLOT_FIXEL, "3335 (Fixel-слот)"), (SLOT_KYIV, "3333 (Kyiv-слот)")):
        d = rf.get(pid)
        if d:
            fi = d["m_FaceInfo"]
            digits = sum(1 for c in d["m_CharacterTable"] if 0x30 <= c["m_Unicode"] <= 0x39)
            print(f"  {lbl:22s} scale={fi['m_Scale']:.4f} гліфів {len(d['m_GlyphTable'])} "
                  f"цифр {digits}")
    route, left, tgt = Counter(), Counter(), Counter()
    for pid, d in rf.items():
        if pid in (SLOT_FIXEL, SLOT_KYIV):
            continue
        fb = [x.get("m_PathID") for x in (d.get("m_FallbackFontAssetTable") or [])]
        r = "FIXEL" if SLOT_FIXEL in fb else ("KYIV" if SLOT_KYIV in fb else None)
        if r:
            route[r] += 1
            left[sum(1 for c in d["m_CharacterTable"] if c["m_Unicode"] in PUNCT_DIGITS)] += 1
        for w in d.get("m_FontWeightTable") or []:
            t = (w.get("regularTypeface") or {}).get("m_PathID", 0)
            if t:
                tgt[t] += 1
    print(f"  маршрутизація: {dict(route)}")
    print(f"  латинської пунктуації/цифр лишилось: {dict(left)}")
    for t, n in tgt.most_common(6):
        d = rf.get(t, {})
        fb = [x.get("m_PathID") for x in (d.get("m_FallbackFontAssetTable") or [])]
        cyr = "FIXEL" if SLOT_FIXEL in fb else ("KYIV" if SLOT_KYIV in fb else "НЕМА")
        print(f"  <b> -> {d.get('m_Name', t):42s} посилань {n:>3}  кирилиця: {cyr}  "
              f"free_rects {len(d.get('m_FreeGlyphRects') or [])}")


if __name__ == "__main__":
    main()
