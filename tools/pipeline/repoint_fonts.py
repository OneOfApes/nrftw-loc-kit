"""
Перецілювання посилань на кириличні шрифти — побайтово, на місці.

Що робить:
  1) кожному базовому шрифту переставляє кириличний елемент
     m_FallbackFontAssetTable на потрібний слот (Fixel або Kyiv);
  2) окремим написам (довгі повідомлення, що сидять на «кнопковому» шрифті)
     переставляє m_fontAsset на текстовий Arcon.

Кожна правка — рівно 8 байтів (m_PathID у PPtr). Розмір асета не змінюється,
файл не перезаписується. Перед записом кожна правка перевіряється:
перезбірка асета мусить дати ту саму довжину й відрізнятися рівно у 8 байтах.

  python repoint_fonts.py plan     # тільки показати, що буде зроблено
  python repoint_fonts.py apply    # вшити (з бекапом діапазонів)
"""

from __future__ import annotations

import glob
import io
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402
from scan_all_fonts import Window, bundle_nodes  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAME = kitconfig.GAME
AA = kitconfig.AA
SCAN = kitconfig.SCAN
BACKUP = kitconfig.BACKUP

DUP = "CAB-c96cdae22def2c264391645ea79e4d4c"
# 🔴 цілі — ЛИШЕ TMP-варіанти: SDF-варіанти належать іншому класу
# (m_Script -> unity default resources 19001) і валять TMP при ініціалізації.
CYR_TMP = -2444889057261992194          # -> Fixel (він і був рідною ціллю всього)
CYR_BOLD_TMP = -5959213582716284887     # -> Kyiv  (той самий клас, 0 посилань)
CYR_SDF = 775181479505102588            # чужий клас — НЕ ВИКОРИСТОВУВАТИ
CYR_BOLD_SDF = -5519819465463294359     # чужий клас — НЕ ВИКОРИСТОВУВАТИ
CYR_ALL = {CYR_TMP, CYR_SDF, CYR_BOLD_SDF, CYR_BOLD_TMP}

# «кнопковий» шрифт -> текстовий Arcon для довгих повідомлень
BTN_FONT = -8148225244525073731          # Arcon-RegularButton SDF
TEXT_FONT = None                         # знайдемо за назвою нижче

# 🔴 РОДИНУ ШРИФТІВ НЕ РОЗРИВАТИ. У всіх Arcon-* спільний жирний варіант
# ArconBold-Regular SDF - Variant, у всіх friz-quadrata-* — friz-...-bold-...Variant.
# Якщо частина родини піде в Kyiv, а частина у Fixel, то <b> усередині речення
# дасть чужу гарнітуру. Тому: уся родина friz + декоративні = Kyiv,
# уся родина Arcon + системні = основний текстовий шрифт (FONT_BODY).
KYIV_MARKS = ("friz", "marcellus", "standard-graf")
KYIV_EXACT = set()          # кнопковий Arcon теж Fixel: він з родини Arcon
                            # і малює hintText та довгі службові повідомлення
LONG_MSG = ("message", "descriptionText", "longerMessage", "thankyouText", "noMoney",
            "freeText", "itemText", "foodText", "statusText", "wipText", "localDetails",
            "SelectEnchantItemText", "SelectEnchantGemText")


def target_slot(name):
    n = (name or "").lower()
    if name in KYIV_EXACT or any(m in n for m in KYIV_MARKS):
        return CYR_BOLD_TMP, "KYIV"
    return CYR_TMP, "FIXEL"


# ─────────────────────────── індекс CAB -> нода бандла ───────────────────────────

def build_cab_index():
    idx = {}
    for f in sorted(os.listdir(AA)):
        if not f.endswith(".bundle"):
            continue
        p = os.path.join(AA, f)
        try:
            ds, nodes = bundle_nodes(p)
        except Exception:
            continue
        for off, size, fl, name in nodes:
            if name.endswith(".resS"):
                continue
            idx[name] = (p, ds, off, size)
    return idx


