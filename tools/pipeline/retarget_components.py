"""
Перецілювання ОКРЕМИХ КОМПОНЕНТІВ UI на інший базовий шрифт.

Навіщо: одна й та сама гарнітура малює і те, що має бути Kyiv, і те, що має
бути Fixel (`friz-quadrata-std-medium_clean SDF TMP` — і заголовок екрана, і
підписи «Вартість»/«Вимоги»). Один асет не може бути двома гарнітурами, тому
одиниця перемикання тут — не шрифт, а КОМПОНЕНТ (`m_fontAsset`, 8 байтів).

🔴 Родини шрифтів це НЕ розриває: жирні варіанти (`ArconBold-...Variant`,
`friz-...-bold-...Variant`) лишаються там, де були, тому `<b>` усередині
речення й далі дає ту саму гарнітуру, що й решта рядка.

Разом із `m_fontAsset` переставляємо і `m_sharedMaterial` — компонент тримає
окреме посилання на матеріал СТАРОГО шрифта, а в матеріалі лежить атлас.
Донора беремо в тому самому CAB: матеріал, яким уже користуються інші
компоненти цільового шрифта. Якщо донора немає — лишаємо як є: TMP на
`LoadFontAsset` бачить розбіжність атласу й сам підставляє рідний матеріал
шрифта (але тоді можуть зникнути обведення/тінь, тому це видно в звіті).

  python retarget_components.py plan     # нічого не пише, лише рахує
  python retarget_components.py apply
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402
from repoint_fonts import View, build_cab_index, DUP  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SCAN = kitconfig.SCAN
BACKUP = kitconfig.BACKUP

# ─────────────────────────────── правила ───────────────────────────────
# path   — шлях у ієрархії (parents/go_name)
# frm    — чіпаємо лише те, що зараз сидить на шрифті з цим префіксом
#          (щоб не зачепити LiberationSans — на ньому іконки-гліфи керування)
# skip   — go_name, які лишаються як є
RULES = [
    dict(
        tag="tooltip_body", to="Arcon-Regular SDF", frm="friz",
        title="тіло превью предмета -> Fixel",
        path=re.compile(r"dynamiclyExpandingElements/containerTitle/"),
        skip={"itemNameText", "weaponslotName", "shieldslotName"},
    ),
    dict(
        tag="world_location", to="friz-quadrata-std-bold-browndirt SDF", frm="Arcon",
        title="плашка локації у світі -> Kyiv",
        path=re.compile(r"playerHUD/playerTimeOfDay/playerLocation/"),
        skip=set(),
    ),
    dict(
        tag="stash_filters", to="friz-quadrata-std-medium_clean SDF TMP", frm="Arcon",
        title="вкладки й фільтри скрині -> Kyiv",
        # 🔴 `inventorySorting_*` тут НЕМАЄ навмисно: це нижня панель
        # «СОРТУВАННЯ: ЧАС», а не верхній правий фільтр. Значення сортування
        # користувач хоче лишити у Fixel.
        path=re.compile(r"(FilterButtonParent/"
                        r"|/inventoryFilterItem[^/]*/text$"
                        r"|/vendorTabShared/text$"
                        r"|inventoryTabShared/[^/]*/titleText$"
                        r"|containerElement/(categoryGroup|lockedGroup)/"
                        r"(name$|nameButton/text$)"
                        r"|containerElement/[A-Za-z]+Tab/text$)"),
        skip=set(),
    ),
    dict(
        tag="map_all_kyiv", to="friz-quadrata-std-medium_clean SDF TMP", frm="Arcon",
        title="усе на екрані мапи -> Kyiv",
        path=re.compile(r"mapScreen/"),
        # `text (2)` під `iconBackground` малює <sprite=...> — іконки кнопок,
        # тексту там нема, і чіпати їх не треба
        skip={"text (2)"},
    ),
    dict(
        tag="collections_tabs", to="friz-quadrata-std-bold-browndirt SDF", frm="Arcon",
        title="вкладки речей (Зброя/Обладунки/…) -> Kyiv",
        # WeaponsButton/OffHandButton уже на friz-bold-browndirt — цілимо в той
        # самий асет, щоб усі 7 вкладок були однією гарнітурою
        path=re.compile(r"ButtonsVerticalWrapper/[A-Za-z]+Button/LabelGroup/text$"),
        skip=set(),
    ),
    dict(
        tag="bottom_hints", to="friz-quadrata-std-medium_clean SDF TMP", frm="Arcon",
        title="нижні кнопки-підказки на всіх екранах -> Kyiv",
        # menuFooter/aInstruction/labelA тощо: текст («Перемістити», «Викинути»,
        # «Назад»…) підставляється в рантаймі, тому ловимо за структурою, не за
        # текстом. Іконки клавіш (LiberationSans) і спрайти сюди не потрапляють
        # через frm="Arcon" і go_name label*/text.
        path=re.compile(r"(menuFooter[^/]*/[a-zA-Z]{1,4}Instruction[^/]*/label"
                        r"|[a-zA-Z]{1,4}Instruction[^/]*/label[A-Z]"
                        r"|/footer/[a-z]Group/text$"
                        r"|moneyPrompt/[ab]Group/text$)"),
        skip=set(),
    ),
    dict(
        tag="settings_dividers", to="friz-quadrata-std-medium_clean SDF TMP",
        frm="Liberation",
        title="заголовки розділів налаштувань -> Kyiv",
        path=re.compile(r"dividerSettingsItemGUI/label$"),
        skip=set(),
    ),
    dict(
        tag="mainmenu_buttons", to="friz-quadrata-std-medium_clean SDF TMP", frm="Arcon",
        title="кнопки головного меню -> Kyiv",
        path=re.compile(r"mainMenu/mainScreen/content/content/leftColumn/pane/"
                        r"fields/[^/]+Button/text$"),
        skip=set(),
    ),
]


def load_registry():
    fonts, holders = {}, {}
    for f in glob.glob(os.path.join(SCAN, "usage_*.json")):
        d = json.load(open(f, encoding="utf-8"))
        for r in d.get("fonts", []):
            fonts[(r["file"], int(r["path_id"]))] = r
        for h in d.get("holders", []):
            holders[(h["file"], int(h["path_id"]))] = h
    return fonts, list(holders.values())


def font_pid(fonts, name):
    """path_id шрифта в бандлі DUP. `Arcon-Regular SDF` там два — беремо живий
    (317 гліфів), бо другий — порожня заглушка старого формату."""
    cands = [(pid, r) for (cab, pid), r in fonts.items()
             if cab == DUP and r.get("name") == name]
    if not cands:
        raise SystemExit(f"шрифт не знайдено: {name}")
    live = [pid for pid, r in cands if (r.get("glyphs") or 0) > 0]
    if len(live) != 1:
        raise SystemExit(f"неоднозначний шрифт {name}: {[c[0] for c in cands]}")
    return live[0]


def comp_font(h):
    for fld, cab, pid in h["refs"]:
        if fld == "m_fontAsset":
            return cab, int(pid)
    return None, None


def read_tt(view, pid):
    o = view.sf.objects.get(pid)
    if o is None:
        return None, None
    try:
        return o, o.read_typetree()
    except Exception:
        return o, None


def find_pptr(d, field):
    """перший PPtr під ключем `field` -> (m_FileID, m_PathID) | None"""
    out = []

    def walk(v, key=None):
        if out:
            return
        if isinstance(v, dict):
            if key == field and "m_PathID" in v:
                out.append((v.get("m_FileID"), v.get("m_PathID")))
                return
            for k, vv in v.items():
                walk(vv, k)
        elif isinstance(v, list):
            for vv in v:
                walk(vv, key)

    walk(d)
    return out[0] if out else None


def patch_fields(view, pid, changes):
    """changes: [(field, (old_fid, old_pid), (new_fid, new_pid))]
    -> ([(abs_offset, bytes)], опис) | (None, причина)"""
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter

    o = view.sf.objects[pid]
    raw = o.get_raw_data()
    node = o.serialized_type.node
    d = o.read_typetree()

    w = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w, o.assets_file)
    if w.bytes != raw:
        return None, "перезбірка НЕ ідентична"

    for field, old, new in changes:
        cnt = 0

        def walk(v, key=None):
            nonlocal cnt
            if isinstance(v, dict):
                if key == field and (v.get("m_FileID"), v.get("m_PathID")) == old:
                    v["m_FileID"], v["m_PathID"] = new
                    cnt += 1
                    return
                for k, vv in v.items():
                    walk(vv, k)
            elif isinstance(v, list):
                for vv in v:
                    walk(vv, key)

        walk(d)
        if cnt != 1:
            return None, f"{field}: {cnt} збігів замість 1"

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
    if not runs:
        return None, "нічого не змінилось"
    nbytes = sum(b - a for a, b in runs)
    if len(runs) > 3 or nbytes > 40:
        return None, f"підозрілий diff: {len(runs)} діапазонів, {nbytes} Б"
    base, _ = view.abs_obj(pid)
    return ([(base + a, nb[a:b]) for a, b in runs],
            f"{len(runs)} діап. / {nbytes} Б")


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    fonts, holders = load_registry()
    idx = build_cab_index()

    targets = {r["tag"]: font_pid(fonts, r["to"]) for r in RULES}
    print("цільові шрифти:")
    for r in RULES:
        print(f"  {r['tag']:18} -> {r['to']:42} path_id={targets[r['tag']]}")

    # ── розкладка робіт по CAB
    jobs = defaultdict(list)          # cab -> [(pid, old_font, new_font, tag, go)]
    used_by_font = defaultdict(lambda: defaultdict(list))   # cab -> font_pid -> [pid]
    for h in holders:
        cab, fpid = comp_font(h)
        if fpid is None:
            continue
        used_by_font[h["file"]][fpid].append(int(h["path_id"]))
        name = fonts.get((cab, fpid), {}).get("name", "")
        path = (h.get("parents") or "") + "/" + (h.get("go_name") or "")
        for r in RULES:
            if not r["path"].search(path):
                continue
            if not name.startswith(r["frm"]):
                continue
            if (h.get("go_name") or "") in r["skip"]:
                continue
            new = targets[r["tag"]]
            if cab == DUP and fpid == new:
                break
            # cab == DUP -> міняється лише m_PathID (8 Б);
            # інший CAB (LiberationSans живе окремо) -> ще й m_FileID
            jobs[h["file"]].append((int(h["path_id"]), fpid, new, r["tag"],
                                    h.get("go_name") or "", cab == DUP))
            break

    print("\nзнайдено компонентів:")
    per_tag = Counter(j[3] for items in jobs.values() for j in items)
    for r in RULES:
        print(f"  {r['tag']:18} {per_tag.get(r['tag'], 0):5}   {r['title']}")
    print("  по файлах:")
    for cab, items in sorted(jobs.items(), key=lambda kv: -len(kv[1])):
        base = os.path.basename(idx[cab][0])[:46] if cab in idx else "??? " + cab
        print(f"    {len(items):5}  {base}")

    patches = defaultdict(list)
    skipped = Counter()
    for cab, items in sorted(jobs.items()):
        if cab not in idx:
            print(f"  🔴 CAB не знайдено: {cab} ({len(items)} компонентів)")
            skipped["немає CAB"] += len(items)
            continue
        p, ds, off, size = idx[cab]
        v = View(p, ds, off, size, cab)

        # донори матеріалів: чим уже користуються компоненти цільового шрифта
        donor = {}
        for new in {j[2] for j in items}:
            c = Counter()
            for pid in used_by_font[cab].get(new, [])[:40]:
                o, d = read_tt(v, pid)
                if d is None:
                    continue
                m = find_pptr(d, "m_sharedMaterial")
                if m:
                    c[m] += 1
            if c:
                donor[new] = c.most_common(1)[0][0]
        for new, m in donor.items():
            print(f"    матеріал-донор для {new}: {m}")
        for new in {j[2] for j in items}:
            if new not in donor:
                print(f"    ⚠ у {cab[:18]} немає донора матеріалу для {new} — "
                      f"TMP підставить рідний матеріал шрифта сам")

        # m_FileID, під яким цей CAB бачить бандл DUP (звідти всі цільові
        # шрифти). Учимо з будь-якого сусіда, що вже дивиться в DUP.
        dup_fid = None
        for new in {j[2] for j in items}:
            for pid in used_by_font[cab].get(new, [])[:20]:
                o, d = read_tt(v, pid)
                if d is None:
                    continue
                fa = find_pptr(d, "m_fontAsset")
                if fa and fa[1] == new:
                    dup_fid = fa[0]
                    break
            if dup_fid is not None:
                break
        okc = Counter()
        for pid, old, new, tag, go, same_cab in items:
            o, d = read_tt(v, pid)
            if d is None:
                skipped["не читається"] += 1
                continue
            fa = find_pptr(d, "m_fontAsset")
            if fa is None or fa[1] != old:
                skipped["m_fontAsset не збігся"] += 1
                continue
            if same_cab:
                new_ptr = (fa[0], new)
            elif dup_fid is not None:
                new_ptr = (dup_fid, new)
            else:
                skipped["невідомий m_FileID для DUP"] += 1
                continue
            changes = [("m_fontAsset", fa, new_ptr)]
            sm = find_pptr(d, "m_sharedMaterial")
            if new in donor and sm and sm != donor[new]:
                changes.append(("m_sharedMaterial", sm, donor[new]))
                mm = find_pptr(d, "m_Material")
                if mm == sm:
                    changes.append(("m_Material", mm, donor[new]))
            res, info = patch_fields(v, pid, changes)
            if res is None:
                skipped[info.split(":")[0]] += 1
                continue
            patches[p].extend(res)
            okc[tag] += 1
        v.close()
        print(f"    готово: {dict(okc)}")

    tot = sum(len(x) for x in patches.values())
    print(f"\nусього діапазонів до запису: {tot} "
          f"({sum(len(b) for x in patches.values() for _, b in x)} байтів)")
    if skipped:
        print(f"пропущено: {dict(skipped)}")

    if mode != "apply":
        print("\n(режим plan — у файли НІЧОГО не записано)")
        return 0

    os.makedirs(BACKUP, exist_ok=True)
    for p, items in patches.items():
        if not items:
            continue
        fsize = os.path.getsize(p)
        for off, blob in items:
            if off < 0 or off + len(blob) > fsize:
                raise SystemExit(f"ЗАПИС ЗА МЕЖУ {os.path.basename(p)} — скасовано")
        tag = "retarget_" + "_".join(os.path.basename(p).split("_")[:2])
        meta = []
        with open(p, "rb") as f:
            for off, blob in items:
                f.seek(off)
                meta.append(dict(file=p, offset=off, size=len(blob),
                                 old=f.read(len(blob)).hex()))
        json.dump(meta, open(os.path.join(BACKUP, f"{tag}.json"), "w"), indent=0)
        with open(p, "r+b") as f:
            for off, blob in items:
                f.seek(off)
                f.write(blob)
        print(f"записано {len(items)} правок у {os.path.basename(p)[:46]} "
              f"(журнал {tag}.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
