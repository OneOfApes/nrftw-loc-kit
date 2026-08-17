"""
Перевірка вшитого — читає ФАЙЛИ ГРИ і доводить, що там лежить те, що треба.
Гру не запускає.

  1) формат кожного кириличного асета проти домовленостей рідного;
  2) малює рядки українською з АТЛАСУ, ВЗЯТОГО З ФАЙЛУ ГРИ;
  3) показує, який базовий шрифт куди тепер веде.

  python verify_inplace.py
"""

from __future__ import annotations

import io
import os
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import kitconfig  # noqa: E402
from scan_all_fonts import Window, bundle_nodes  # noqa: E402
from inplace_font import AA, BUNDLE, PAD, ATLAS  # noqa: E402
from inplace_resources import RES, RESS, borrow_node  # noqa: E402

OUT = os.path.join(kitconfig.PREVIEW, "from_game.png")
LINES = ["Витрату витривалості на атаки зменшено на 7%",
         "Вартість 14 · Отримати 10 · Рівень 9 · 123/123",
         "«Мрок поглинув Серім», — мовила Віщунка… 150% шкоди!"]
CYR = {
    -2444889057261992194: "Regular TMP -> FIXEL (сюди ведуть усі Arcon/Liberation)",
    -5959213582716284887: "Bold TMP -> KYIV (сюди ведуть friz-quadrata/Marcellus)",
    775181479505102588: "Regular SDF — ЧУЖИЙ КЛАС, лишається Noto, посилань нема",
    -5519819465463294359: "Bold SDF — ЧУЖИЙ КЛАС, лишається Noto, посилань нема",
}


def check_format(d, label):
    g, c, u = d["m_GlyphTable"], d["m_CharacterTable"], d["m_UsedGlyphRects"]
    p = []
    idx = [x["m_Index"] for x in g]
    if 0 in idx:
        p.append("є гліф з індексом 0")
    if len(set(idx)) != len(idx):
        p.append("індекси не унікальні")
    if idx != sorted(idx):
        p.append("таблиця гліфів не відсортована")
    cu = [x["m_Unicode"] for x in c]
    if cu != sorted(cu):
        p.append("символи не відсортовані")
    if len(set(cu)) != len(cu):
        p.append("unicode повторюються")
    if not set(x["m_GlyphIndex"] for x in c) <= set(idx):
        p.append("символ без гліфа")
    if any(x["m_GlyphRect"]["m_Width"] == 0 or x["m_GlyphRect"]["m_Height"] == 0 for x in g):
        p.append("нульовий прямокутник")
    if len(u) != len(g):
        p.append("used_rects != гліфів")
    for x in g:
        r = x["m_GlyphRect"]
        if r["m_X"] < 0 or r["m_Y"] < 0 or r["m_X"] + r["m_Width"] > ATLAS \
                or r["m_Y"] + r["m_Height"] > ATLAS:
            p.append("прямокутник за межами атласу")
            break
    fi = d["m_FaceInfo"]
    print(f"    гліфів {len(g)}, символів {len(c)}, кегль {fi['m_PointSize']}, "
          f"scale {fi['m_Scale']}, capLine {fi['m_CapLine']:.1f}, "
          f"pad {d['m_AtlasPadding']}, атлас {d['m_AtlasWidth']}x{d['m_AtlasHeight']}")
    print(f"    формат: {'✅ усе за домовленостями' if not p else '🔴 ' + '; '.join(p)}")
    return not p


def render(d, sheet, text, px=34, thresh=0.5):
    gl = {g["m_Index"]: g for g in d["m_GlyphTable"]}
    ch = {c["m_Unicode"]: c["m_GlyphIndex"] for c in d["m_CharacterTable"]}
    fi = d["m_FaceInfo"]
    pt = fi["m_PointSize"]
    k = px / pt
    asc = fi["m_AscentLine"] * k
    W = int(sum((gl[ch[ord(c)]]["m_Metrics"]["m_HorizontalAdvance"] if ord(c) in ch else pt * .3)
                * k for c in text) + 20)
    H = int(fi["m_LineHeight"] * k + 12)
    canvas = np.zeros((H, W), dtype=np.float32)
    x = 6.0
    for c in text:
        u = ord(c)
        if u not in ch:
            x += pt * .3 * k
            continue
        g = gl[ch[u]]
        m, r = g["m_Metrics"], g["m_GlyphRect"]
        y0 = ATLAS - (r["m_Y"] + r["m_Height"])
        patch = sheet[y0 - PAD:y0 + r["m_Height"] + PAD, r["m_X"] - PAD:r["m_X"] + r["m_Width"] + PAD]
        if patch.size == 0:
            x += m["m_HorizontalAdvance"] * k
            continue
        ph, pw = patch.shape
        nw, nh = max(1, int(round(pw * k))), max(1, int(round(ph * k)))
        img = np.array(Image.fromarray(patch).resize((nw, nh), Image.BILINEAR),
                       dtype=np.float32) / 255.0
        alpha = np.clip((img - thresh) * 12.0 + .5, 0, 1)
        px0 = int(round(x + (m["m_HorizontalBearingX"] - PAD) * k))
        py0 = int(round(6 + asc - (m["m_HorizontalBearingY"] + PAD) * k))
        xs, ys, xe, ye = max(0, px0), max(0, py0), min(W, px0 + nw), min(H, py0 + nh)
        if xe > xs and ye > ys:
            canvas[ys:ye, xs:xe] = np.maximum(canvas[ys:ye, xs:xe],
                                              alpha[ys - py0:ye - py0, xs - px0:xe - px0])
        x += m["m_HorizontalAdvance"] * k
    return canvas


