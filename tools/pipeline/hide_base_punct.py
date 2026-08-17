"""
Щоб пунктуація в українському тексті була УКРАЇНСЬКА (з нашої гарнітури),
а не латинська з Arcon/friz-quadrata.

TextMeshPro завжди спершу шукає символ у базовому шрифті і лише потім іде по
списку запасних. Тому доки в Arcon є кома — вона братиметься з Arcon, хоч би
що лежало в кириличному асеті. Єдиний спосіб віддати пунктуацію запасному
шрифту — прибрати ці символи з базового.

Прибираємо БЕЗ зміни розміру: у m_CharacterTable запис не видаляється, а його
m_Unicode переписується на невживану приватну зону (U+E000+). Кількість
записів та сама, гліфи цілі, таблиця перечитується відсортованою.
Наслідок: TMP не знаходить, скажімо, U+002C у базовому шрифті й іде у
кириличний асет, де кома тепер є.

  python hide_base_punct.py plan | apply
"""

from __future__ import annotations

import glob
import io
import json
import os
import struct
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402
from scan_all_fonts import Window, bundle_nodes  # noqa: E402
from repoint_fonts import build_cab_index, CYR_TMP, CYR_BOLD_TMP  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCAN = kitconfig.SCAN
BACKUP = kitconfig.BACKUP
GAME = kitconfig.GAME
RES = os.path.join(GAME, "resources.assets")

# Приховуємо лише те, що ми ГАРАНТОВАНО поклали в кириличні асети.
# Пробіл (U+0020) НЕ чіпаємо — на ньому тримається розбиття рядків.
# Кутові дужки НЕ чіпаємо — це розмітка TMP.
HIDE = [ord(c) for c in ".,!?:;-—–…«»()’‘“”„'\"№·•/*%°−+" "0123456789"]
PUA = 0xE000            # куди перенумеровуємо

# У скани попали й ті шрифти, що НА ЧАС СКАНУ вели у SDF-варіанти (чужий клас).
# Після перецілювання вони теж ведуть у наші слоти, тому пунктуацію ховаємо і в них.
CYR_SLOTS = {CYR_TMP, CYR_BOLD_TMP, 775181479505102588, -5519819465463294359}
TAG = "punct"          # префікс бекапу; другий прохід запускати з іншим


def hide_in_object(o, node=None):
    """-> (нові байти, скільки прибрано) або (None, причина)"""
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter

    raw = o.get_raw_data()
    node = node or o.serialized_type.node
    d = o.read_typetree(node)
    w = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w, o.assets_file)
    if w.bytes != raw:
        return None, "перезбірка не ідентична"

    tbl = d.get("m_CharacterTable") or []
    taken = {c["m_Unicode"] for c in tbl}
    n = 0
    free = PUA
    for c in tbl:
        if c["m_Unicode"] in HIDE:
            while free in taken:
                free += 1
            taken.add(free)
            c["m_Unicode"] = free
            n += 1
    if not n:
        return None, "нема чого приховувати"
    tbl.sort(key=lambda c: c["m_Unicode"])        # формат вимагає сортування

    w2 = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w2, o.assets_file)
    blob = w2.bytes
    if len(blob) != len(raw):
        return None, f"розмір змінився {len(blob)-len(raw):+d}"
    return blob, n


