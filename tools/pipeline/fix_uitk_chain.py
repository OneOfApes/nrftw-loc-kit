"""
Фінальний удар по «старій кирилиці» в UI Toolkit. Три правки разом:

A. Стилі журналу/мапи (`ActivityJournalEntryLabel`, `MapChunkDetailsPanel`)
   вказували на `Arcon-Regular-Loc SDF` — шрифт-посередник з 0 гліфів і
   атласом 1x1. UITK такий асет відкидає і йде в глобальний ланцюг (CJK-серифи
   для російської кирилиці + NotInter для «і»). Перецілюємо стилі ПРЯМО на
   слот B (Kyiv) — асет, який гра довела, що приймає (вкладки/заголовок).

B. Страховка: у ланцюгу запасних самого Loc усі CJK-записи замінюємо на слот B.

C. `NotInter-Regular` (Font/TTF, дефолт теми UITK — ним малюється тіло
   завдання й усе, що без явного шрифта) — вміст замінюється на
   FixelDisplay-Light.otf, доповнений нулями до рідних 431 520 Б. TTF-лоадери
   читають таблиці за зсувами, хвіст ігнорують (перевірено FreeType/PIL).

  python fix_uitk_chain.py plan | apply
"""

from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inplace_font import AA, BUNDLE, BACKUP, FIXEL, BundleView, PlainView, _write  # noqa: E402
from inplace_uitk import borrow_uitk_node, RES  # noqa: E402

SLOT_B_RES = 3332
SLOT_B_BUNDLE = -5519819465463294359
LOC_RES, LOC_BUNDLE = 3326, -3034024402733082206
STYLES_RES = {3776: "ActivityJournalEntryLabel", 3778: "MapChunkDetailsPanel"}
NOTINTER_PID = 815
NOTINTER_LEN = 431520


def swap_pptr_raw(raw, old_pid, new_pid, expect):
    """заміна (fileID=0, old_pid) -> (0, new_pid) у сирих байтах; рівно expect збігів"""
    pat = struct.pack("<iq", 0, old_pid)
    npat = struct.pack("<iq", 0, new_pid)
    cnt = raw.count(pat)
    if cnt != expect:
        return None, f"збігів {cnt}, очікував {expect}"
    return raw.replace(pat, npat), f"{cnt} PPtr"


def loc_fallback_to_b(o, node, slot_b):
    """усі записи запасних Loc -> слот B (8 Б на запис)"""
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter

    raw = o.get_raw_data()
    d = o.read_typetree(node)
    w = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w, o.assets_file)
    if w.bytes != raw:
        return None, "перезбірка НЕ ідентична"
    ch = 0
    for ref in d.get("m_FallbackFontAssetTable") or []:
        if ref.get("m_PathID") != slot_b:
            ref["m_FileID"], ref["m_PathID"] = 0, slot_b
            ch += 1
    if not ch:
        return None, "уже як треба"
    w2 = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w2, o.assets_file)
    if len(w2.bytes) != len(raw):
        return None, "розмір змінився"
    return w2.bytes, f"{ch} записів -> слот B"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    patches_res, patches_bundle = [], []

    # ── A+B у resources.assets
    donor, node = borrow_uitk_node()
    pv = PlainView(RES)
    for pid, nm in STYLES_RES.items():
        o = pv.sf.objects[pid]
        raw = o.get_raw_data()
        nb, info = swap_pptr_raw(raw, LOC_RES, SLOT_B_RES, 1)
        print(f"  A res  «{nm}»: {info}")
        if nb:
            off, size = pv.abs_obj(pid)
            patches_res.append((off, nb))
    o = pv.sf.objects[LOC_RES]
    nb, info = loc_fallback_to_b(o, node, SLOT_B_RES)
    print(f"  B res  «Arcon-Regular-Loc SDF»: {info}")
    if nb:
        off, _ = pv.abs_obj(LOC_RES)
        patches_res.append((off, nb))

    # ── C: NotInter -> Fixel (доповнений). Font не має typetree для запису,
    #    тому сира хірургія: шукаємо префікс довжини m_FontData (431520) і
    #    замінюємо РІВНО стільки байтів слідом — розмір обʼєкта незмінний.
    o = pv.sf.objects[NOTINTER_PID]
    raw = o.get_raw_data()
    lenpat = struct.pack("<i", NOTINTER_LEN)
    pos = raw.find(lenpat)
    fx = open(FIXEL, "rb").read()
    if pos < 0 or raw.count(lenpat) != 1:
        print(f"  C res  🔴 NotInter: префікс довжини знайдено {raw.count(lenpat)} разів")
    elif raw[pos+4:pos+8] != b"\x00\x01\x00\x00":
        print(f"  C res  🔴 NotInter: після префікса не sfnt-сигнатура: "
              f"{raw[pos+4:pos+8].hex()}")
    elif len(fx) > NOTINTER_LEN:
        print("  C res  🔴 Fixel OTF більший за рідний TTF")
    else:
        off, _ = pv.abs_obj(NOTINTER_PID)
        blob = fx + b"\x00" * (NOTINTER_LEN - len(fx))
        patches_res.append((off + pos + 4, blob))
        print(f"  C res  NotInter -> FixelDisplay-Light ({len(fx)} Б + нулі, "
              f"зсув у обʼєкті {pos+4})")
    pv.close()

    # ── A+B у бандлі: стилі-двійники + Loc
    bv = BundleView(os.path.join(AA, BUNDLE))
    pat = struct.pack("<iq", 0, LOC_BUNDLE)
    for pid, o in sorted(bv.sf.objects.items()):
        if o.type.name != "MonoBehaviour" or o.byte_size > 60000:
            continue
        raw = o.get_raw_data()
        if len(raw) < 36 or pid == LOC_BUNDLE:
            continue
        fid, spid = struct.unpack_from("<iq", raw, 16)
        if spid == 19001:
            continue                      # шрифти обробляє loc_fallback нижче
        if pat in raw:
            n = struct.unpack_from("<i", raw, 28)[0]
            nm = raw[32:32+n].decode("utf-8", "replace") if 0 < n < 90 else "?"
            nb, info = swap_pptr_raw(raw, LOC_BUNDLE, SLOT_B_BUNDLE, raw.count(pat))
            print(f"  A бандл «{nm}» (pid {pid}): {info}")
            if nb:
                off, _ = bv.abs_obj(pid)
                patches_bundle.append((off, nb))
    o = bv.sf.objects[LOC_BUNDLE]
    nb, info = loc_fallback_to_b(o, o.serialized_type.node, SLOT_B_BUNDLE)
    print(f"  B бандл «Arcon-Regular-Loc SDF»: {info}")
    if nb:
        off, _ = bv.abs_obj(LOC_BUNDLE)
        patches_bundle.append((off, nb))
    bv.close()

    print(f"\nправок: resources {len(patches_res)}, бандл {len(patches_bundle)}")
    if mode != "apply":
        print("(режим plan — нічого не записано)")
        return 0
    if patches_res:
        _write(RES, patches_res, "uitkchain_resources")
    if patches_bundle:
        _write(os.path.join(AA, BUNDLE), patches_bundle, "uitkchain_bundle")
    donor.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
