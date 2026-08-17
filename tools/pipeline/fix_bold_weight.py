"""
🔴 КОРІНЬ ПРОБЛЕМИ «жирне слово іншою гарнітурою».

У ваніли кириличний Fixel-слот (`NotoSerifCyrillic-Regular TMP`) має
`m_FontWeightTable[7].regularTypeface -> NotoSerifCyrillic-Bold TMP`, тобто в
наш **Kyiv-слот**. Те саме в `resources.assets`: 3335 -> 3333.

Через це `<b>` усередині Fixel-речення малювався Kyiv-ом. Ланцюг TMP:

  <b> -> ArconBold-Regular SDF - Variant  (кирилиці нема; його ЗАПАСНІ на
         цьому проході не читаються — includeFallbacks=false)
      -> сам Arcon-Regular SDF            (нема)
      -> запасні Arcon = FIXEL-слот, але запитано жирне, тому TMP спершу
         дивиться у вагову таблицю FIXEL-слота -> а вона веде в KYIV-слот.

Саме тому `add_bold_fallback.py` (кирилиця жирним варіантам) нічого не
змінював: до тих запасних виконання не доходить.

Лікування (жирної гарнітури Fixel у грі нема — третій слот зайняти нічим:
`Regular SDF`/`Bold SDF` чужого класу валять гру, CJK-заглушки мають атлас
1024² і 0 гліфів):

  1. `m_FontWeightTable[7].regularTypeface` Fixel-слота -> 0.
     Тоді TMP бере гліфи самого Fixel і домальовує синтетичний жир
     (`boldStyle` 0.75) — гарнітура одна, виділення лишається.
  2. `boldSpacing` 7.0 -> 0 в ОБОХ слотах: саме ця розрядка колись
     читалася як «другий шрифт».

Мусить іти ПІСЛЯ `inplace_font`/`inplace_resources` — вони переписують
кириличні асети цілком.

  python fix_bold_weight.py plan | apply
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402
from repoint_fonts import View, build_cab_index, DUP, CYR_TMP, CYR_BOLD_TMP  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKUP = kitconfig.BACKUP
GAME = kitconfig.GAME
RES = os.path.join(GAME, "resources.assets")
SLOT_FIXEL, SLOT_KYIV = 3335, 3333
BOLD_WEIGHT_INDEX = 7


def edit(obj, node, mutate):
    """mutate(d) -> True якщо щось змінилось. -> ([(зсув_у_обʼєкті, байти)], опис)"""
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter

    raw = obj.get_raw_data()
    d = obj.read_typetree(node)
    w = EndianBinaryWriter(endian=obj.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w, obj.assets_file)
    if w.bytes != raw:
        return None, "перезбірка НЕ ідентична"
    if not mutate(d):
        return None, "уже як треба"
    w2 = EndianBinaryWriter(endian=obj.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w2, obj.assets_file)
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
    nbytes = sum(b - a for a, b in runs)
    if not runs or len(runs) > 10 or nbytes > 120:
        return None, f"підозрілий diff: {len(runs)} діапазонів, {nbytes} Б"
    return [(a, nb[a:b]) for a, b in runs], f"{len(runs)} діап. / {nbytes} Б"


def make_mut(self_pid):
    """Вага 400 та 700, пряме й курсивне -> НА САМ СЕБЕ.

    🔴 Порожня позиція НЕ РІВНОЗНАЧНА «узяти гліфи самого слота»: перевірено в
    грі — при нулі TMP іде далі по глобальному ланцюгу й дістає ванільний
    Noto Serif (та сама «стара кирилиця з російської локалізації»). Тому
    позицію треба не чистити, а замикати на власний слот: тоді жирне й
    курсивне беруть гліфи ТІЄЇ САМОЇ гарнітури.
    """

    def mut(d):
        ch = False
        wt = d.get("m_FontWeightTable") or []
        for i in (4, BOLD_WEIGHT_INDEX):
            if i >= len(wt):
                continue
            for fld in ("regularTypeface", "italicTypeface"):
                ref = wt[i].get(fld)
                if ref is None:
                    continue
                if ref.get("m_FileID") != 0 or ref.get("m_PathID") != self_pid:
                    ref["m_FileID"], ref["m_PathID"] = 0, self_pid
                    ch = True
        if d.get("boldSpacing"):
            d["boldSpacing"] = 0.0
            ch = True
        return ch

    return mut


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    import UnityPy

    patches = {}

    # ── бандл
    idx = build_cab_index()
    p, ds, off, size = idx[DUP]
    v = View(p, ds, off, size, DUP)
    items = []
    for pid, label in ((CYR_TMP, "FIXEL-слот"), (CYR_BOLD_TMP, "KYIV-слот")):
        o = v.sf.objects[pid]
        res, info = edit(o, o.serialized_type.node, make_mut(pid))
        base = v.base + o.byte_start
        print(f"  бандл {label:12} {info}")
        if res:
            items += [(base + a, b) for a, b in res]
    v.close()
    if items:
        patches[p] = items

    # ── resources.assets
    from inplace_resources import borrow_node
    node, _ = borrow_node()
    sfr = UnityPy.Environment().load_file(open(RES, "rb"), name="resources.assets")
    items = []
    for pid, label in ((SLOT_FIXEL, "FIXEL-слот 3335"), (SLOT_KYIV, "KYIV-слот 3333")):
        o = sfr.objects[pid]
        res, info = edit(o, node, make_mut(pid))
        print(f"  resources.assets {label:16} {info}")
        if res:
            items += [(o.byte_start + a, b) for a, b in res]
    if items:
        patches[RES] = items

    tot = sum(len(x) for x in patches.values())
    print(f"\nусього діапазонів: {tot} "
          f"({sum(len(b) for x in patches.values() for _, b in x)} байтів)")
    if mode != "apply":
        print("(режим plan — нічого не записано)")
        return 0
    if not tot:
        print("нема чого писати")
        return 0

    os.makedirs(BACKUP, exist_ok=True)
    for p, its in patches.items():
        fsize = os.path.getsize(p)
        for offs, blob in its:
            if offs < 0 or offs + len(blob) > fsize:
                raise SystemExit(f"ЗАПИС ЗА МЕЖУ {os.path.basename(p)} — скасовано")
        tag = "boldweight_" + "_".join(os.path.basename(p).split("_")[:2])
        meta = []
        with open(p, "rb") as f:
            for offs, blob in its:
                f.seek(offs)
                meta.append(dict(file=p, offset=offs, size=len(blob),
                                 old=f.read(len(blob)).hex()))
        json.dump(meta, open(os.path.join(BACKUP, f"{tag}.json"), "w"), indent=0)
        with open(p, "r+b") as f:
            for offs, blob in its:
                f.seek(offs)
                f.write(blob)
        print(f"записано {len(its)} правок у {os.path.basename(p)[:46]} "
              f"(журнал {tag}.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