class View:
    def __init__(self, path, ds, off, size, name):
        import UnityPy

        self.path, self.name = path, name
        self._fh = open(path, "rb")
        buf = io.BufferedReader(Window(self._fh, ds + off, size), buffer_size=1 << 20)
        self.sf = UnityPy.Environment().load_file(buf, name=name)
        # byte_start уже містить header.data_offset — вдруге не додаємо
        self.base = ds + off

    def abs_obj(self, pid):
        o = self.sf.objects[pid]
        return self.base + o.byte_start, o.byte_size

    def close(self):
        self._fh.close()


def patch_pptr(view, pid, old_pathid, new_pathid, field):
    """Готує 8-байтову правку. -> (abs_offset, bytes, опис) або None."""
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter

    o = view.sf.objects[pid]
    raw = o.get_raw_data()
    node = o.serialized_type.node
    d = o.read_typetree()

    w = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w, o.assets_file)
    if w.bytes != raw:
        return None, f"перезбірка НЕ ідентична (pid={pid})"

    changed = 0
    if field == "fallback":
        for ref in d.get("m_FallbackFontAssetTable") or []:
            if isinstance(ref, dict) and ref.get("m_PathID") == old_pathid:
                ref["m_PathID"] = new_pathid
                changed += 1
    else:
        def walk(v, key=None):
            nonlocal changed
            if isinstance(v, dict):
                if key == field and v.get("m_PathID") == old_pathid:
                    v["m_PathID"] = new_pathid
                    changed += 1
                    return
                for k, vv in v.items():
                    walk(vv, k)
            elif isinstance(v, list):
                for vv in v:
                    walk(vv, key)
        walk(d)
    if changed != 1:
        return None, f"знайдено {changed} посилань замість 1 (pid={pid})"

    w2 = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w2, o.assets_file)
    new = w2.bytes
    if len(new) != len(raw):
        return None, f"розмір змінився {len(new)-len(raw):+d} (pid={pid})"
    diff = [i for i in range(len(raw)) if raw[i] != new[i]]
    if not diff:
        return None, f"нічого не змінилось (pid={pid})"
    if len(diff) > 8 or diff[-1] - diff[0] != len(diff) - 1:
        return None, f"різниця {len(diff)} байтів, не суцільна (pid={pid})"
    off, _ = view.abs_obj(pid)
    return (off + diff[0], new[diff[0]:diff[-1] + 1]), f"{len(diff)} Б @ {off + diff[0]}"


