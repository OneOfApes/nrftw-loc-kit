"""
Гарнітури в кириличні слоти UI TOOLKIT — бандл + resources.assets.

🔴 Навіщо окремий інструмент. У грі ДВІ незалежні текстові підсистеми:

  TextMeshPro   `TMP_FontAsset`  (m_Script -> monoscripts) — увесь звичайний UI
  UI Toolkit    `FontAsset`      (m_Script -> Library/unity default resources,
                                  pathID 19001) — панелі мапи, журналу,
                                  активностей: MapChunkDetailsPanel,
                                  ActivityJournalEntryLabel, ActivityDetailsPanel,
                                  ActivityRewardPanel, ItemRewardBox,
                                  FontsStyleSheet, FallbackStyleSheet

Класи НЕ сумісні. Дати UITK-шрифту запасний TMP-класу (або навпаки) — тихий
нативний виліт без винятку в лозі. Саме це валило мапу й журнал, і саме через
це `Regular SDF` / `Bold SDF` двічі описували як «мертві залишки старого TMP».
Вони не мертві — це кириличні слоти UI Toolkit.

На щастя, будова в них ТА САМА, що в TMP-слотів:

  Regular SDF  42 336 Б  pt 112  cap 80  441 гліф / 441 символ / 441 used / 280 free
  Bold SDF     42 328 Б  pt 106  cap 76  те саме,  атлас 2048x2048 Alpha8 у .resS

тож гарнітура кладеться тим самим способом і без зміни розміру.

  python inplace_uitk.py plan | apply
"""

from __future__ import annotations

import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from inplace_font import (AA, BUNDLE, BACKUP, FIXEL, KYIV, NOTO, DIGIT_FONT,  # noqa: E402
                          PAD, GRAD, ATLAS, REL, BundleView, PlainView, _write)

import kitconfig  # noqa: E402

GAME = kitconfig.GAME
RES = os.path.join(GAME, "resources.assets")

# base_point / base_cap — метрики латинського UITK-шрифта, який цей слот обслуговує
# (Arcon UITK: 91/65, friz+Marcellus UITK: 145/102). Формула масштабу — як у TMP.
SLOTS_BUNDLE = {
    "fixel": dict(path_id=775181479505102588, name="UITK NotoSerifCyrillic-Regular SDF",
                  font=FIXEL, pt=112, base_point=91.0, base_cap=65.0, digits="regular"),
    "kyiv": dict(path_id=-5519819465463294359, name="UITK NotoSerifCyrillic-Bold SDF",
                 font=KYIV, pt=106, base_point=145.0, base_cap=102.0, digits=None),
}
SLOTS_RES = {
    "fixel": dict(path_id=3334, name="UITK 3334 Regular SDF",
                  font=FIXEL, pt=112, base_point=91.0, base_cap=65.0, digits="regular"),
    "kyiv": dict(path_id=3332, name="UITK 3332 Bold SDF",
                 font=KYIV, pt=106, base_point=145.0, base_cap=102.0, digits=None),
}


def borrow_uitk_node():
    """typetree UITK-FontAsset позичаємо з бандла — у resources.assets його нема."""
    v = BundleView(os.path.join(AA, BUNDLE))
    node = v.sf.objects[SLOTS_BUNDLE["fixel"]["path_id"]].serialized_type.node
    return v, node