def main():
    global TAG
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    if len(sys.argv) > 2:
        TAG = sys.argv[2]
    import UnityPy

    # ── які шрифти вважати базовими: ті, що ведуть у наші кириличні слоти
    fonts = {}
    for f in glob.glob(os.path.join(SCAN, "usage_*.json")):
        for r in json.load(open(f, encoding="utf-8")).get("fonts", []):
            fonts[(r["file"], int(r["path_id"]))] = r
    idx = build_cab_index()

    # 🔴 Фільтр за fallbacks зі СКАНУ пропускав шрифти, яким кирилицю додали
    # пізніше (жирні варіанти). Тому беремо всі шрифти, а наявність кириличного
    # запасного перевіряємо вже по ЖИВОМУ файлу нижче.
    bycab = defaultdict(list)
    for (cab, pid), r in fonts.items():
        if (r.get("name") or "").startswith("NotoSerifCyrillic"):
            continue
        bycab[cab].append((pid, r["name"]))

    patches = defaultdict(list)
    total_chars = 0
    print(f"символів до приховування: {len(HIDE)} — "
          f"{' '.join(chr(u) for u in HIDE)}")
    for cab, items in sorted(bycab.items()):
        if cab not in idx:
            print(f"  🔴 нема ноди {cab}")
            continue
        p, ds, off, size = idx[cab]
        fh = open(p, "rb")
        sf = UnityPy.Environment().load_file(
            io.BufferedReader(Window(fh, ds + off, size), buffer_size=1 << 20), name=cab)
        base = ds + off
        print(f"\n--- {os.path.basename(p)[:38]} / {cab[:22]}")
        for pid, nm in sorted(items, key=lambda x: x[1]):
            if pid not in sf.objects:
                continue
            o = sf.objects[pid]
            try:
                if not any(x.get("m_PathID") in CYR_SLOTS
                           for x in (o.read_typetree().get("m_FallbackFontAssetTable") or [])):
                    continue
            except Exception:
                continue
            blob, info = hide_in_object(o)
            if blob is None:
                print(f"    — {nm}: {info}")
                continue
            patches[p].append((base + o.byte_start, blob))
            total_chars += info
            print(f"    ok {nm}: приховано {info}")
        fh.close()

    # ── resources.assets («нові» шрифти, typetree позичений)
    from inplace_resources import borrow_node, SLOT_FIXEL, SLOT_KYIV
    node, _ = borrow_node()
    smap = json.load(open(os.path.join(SCAN, "scripts_map.json"), encoding="utf-8"))
    sfr = UnityPy.Environment().load_file(open(RES, "rb"), name="resources.assets")
    print("\n--- resources.assets")

    def mbname(raw):
        n = struct.unpack_from("<i", raw, 28)[0]
        return raw[32:32 + n].decode("utf8", "replace") if 0 <= n <= 200 else ""

    for pid, o in sfr.objects.items():
        if o.type.name != "MonoBehaviour" or pid in (SLOT_FIXEL, SLOT_KYIV):
            continue
        raw = o.get_raw_data()
        fid, spid = struct.unpack_from("<iq", raw, 16)
        if not (fid == 2 and smap.get(f"ggm:{spid}") == "TMP_FontAsset"):
            continue
        try:
            d = o.read_typetree(node)
        except Exception:
            continue
        if not any(x.get("m_PathID") in (SLOT_FIXEL, SLOT_KYIV)
                   for x in (d.get("m_FallbackFontAssetTable") or [])):
            continue
        blob, info = hide_in_object(o, node)
        nm = mbname(raw)
        if blob is None:
            print(f"    — {nm}: {info}")
            continue
        patches[RES].append((o.byte_start, blob))
        total_chars += info
        print(f"    ok {nm}: приховано {info}")

    nfiles = len(patches)
    npatch = sum(len(v) for v in patches.values())
    nbytes = sum(len(b) for v in patches.values() for _, b in v)
    print(f"\nшрифтів: {npatch}, файлів: {nfiles}, символів: {total_chars}, "
          f"байтів запису: {nbytes/1e6:.2f} МБ")
    if mode != "apply":
        print("(режим plan — нічого не записано)")
        return

    os.makedirs(BACKUP, exist_ok=True)
    for p, items in patches.items():
        fsize = os.path.getsize(p)
        for off, blob in items:
            if off < 0 or off + len(blob) > fsize:
                raise SystemExit(f"ЗАПИС ЗА МЕЖУ {os.path.basename(p)} — скасовано")
        tag = TAG + "_" + "_".join(os.path.basename(p).split("_")[:2])
        meta = []
        with open(p, "rb") as f:
            for off, blob in items:
                f.seek(off)
                bn = f"{tag}_{off}.bin"
                open(os.path.join(BACKUP, bn), "wb").write(f.read(len(blob)))
                meta.append(dict(file=p, offset=off, size=len(blob), backup=bn))
        json.dump(meta, open(os.path.join(BACKUP, f"{tag}.json"), "w"), indent=1)
        with open(p, "r+b") as f:
            for off, blob in items:
                f.seek(off)
                f.write(blob)
        print(f"записано {len(items)} шрифтів у {os.path.basename(p)[:44]} (бекап {tag}.json)")


if __name__ == "__main__":
    main()
