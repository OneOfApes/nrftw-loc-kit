"""
Маршрутизація шрифтів UI TOOLKIT між нашими UITK-слотами + замикання
вагових таблиць цих слотів на себе.

🔴 Усе відбувається ВСЕРЕДИНІ класу UI Toolkit. Дати UITK-шрифту запасний
TMP-класу — тихий нативний виліт (мапа, журнал). Тому цілі тут — лише
`Regular SDF` / `Bold SDF` (у `resources.assets` — 3334 / 3332), і ніколи
не наші TMP-слоти.

Розподіл той самий, що й у TMP-частині:
    Arcon-*, Liberation*, Lucida*        -> Fixel  (Regular SDF / 3334)
    friz-*, Marcellus*, standard-graf*   -> Kyiv   (Bold SDF / 3332)

Вагові таблиці слотів замикаються на сам слот — інакше жирне й курсивне в
UITK-панелях піде далі по ланцюгу й дістане ванільний Noto (та сама пастка,
що й у TMP-слотах, див. `fix_bold_weight.py`).

  python repoint_uitk.py plan | apply
"""

from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inplace_font import AA, BUNDLE, BACKUP, BundleView, PlainView, _write  # noqa: E402
from inplace_uitk import borrow_uitk_node, RES  # noqa: E402

UITK_SCRIPT = 19001
SLOT_A_BUNDLE, SLOT_B_BUNDLE = 775181479505102588, -5519819465463294359
SLOT_A_RES, SLOT_B_RES = 3334, 3332
# 🔴 Розподіл UITK — рішення користувача 2026-07-28:
#   * `Arcon-Regular-Loc SDF` -> KYIV: список завдань у журналі, «Активні/
#     Завершені», кнопки під журналом, рядок небезпеки на мапі. Користувач
#     хотів рядок небезпеки у Fixel, але він на ТОМУ САМОМУ шрифті, що список
#     журналу, — тому Kyiv (дозволений запасний варіант).
#   * `MarcellusSC-Regular` -> KYIV: вкладки журналу (Завдання/Замовлення/
#     Випробування) — користувач явно просив їх Kyiv.
# Розриву родини тут нема: у UITK кожен шрифт має власний ланцюг, спільного
# жирного варіанта, як у TMP-родин, не існує.
KYIV_MARKS = ("friz", "marcellus", "standard-graf", "arcon-regular-loc")
WEIGHT_IDX = (4, 7)


def want_slot(name, a, b):
    n = (name or "").lower()
    return b if any(m in n for m in KYIV_MARKS) else a


def is_uitk(o):
    raw = o.get_raw_data()
    if len(raw) < 28:
        return False
    return struct.unpack_from("<q", raw, 20)[0] == UITK_SCRIPT


def edit(o, node, mutate):
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter

    raw = o.get_raw_data()
    node = node or o.serialized_type.node     # у бандлі typetree свій, у resources — позичений
    d = o.read_typetree(node)
    w = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w, o.assets_file)
    if w.bytes != raw:
        return None, "перезбірка НЕ ідентична"
    if not mutate(d):
        return None, "уже як треба"
    w2 = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w2, o.assets_file)
    nb = w2.bytes
    if len(nb) != len(raw):
        return None, f"розмір змінився {len(nb)-len(raw):+d}"
    runs = []
    for i in range(len(raw)):
        if raw[i] == nb[i]:
            continue
        if runs and i == runs[-1][1]:
            runs[-1][1] = i + 1
        else:
            runs.append([i, i + 1])
    n = sum(b - a for a, b in runs)
    if not runs or len(runs) > 12 or n > 160:
        return None, f"підозрілий diff: {len(runs)} діапазонів / {n} Б"
    return [(a, nb[a:b]) for a, b in runs], f"{len(runs)} діап. / {n} Б"


def process(view, node, slot_a, slot_b, label):
    """-> [(abs_offset, bytes)]"""
    out = []
    for pid, o in sorted(view.sf.objects.items()):
        if o.type.name != "MonoBehaviour" or not is_uitk(o):
            continue
        try:
            d = o.read_typetree(node)
        except Exception:
            continue
        if "m_FallbackFontAssetTable" not in d or "m_GlyphTable" not in d:
            continue
        nm = d.get("m_Name") or str(pid)
        base, _ = view.abs_obj(pid)

        if pid in (slot_a, slot_b):
            # слот: вага 400 і 700, пряме й курсивне -> на себе
            def mut(dd, self_pid=pid):
                ch = False
                wt = dd.get("m_FontWeightTable") or []
                for i in WEIGHT_IDX:
                    if i >= len(wt):
                        continue
                    for fld in ("regularTypeface", "italicTypeface"):
                        ref = wt[i].get(fld)
                        if ref is None:
                            continue
                        if (ref.get("m_FileID"), ref.get("m_PathID")) != (0, self_pid):
                            ref["m_FileID"], ref["m_PathID"] = 0, self_pid
                            ch = True
                return ch
            res, info = edit(o, node, mut)
            print(f"  {label} слот «{nm}»: {info}")
            if res:
                out += [(base + a, b) for a, b in res]
            continue

        fb = d.get("m_FallbackFontAssetTable") or []
        if not fb:
            continue
        target = want_slot(nm, slot_a, slot_b)
        cur = fb[0].get("m_PathID")
        if cur == target:
            continue

        def mut2(dd, tgt=target):
            ch = False
            for ref in dd.get("m_FallbackFontAssetTable") or []:
                if ref.get("m_PathID") in (slot_a, slot_b) and ref["m_PathID"] != tgt:
                    ref["m_FileID"], ref["m_PathID"] = 0, tgt
                    ch = True
            return ch
        res, info = edit(o, node, mut2)
        tag = "KYIV" if target == slot_b else "FIXEL"
        print(f"  {label} «{nm}» -> {tag}: {info}")
        if res:
            out += [(base + a, b) for a, b in res]
    return out


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    print("=" * 76)
    print("UI TOOLKIT — маршрутизація" + ("" if mode == "apply" else "   (ПЛАН)"))
    print("=" * 76)

    bv = BundleView(os.path.join(AA, BUNDLE))
    p1 = process(bv, None, SLOT_A_BUNDLE, SLOT_B_BUNDLE, "бандл")
    if mode == "apply" and p1:
        _write(bv.path, p1, "uitkroute_bundle")
    bv.close()

    donor, node = borrow_uitk_node()
    pv = PlainView(RES)
    p2 = process(pv, node, SLOT_A_RES, SLOT_B_RES, "resources")
    if mode == "apply" and p2:
        _write(RES, p2, "uitkroute_resources")
    pv.close()
    donor.close()

    print(f"\nдіапазонів: бандл {len(p1)}, resources {len(p2)}")
    if mode != "apply":
        print("(режим plan — нічого не записано)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