def main():
    import UnityPy

    blocks = []
    ok_all = True

    # ─── бандл
    path = os.path.join(AA, BUNDLE)
    ds, nodes = bundle_nodes(path)
    off, size, fl, name = [n for n in nodes if not n[3].endswith(".resS")][0]
    res_node = [n for n in nodes if n[3].endswith(".resS")][0]
    fh = open(path, "rb")
    sf = UnityPy.Environment().load_file(
        io.BufferedReader(Window(fh, ds + off, size), buffer_size=1 << 20), name=name)
    print("=" * 74)
    print("БАНДЛ duplicateassetisolation — читаю з ФАЙЛУ ГРИ")
    print("=" * 74)
    for pid, label in CYR.items():
        d = sf.objects[pid].read_typetree()
        print(f"\n  {label}")
        ok_all &= check_format(d, label)
        td = sf.objects[d["m_AtlasTextures"][0]["m_PathID"]].read_typetree()
        sd = td["m_StreamData"]
        with open(path, "rb") as f:
            f.seek(ds + res_node[0] + sd["offset"])
            raw = f.read(sd["size"])
        sheet = np.flipud(np.frombuffer(raw, dtype=np.uint8).reshape(td["m_Height"],
                                                                    td["m_Width"])).copy()
        print(f"    атлас із .resS: непорожніх пікселів "
              f"{(sheet > 130).mean()*100:.1f}%, пік {sheet.max()}")
        blocks.append((f"БАНДЛ · {label}", [render(d, sheet, ln) for ln in LINES]))
    fh.close()

    # ─── resources.assets
    print("\n" + "=" * 74)
    print("resources.assets — читаю з ФАЙЛУ ГРИ")
    print("=" * 74)
    fnode, tnode = borrow_node()
    sfr = UnityPy.Environment().load_file(open(RES, "rb"), name="resources.assets")
    for pid, label in ((3335, "3335 Regular TMP -> FIXEL"), (3333, "3333 Bold TMP -> KYIV")):
        d = sfr.objects[pid].read_typetree(fnode)
        print(f"\n  {label}  («{d['m_Name']}»)")
        ok_all &= check_format(d, label)
        td = sfr.objects[d["m_AtlasTextures"][0]["m_PathID"]].read_typetree(tnode)
        sd = td["m_StreamData"]
        with open(RESS, "rb") as f:
            f.seek(sd["offset"])
            raw = f.read(sd["size"])
        sheet = np.flipud(np.frombuffer(raw, dtype=np.uint8).reshape(td["m_Height"],
                                                                    td["m_Width"])).copy()
        print(f"    атлас із resources.assets.resS: непорожніх "
              f"{(sheet > 130).mean()*100:.1f}%, пік {sheet.max()}")
        blocks.append((f"resources.assets · {label}", [render(d, sheet, ln) for ln in LINES]))

    # ─── картинка
    W = max(r.shape[1] for _, rows in blocks for r in rows) + 24
    H = sum(28 + sum(r.shape[0] + 5 for r in rows) + 14 for _, rows in blocks) + 20
    out = Image.new("RGB", (W, H), (24, 22, 20))
    d0 = ImageDraw.Draw(out)
    y = 10
    for title, rows in blocks:
        d0.text((12, y), title, fill=(180, 150, 90))
        y += 24
        for r in rows:
            a = (r * 255).astype(np.uint8)
            rgb = np.dstack([(a.astype(np.float32) * c / 255).astype(np.uint8)
                             for c in (242, 230, 189)])
            out.paste(Image.fromarray(rgb, "RGB"), (12, y), Image.fromarray(a, "L"))
            y += r.shape[0] + 5
        y += 14
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out.save(OUT)
    print("\n" + ("✅ ФОРМАТ УСІХ АСЕТІВ ЧИСТИЙ" if ok_all else "🔴 Є ПРОБЛЕМИ ФОРМАТУ"))
    print("→", OUT)


if __name__ == "__main__":
    main()
