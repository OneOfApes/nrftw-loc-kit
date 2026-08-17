"""
Те саме побайтове вшивання, але для resources.assets.

Особливість файлу: у ньому НЕМА typetree, тому typetree для TMP_FontAsset
позичається з бандла duplicateassetisolation (структура та сама — перевірено
звіркою байт-у-байт після перезбірки).

Слоти:
  3335  NotoSerifCyrillic-Regular TMP  <- Fixel   (на нього дивиться весь «новий» набір)
  3333  NotoSerifCyrillic-Bold TMP     <- Kyiv    (вільний, 0 посилань)

Перецілювання:
  * «нові» шрифти friz/Marcellus  3335 -> 3333   (через typetree)
  * «старі» шрифти (формат TMP 1.x, не читаються)  3334 -> 3335/3333
    сирою підміною 12-байтового PPtr

  python inplace_resources.py plan | apply
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402
from scan_all_fonts import Window, bundle_nodes  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAME = kitconfig.GAME
AA = kitconfig.AA
RES = os.path.join(GAME, "resources.assets")
RESS = os.path.join(GAME, "resources.assets.resS")
SCAN = kitconfig.SCAN
BACKUP = kitconfig.BACKUP

SLOT_FIXEL, SLOT_KYIV = 3335, 3333
OLD_CYR = 3334                     # старий кириличний, куди дивиться «старий» набір

from inplace_font import FIXEL, KYIV, NOTO, PAD, GRAD, ATLAS, REL, DIGIT_FONT  # noqa: E402

BUILD = {
    SLOT_FIXEL: dict(font=FIXEL, pt=112, base_point=159.0, base_cap=114.0, tag="FIXEL",
                     digits="regular"),
    SLOT_KYIV: dict(font=KYIV, pt=106, base_point=145.0, base_cap=102.0, tag="KYIV",
                    digits=None),
}
# той самий список, що в repoint_fonts.py — Kyiv лишається на заголовках
from repoint_fonts import KYIV_MARKS, KYIV_EXACT  # noqa: E402


def borrow_node():
    """typetree для TMP_FontAsset і Texture2D — позичені з бандла.
    Вбудовані typetree UnityPy для цієї версії Unity не збігаються (перевірено
    на GameObject/Material), тому беремо саме ті, з якими зібрана гра."""
    import UnityPy

    b = [x for x in os.listdir(AA) if x.startswith("duplicateassetisolation")][0]
    ds, nodes = bundle_nodes(os.path.join(AA, b))
    off, size, fl, name = [n for n in nodes if not n[3].endswith(".resS")][0]
    fh = open(os.path.join(AA, b), "rb")
    sf = UnityPy.Environment().load_file(
        io.BufferedReader(Window(fh, ds + off, size), buffer_size=1 << 20), name=name)
    font = tex = None
    for st in sf.types:
        if st.node is None:
            continue
        if any(c.m_Name == "m_FaceInfo" for c in (st.node.m_Children or [])):
            font = font or st.node
        if st.class_id == 28 and any(c.m_Name == "m_TextureFormat"
                                    for c in (st.node.m_Children or [])):
            tex = tex or st.node
    if font is None or tex is None:
        raise SystemExit("не знайшов потрібних typetree у бандлі")
    return font, tex


def mb_name(raw):
    if len(raw) < 32:
        return ""
    n = struct.unpack_from("<i", raw, 28)[0]
    if not (0 <= n <= 200) or 32 + n > len(raw):
        return ""
    try:
        return raw[32:32 + n].decode("utf8")
    except UnicodeDecodeError:
        return ""


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "plan"
    import numpy as np
    import UnityPy
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter
    from build_sdf_font import build
    from charset_ua import make_charset

    node, texnode = borrow_node()
    sf = UnityPy.Environment().load_file(open(RES, "rb"), name="resources.assets")
    base = 0      # ObjectReader.byte_start для звичайного файлу вже абсолютний
    objs = sf.objects
    print(f"resources.assets: обʼєктів {len(objs)}, data_offset={base}")

    patches_res, patches_ress = [], []

    # ─── 1. вшити гарнітури у два слоти
    for pid, cfg in BUILD.items():
        o = objs[pid]
        raw = o.get_raw_data()
        d = o.read_typetree(node)
        w = EndianBinaryWriter(endian=o.reader.endian)
        TypeTreeHelper.write_typetree(d, node, w, o.assets_file)
        print(f"\n### {cfg['tag']} -> {d['m_Name']} (path_id={pid})")
        print(f"  перезбірка ідентична: {w.bytes == raw}")
        if w.bytes != raw:
            raise SystemExit("перезбірка не ідентична — далі не йдемо")

        dfont = DIGIT_FONT if cfg.get("digits") == "regular" else None
        charset, _ = make_charset(cfg["font"], NOTO, cfg["pt"], digit_font=dfont)
        res = build(cfg["font"], charset, cfg["pt"], atlas=ATLAS,
                    pad=PAD, grad=GRAD, filler=NOTO,
                    extra=[(dfont, set("0123456789"))] if dfont else None)
        if res["overflow"]:
            raise SystemExit("атлас переповнено")
        og = (len(d["m_GlyphTable"]), len(d["m_CharacterTable"]), len(d["m_UsedGlyphRects"]))
        ng = (len(res["glyphs"]), len(res["chars"]), len(res["used_rects"]))
        print(f"  кількості: рідні {og}, нові {ng}")
        if og != ng:
            raise SystemExit("кількості не збігаються")

        own = res["face"]["m_CapLine"] / res["face"]["m_PointSize"]
        scale = round(REL * (cfg["base_cap"] / cfg["base_point"]) / own, 4)
        face = dict(d["m_FaceInfo"])
        for k, v in res["face"].items():
            if k in ("m_FamilyName", "m_StyleName") or k not in face:
                continue
            face[k] = v
        face["m_Scale"] = scale
        new = dict(d)
        new["m_FaceInfo"] = face
        new["m_GlyphTable"] = res["glyphs"]
        new["m_CharacterTable"] = res["chars"]
        new["m_UsedGlyphRects"] = res["used_rects"]

        w2 = EndianBinaryWriter(endian=o.reader.endian)
        TypeTreeHelper.write_typetree(new, node, w2, o.assets_file)
        blob = w2.bytes
        print(f"  асет: {len(raw)} -> {len(blob)} ({len(blob)-len(raw):+d}), "
              f"m_Scale={scale}, зсув {base + o.byte_start}")
        if len(blob) != len(raw):
            raise SystemExit("розмір змінився")
        patches_res.append((base + o.byte_start, blob))

        # матеріал слота: TMP бере з нього _GradientScale
        m = d.get("m_Material") or {}
        if m.get("m_PathID"):
            try:
                md = objs[m["m_PathID"]].read_typetree()
                gs = dict(md["m_SavedProperties"]["m_Floats"]).get("_GradientScale")
                print(f"  матеріал «{md.get('m_Name')}»: _GradientScale={gs}")
            except Exception as e:
                print(f"  матеріал path_id={m['m_PathID']} (не читається: {str(e)[:50]})")

        # атлас
        tex = objs[d["m_AtlasTextures"][0]["m_PathID"]]
        td = tex.read_typetree(texnode)
        sd = td.get("m_StreamData") or {}
        sheet = np.array(res["atlas"], dtype=np.uint8)
        raw_atlas = np.flipud(sheet).tobytes()
        if sd.get("size"):
            print(f"  атлас «{td['m_Name']}» {td['m_Width']}x{td['m_Height']} "
                  f"format={td['m_TextureFormat']} у .resS зсув {sd['offset']} розмір {sd['size']}")
            if sd["size"] != len(raw_atlas):
                raise SystemExit("розмір атласу не збігається")
            patches_ress.append((sd["offset"], raw_atlas))
        else:
            inline = td.get("image data") or b""
            a_off = base + tex.byte_start + (len(tex.get_raw_data()) - len(inline))
            print(f"  атлас «{td['m_Name']}» ВСЕРЕДИНІ асета: {len(inline)} Б, зсув {a_off}")
            if len(inline) != len(raw_atlas):
                raise SystemExit("розмір вбудованого атласу не збігається")
            patches_res.append((a_off, raw_atlas))

    # ─── 2. перецілити «нові» шрифти friz/Marcellus на слот Kyiv
    print("\n" + "=" * 70)
    print("ПЕРЕЦІЛЮВАННЯ «НОВИХ» ШРИФТІВ")
    smap = json.load(open(os.path.join(SCAN, "scripts_map.json"), encoding="utf-8"))
    fonts_new, fonts_old = {}, {}
    for pid, o in objs.items():
        if o.type.name != "MonoBehaviour":
            continue
        raw = o.get_raw_data()
        fid, spid = struct.unpack_from("<iq", raw, 16)
        cls = smap.get(f"ggm:{spid}") if fid == 2 else f"fid{fid}:{spid}"
        if cls == "TMP_FontAsset":
            fonts_new[pid] = mb_name(raw)
        elif cls == "fid1:19001":
            fonts_old[pid] = mb_name(raw)

    for pid, nm in sorted(fonts_new.items(), key=lambda kv: kv[1]):
        if pid in BUILD:
            continue
        want_kyiv = any(m in (nm or "").lower() for m in KYIV_MARKS)
        if not want_kyiv:
            continue
        o = objs[pid]
        raw = o.get_raw_data()
        d = o.read_typetree(node)
        w = EndianBinaryWriter(endian=o.reader.endian)
        TypeTreeHelper.write_typetree(d, node, w, o.assets_file)
        if w.bytes != raw:
            print(f"  🔴 {nm}: перезбірка не ідентична — пропуск")
            continue
        ch = 0
        for ref in d.get("m_FallbackFontAssetTable") or []:
            if isinstance(ref, dict) and ref.get("m_PathID") == SLOT_FIXEL:
                ref["m_PathID"] = SLOT_KYIV
                ch += 1
        if ch != 1:
            print(f"  — {nm}: посилань на {SLOT_FIXEL} = {ch}, пропуск")
            continue
        w2 = EndianBinaryWriter(endian=o.reader.endian)
        TypeTreeHelper.write_typetree(d, node, w2, o.assets_file)
        nb = w2.bytes
        diff = [i for i in range(len(raw)) if raw[i] != nb[i]]
        if len(nb) != len(raw) or len(diff) > 8 or diff[-1] - diff[0] != len(diff) - 1:
            print(f"  🔴 {nm}: небезпечна різниця {len(diff)} Б — пропуск")
            continue
        patches_res.append((base + o.byte_start + diff[0], nb[diff[0]:diff[-1] + 1]))
        print(f"  KYIV  {nm}  ({len(diff)} Б @ {base + o.byte_start + diff[0]})")

    # ─── 3. «старі» шрифти: сира підміна 12-байтового PPtr 3334 -> слот
    print("\n" + "=" * 70)
    print("ПЕРЕЦІЛЮВАННЯ «СТАРИХ» ШРИФТІВ (сира підміна PPtr)")
    old_pat = struct.pack("<iq", 0, OLD_CYR)
    for pid, nm in sorted(fonts_old.items(), key=lambda kv: kv[1]):
        o = objs[pid]
        raw = o.get_raw_data()
        cnt = raw.count(old_pat)
        if cnt == 0:
            continue
        if cnt != 1:
            print(f"  🔴 {nm}: PPtr на {OLD_CYR} трапляється {cnt} разів — пропуск")
            continue
        tgt = SLOT_KYIV if any(m in (nm or "").lower() for m in KYIV_MARKS) else SLOT_FIXEL
        i = raw.find(old_pat)
        patches_res.append((base + o.byte_start + i + 4, struct.pack("<q", tgt)))
        print(f"  {'KYIV ' if tgt==SLOT_KYIV else 'FIXEL'} {nm}  (8 Б @ "
              f"{base + o.byte_start + i + 4})")

    print("\n" + "=" * 70)
    print(f"resources.assets: {len(patches_res)} правок, "
          f"{sum(len(b) for _, b in patches_res)/1e6:.2f} МБ")
    print(f"resources.assets.resS: {len(patches_ress)} правок, "
          f"{sum(len(b) for _, b in patches_ress)/1e6:.2f} МБ")
    if mode != "apply":
        print("(режим plan — нічого не записано)")
        return

    os.makedirs(BACKUP, exist_ok=True)
    for path, patches, tag in ((RES, patches_res, "resources"), (RESS, patches_ress, "resourcesS")):
        if not patches:
            continue
        fsize = os.path.getsize(path)
        for off, blob in patches:
            if off < 0 or off + len(blob) > fsize:
                raise SystemExit(f"ЗАПИС ЗА МЕЖУ {os.path.basename(path)}: "
                                 f"{off}+{len(blob)} > {fsize} — скасовано")
        meta = []
        with open(path, "rb") as f:
            for off, blob in patches:
                f.seek(off)
                old = f.read(len(blob))
                bn = f"{tag}_{off}.bin"
                open(os.path.join(BACKUP, bn), "wb").write(old)
                meta.append(dict(file=path, offset=off, size=len(blob), backup=bn))
        json.dump(meta, open(os.path.join(BACKUP, f"{tag}.json"), "w"), indent=1)
        with open(path, "r+b") as f:
            for off, blob in patches:
                f.seek(off)
                f.write(blob)
        print(f"записано {len(patches)} правок у {os.path.basename(path)}")


if __name__ == "__main__":
    main()