def load_registry():
    """Скани перекриваються (той самий бандл міг попасти у два прогони) —
    тому і шрифти, і власників дедуплікуємо за адресою."""
    fonts, holders = {}, {}
    for f in glob.glob(os.path.join(SCAN, "usage_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for r in d.get("fonts", []):
            fonts[(r["file"], int(r["path_id"]))] = r
        for h in d.get("holders", []):
            holders[(h["file"], int(h["path_id"]))] = h
    return fonts, list(holders.values())


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    fonts, holders = load_registry()
    idx = build_cab_index()

    # текстовий Arcon (той, що малює описи предметів — 317 гліфів)
    global TEXT_FONT
    for (fileq, pid), r in fonts.items():
        if fileq == DUP and r.get("name") == "Arcon-Regular SDF" and r.get("glyphs") == 317:
            TEXT_FONT = pid
    print(f"текстовий Arcon-Regular SDF: path_id={TEXT_FONT}")

    # ── 1. базові шрифти з кириличним запасним
    jobs = defaultdict(list)      # cab -> [(pid, old, new, field, опис)]
    for (fileq, pid), r in sorted(fonts.items(), key=lambda kv: kv[1].get("name") or ""):
        if r.get("name", "").startswith("NotoSerifCyrillic"):
            continue
        cyr = [int(b) for a, b in (r.get("fallbacks") or []) if int(b) in CYR_ALL]
        if not cyr:
            continue
        new, tag = target_slot(r["name"])
        if cyr[0] == new:
            continue
        jobs[fileq].append((pid, cyr[0], new, "fallback", f"{tag:5s} {r['name']}"))

    # ── 1b. написи, що сидять на CJK-заглушках (0 гліфів, без кириличного
    #        запасного) — вони тягли кирилицю з глобального ланцюга TMP і тому
    #        лишалися старим Noto. Найпомітніше: тултіп ключових слів предмета.
    #        Arcon-Regular SDF сам має JP/KR/SC/TC у запасних, тож CJK не втрачаємо.
    stubs = {pid for (fq, pid), r in fonts.items()
             if fq == DUP and r.get("glyphs") == 0
             and (r.get("name") or "").startswith(("NotoSerifJP", "NotoSerifKR",
                                                   "NotoSerifSC", "NotoSerifTC"))}
    cjk = 0
    for h in holders:
        for fld, cab, pid in h["refs"]:
            if cab == DUP and int(pid) in stubs:
                jobs[h["file"]].append((int(h["path_id"]), int(pid), TEXT_FONT,
                                        "m_fontAsset",
                                        f"CJK->  напис «{h.get('go_name','')}»"))
                cjk += 1
                break

    # ── 2. довгі повідомлення на «кнопковому» шрифті
    # (крок вимкнено) Раніше довгі повідомлення знімалися з «кнопкового» шрифта
    # на текстовий, бо кнопки були Kyiv. Тепер уся родина Arcon у Fixel, тому
    # кнопковий і текстовий шрифти однієї гарнітури — перецілювати нічого.
    msg = 0

    print(f"\nбазових шрифтів до перецілювання: {sum(1 for v in jobs.values() for j in v if j[3]=='fallback')}")
    print(f"написів-повідомлень до перецілювання: {msg}")
    print(f"написів на CJK-заглушках до перецілювання: {cjk}")
    print(f"файлів зачеплено: {len(jobs)}")

    all_patches = defaultdict(list)
    problems = []
    for cab, items in jobs.items():
        if cab not in idx:
            problems.append(f"нема ноди {cab}")
            continue
        p, ds, off, size = idx[cab]
        print(f"\n--- {os.path.basename(p)[:40]} / {cab[:24]}: {len(items)} правок")
        v = View(p, ds, off, size, cab)
        for pid, old, new, field, desc in items:
            if pid not in v.sf.objects:
                problems.append(f"{cab}: нема обʼєкта {pid}")
                continue
            res, info = patch_pptr(v, pid, old, new, field)
            if res is None:
                problems.append(f"{cab} {desc}: {info}")
                print(f"    🔴 {desc}: {info}")
            else:
                all_patches[p].append(res)
                print(f"    ok  {desc}  ({info})")
        v.close()

    print(f"\nусього правок: {sum(len(x) for x in all_patches.values())}, "
          f"байтів: {sum(len(b) for x in all_patches.values() for _, b in x)}")
    if problems:
        print(f"ПРОБЛЕМИ ({len(problems)}):")
        for q in problems[:30]:
            print("   ", q)

    if mode != "apply":
        print("\n(режим plan — нічого не записано)")
        return

    os.makedirs(BACKUP, exist_ok=True)
    for p, patches in all_patches.items():
        size = os.path.getsize(p)
        for off, blob in patches:
            if off < 0 or off + len(blob) > size:
                raise SystemExit(f"ЗАПИС ЗА МЕЖУ {os.path.basename(p)}: "
                                 f"{off}+{len(blob)} > {size} — скасовано")
        meta = []
        # ім'я бекапу мусить бути унікальним для файлу: world_assets і
        # world_scenes інакше зіткнулися б на спільному префіксі «world»
        tag = "repoint_" + "_".join(os.path.basename(p).split("_")[:2])
        with open(p, "rb") as f:
            for off, blob in patches:
                f.seek(off)
                meta.append(dict(file=p, offset=off, size=len(blob),
                                 old=f.read(len(blob)).hex()))
        json.dump(meta, open(os.path.join(BACKUP, f"{tag}.json"), "w"), indent=1)
        with open(p, "r+b") as f:
            for off, blob in patches:
                f.seek(off)
                f.write(blob)
        print(f"записано {len(patches)} правок у {os.path.basename(p)[:44]} "
              f"(бекап {tag}.json)")


if __name__ == "__main__":
    main()
