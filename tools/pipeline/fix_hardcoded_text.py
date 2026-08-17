"""
Заміна англійських літералів, ЗАШИТИХ У САМІ КОМПОНЕНТИ UI (`m_text`).

Текстовий конвеєр патчить `LocalizedMessage`-записи. Але частина написів
лежить просто в префабі як текст компонента, і гра їх не завжди перезаписує
в рантаймі. Приклад: плашка небезпеки в HUD
`playerHUD/playerTimeOfDay/playerLocation/.../danger/backgroundStatus/dangerText`
з `m_text = "Dangerous"` — запис локалізації для цього ж рядка перекладено
(«Небезпечно»), але в певному стані видно саме літерал.

🔴 Рядок довший за оригінал, тому обʼєкт РОСТЕ. Щоб не перепаковувати бандл
на 10,8 ГБ, беремо байти з двох місць:
  * проміжок вирівнювання після обʼєкта (у цьому файлі в 312 628 обʼєктів
    він і так 0, тож зайняти його безпечно);
  * порожній `m_ActiveFontFeatures` — там один тег `kern`, 4 Б. Кернінг
    вимикається для ОДНОГО цього напису, на око непомітно.
Розмір файлу не змінюється. Додатково правиться `byteSize` у службовій
таблиці обʼєктів (метадані серіалізованого файлу).

🔴 Мусить іти ПЕРШИМ у `apply_all`: обʼєкт росте, тому всі зсуви шрифтових
правок усередині нього зсуваються. Якщо запустити після — `restore_all`
поверне шрифтові байти не туди.

  python fix_hardcoded_text.py plan | apply
"""

from __future__ import annotations

import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402
from repoint_fonts import View, build_cab_index  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

BACKUP = kitconfig.BACKUP

# (CAB, path_id, очікуваний старий текст, новий текст, опис)
JOBS = [
    ("CAB-fdc51b115548f0b7186d2c250b087e8d", 5209661887136665690,
     "Dangerous", "Небезпечно", "плашка небезпеки в HUD"),
]


def rebuild(o, node, new_text):
    """-> (нові байти, опис) | (None, причина)"""
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter

    raw = o.get_raw_data()
    d = o.read_typetree(node)
    w = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w, o.assets_file)
    if w.bytes != raw:
        return None, "перезбірка НЕ ідентична"
    if d.get("m_text") == new_text:
        return None, "уже перекладено"
    d["m_text"] = new_text
    if d.get("m_ActiveFontFeatures"):
        d["m_ActiveFontFeatures"] = []
    w2 = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w2, o.assets_file)
    return w2.bytes, f"{len(raw)} -> {len(w2.bytes)} Б"


def find_meta_entry(path, base, data_offset, pid, byte_start_rel, byte_size):
    """абсолютний зсув поля byteSize у службовій таблиці обʼєктів"""
    with open(path, "rb") as f:
        f.seek(base)
        meta = f.read(data_offset)
    pat = struct.pack("<q", pid)
    pos = -1
    found = []
    while True:
        pos = meta.find(pat, pos + 1)
        if pos < 0:
            break
        try:
            vals = struct.unpack_from("<qqIi", meta, pos)
        except Exception:
            continue
        if vals[1] == byte_start_rel and vals[2] == byte_size:
            found.append(pos)
    if len(found) != 1:
        return None, f"записів у метаданих {len(found)}, а треба рівно 1"
    return base + found[0] + 16, "ok"


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    idx = build_cab_index()
    patches = {}

    for cab, pid, old_text, new_text, note in JOBS:
        if cab not in idx:
            print(f"  🔴 CAB не знайдено: {cab}")
            continue
        p, ds, off, size = idx[cab]
        v = View(p, ds, off, size, cab)
        base = v.base
        do = v.sf.header.data_offset if hasattr(v.sf, "header") else None
        do = getattr(v.sf, "data_offset", None) or do
        o = v.sf.objects.get(pid)
        if o is None:
            print(f"  🔴 обʼєкт {pid} не знайдено")
            v.close()
            continue

        # скільки місця доступно: власний розмір + проміжок до наступного
        starts = sorted(x.byte_start for x in v.sf.objects.values())
        i = starts.index(o.byte_start)
        room = o.byte_size + (starts[i + 1] - (o.byte_start + o.byte_size)
                              if i + 1 < len(starts) else 0)

        nb, info = rebuild(o, o.serialized_type.node, new_text)
        print(f"  {note}: {info if nb is None else info}")
        if nb is None:
            v.close()
            continue
        print(f"    доступно {room} Б (обʼєкт {o.byte_size} + проміжок "
              f"{room - o.byte_size}), потрібно {len(nb)} Б")
        if len(nb) > room:
            print("    🔴 НЕ ВЛАЗИТЬ — скасовано")
            v.close()
            continue

        moff, minfo = find_meta_entry(p, base, do, pid, o.byte_start - do,
                                      o.byte_size)
        if moff is None:
            print(f"    🔴 службовий запис: {minfo}")
            v.close()
            continue
        print(f"    службовий запис byteSize на зсуві {moff}: "
              f"{o.byte_size} -> {len(nb)}")

        items = patches.setdefault(p, [])
        items.append((base + o.byte_start, nb))
        items.append((moff, struct.pack("<I", len(nb))))
        v.close()

    tot = sum(len(x) for x in patches.values())
    print(f"\nдіапазонів: {tot}")
    if mode != "apply":
        print("(режим plan — нічого не записано)")
        return 0
    if not tot:
        print("нема чого писати")
        return 0

    os.makedirs(BACKUP, exist_ok=True)
    for p, items in patches.items():
        fsize = os.path.getsize(p)
        for offs, blob in items:
            if offs < 0 or offs + len(blob) > fsize:
                raise SystemExit(f"ЗАПИС ЗА МЕЖУ {os.path.basename(p)} — скасовано")
        tag = "hardtext_" + "_".join(os.path.basename(p).split("_")[:2])
        meta = []
        with open(p, "rb") as f:
            for offs, blob in items:
                f.seek(offs)
                meta.append(dict(file=p, offset=offs, size=len(blob),
                                 old=f.read(len(blob)).hex()))
        json.dump(meta, open(os.path.join(BACKUP, f"{tag}.json"), "w"), indent=0)
        with open(p, "r+b") as f:
            for offs, blob in items:
                f.seek(offs)
                f.write(blob)
        print(f"записано {len(items)} правок у {os.path.basename(p)[:46]} "
              f"(журнал {tag}.json); розмір файлу {os.path.getsize(p)} "
              f"({'незмінний' if os.path.getsize(p) == fsize else '🔴 ЗМІНИВСЯ'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