def build_slot(view, slot, node=None, verbose=True):
    """🔴 КОНСЕРВАТИВНИЙ режим — і це принципово.

    Перша версія генерувала таблиці з нуля (свій набір символів, свої індекси
    гліфів, пунктуація+цифри замість рідкісної кирилиці). TMP таке ковтає, а
    ОТ UI TOOLKIT ВІДКИДАЄ АСЕТ ЦІЛКОМ і мовчки йде далі по ланцюгу запасних:
    російська кирилиця бралась із NotoSerifJP/SC (динамічні CJK, серифи, БЕЗ
    українських літер), а «і» — з NotInter (дефолт панелі, санс). Звідси
    «стара кирилиця з тонкою і» у журналі й на мапі, яку бачив користувач.
    Причина (підтверджено): ванільна `m_CharacterTable` ВІДСОРТОВАНА за
    юнікодом, а генератор писав свою в довільному порядку — двійковий пошук
    TextCore на несортованій таблиці не знаходить символи. (Кернінг ні до чого:
    у ванільних UITK-слотів 0 кернінг-записів.)

    Тому тут НЕ МІНЯЄТЬСЯ НІЧОГО, крім пікселів і метрик:
      * m_CharacterTable — байт у байт рідна (той самий набір, ті самі індекси);
      * m_GlyphTable — рідні індекси й порядок, нові лише метрики+прямокутники;
      * m_FaceInfo, m_FontFeatureTable, m_FreeGlyphRects — недоторкані;
      * набір символів = рідний (441 чиста кирилиця, БЕЗ цифр і пунктуації —
        цифри в UITK-панелях і у ваніли йшли з дальших запасних).
    """
    from build_sdf_font import build
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter
    import numpy as np

    o = view.sf.objects[slot["path_id"]]
    orig_raw = o.get_raw_data()
    nd = node or o.serialized_type.node
    d = o.read_typetree(nd)

    w = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, nd, w, o.assets_file)
    if w.bytes != orig_raw:
        raise SystemExit(f"{slot['name']}: перезбірка НЕ ідентична — далі не йдемо")

    # рідний набір: unicode -> glyphIndex
    uni2idx = {c["m_Unicode"]: c["m_GlyphIndex"] for c in d["m_CharacterTable"]}
    charset = {chr(u) for u in uni2idx}      # build() чекає символи, не кодпоінти
    pt = d["m_FaceInfo"]["m_PointSize"]
    res = build(slot["font"], charset, pt, atlas=ATLAS,
                pad=d.get("m_AtlasPadding", PAD), grad=GRAD, filler=NOTO)
    if res["overflow"]:
        raise SystemExit(f"{slot['name']}: атлас переповнено на {len(res['overflow'])}")

    # нове: unicode -> (метрики, прямокутник) з нашої збірки
    ours_by_idx = {g["m_Index"]: g for g in res["glyphs"]}
    uni2new = {}
    for c in res["chars"]:
        g = ours_by_idx.get(c["m_GlyphIndex"])
        if g is not None:
            uni2new[c["m_Unicode"]] = g
    missing = set(uni2idx) - set(uni2new)
    if missing:
        raise SystemExit(f"{slot['name']}: {len(missing)} символів без гліфа")

    # зворотна мапа рідних індексів
    idx2uni = {}
    for u, gi in uni2idx.items():
        idx2uni.setdefault(gi, u)

    new_glyphs = []
    for g in d["m_GlyphTable"]:
        u = idx2uni.get(g["m_Index"])
        ng = dict(g)                      # рідні m_Index, m_Scale, m_AtlasIndex
        if u is not None and u in uni2new:
            src = uni2new[u]
            ng["m_Metrics"] = src["m_Metrics"]
            ng["m_GlyphRect"] = src["m_GlyphRect"]
        new_glyphs.append(ng)

    if verbose:
        print(f"  рідних гліфів {len(d['m_GlyphTable'])}, замінено метрик "
              f"{sum(1 for g in d['m_GlyphTable'] if idx2uni.get(g['m_Index']) in uni2new)}, "
              f"добрано з Noto {res['filled']}, пік SDF {res['peak']}")

    new = dict(d)
    new["m_GlyphTable"] = new_glyphs
    if len(res["used_rects"]) == len(d["m_UsedGlyphRects"]):
        new["m_UsedGlyphRects"] = res["used_rects"]
    # m_CharacterTable / m_FaceInfo / m_FontFeatureTable / m_FreeGlyphRects — рідні

    w2 = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(new, nd, w2, o.assets_file)
    blob = w2.bytes
    off, size = view.abs_obj(slot["path_id"])
    if verbose:
        print(f"  асет: {size} -> {len(blob)} ({len(blob)-size:+d}), зсув {off}")
    if len(blob) != size:
        raise SystemExit(f"{slot['name']}: РОЗМІР ЗМІНИВСЯ на {len(blob)-size:+d}")

    tex = view.sf.objects[d["m_AtlasTextures"][0]["m_PathID"]]
    td = tex.read_typetree() if node is None else tex.read_typetree(view.tex_node)
    sd = td["m_StreamData"]
    raw_atlas = np.flipud(np.array(res["atlas"], dtype=np.uint8)).tobytes()
    a_off = view.abs_stream(sd["path"], sd["offset"])
    if verbose:
        print(f"  атлас «{td.get('m_Name')}» {td['m_Width']}x{td['m_Height']} "
              f"-> {len(raw_atlas)} Б на зсуві {a_off} (рідних {sd['size']})")
    if len(raw_atlas) != sd["size"]:
        raise SystemExit("розмір атласу не збігається")
    return dict(asset_off=off, asset_bytes=blob, atlas_off=a_off, atlas_bytes=raw_atlas,
                name=slot["name"])


def run(mode):
    print("=" * 76)
    print("UI TOOLKIT — гарнітури в кириличні слоти" +
          ("" if mode == "apply" else "   (ПЛАН, без запису)"))
    print("=" * 76)

    # ── бандл
    bv = BundleView(os.path.join(AA, BUNDLE))
    patches = []
    for key, slot in SLOTS_BUNDLE.items():
        print(f"\n### БАНДЛ {key.upper()} -> {slot['name']}")
        r = build_slot(bv, slot)
        patches += [(r["asset_off"], r["asset_bytes"]), (r["atlas_off"], r["atlas_bytes"])]
    if mode == "apply":
        _write(bv.path, patches, "uitk_bundle")
    bv.close()

    # ── resources.assets (typetree позичаємо з бандла)
    donor, node = borrow_uitk_node()
    tex_node = None
    for pid, o in donor.sf.objects.items():
        if o.type.name == "Texture2D":
            tex_node = o.serialized_type.node
            break
    pv = PlainView(RES)
    pv.tex_node = tex_node
    patches = []
    for key, slot in SLOTS_RES.items():
        print(f"\n### RESOURCES {key.upper()} -> {slot['name']}")
        r = build_slot(pv, slot, node=node)
        patches.append((r["asset_off"], r["asset_bytes"]))
        ress = RES + ".resS"
        if mode == "apply":
            _write(ress, [(r["atlas_off"], r["atlas_bytes"])], f"uitk_resS_{key}")
    if mode == "apply":
        _write(RES, patches, "uitk_resources")
    pv.close()
    donor.close()
    print("\nГОТОВО" if mode == "apply" else "\nОБИДВА UITK-СЛОТИ ВКЛАДАЮТЬСЯ БЕЗ ЗМІНИ РОЗМІРУ")
    return 0


if __name__ == "__main__":
    sys.exit(run(sys.argv[1] if len(sys.argv) > 1 else "plan"))
