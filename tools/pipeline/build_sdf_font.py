"""
Генератор SDF-атласу у форматі TextMeshPro (SDFAA, Alpha8).

Кодування поля відстаней звірене з атласом, який лежить у грі (кореляція 0.99):
    v = 0.5 + signed_distance_px / (2 * gradientScale)

Домовленості формату зчитані з рідного асета гри (NotoSerifCyrillic-Regular SDF)
і дотримані точно — інакше TextMeshPro падає з NullReferenceException
у InitializeGlyphLookupDictionary, а виняток валить перебудову всього канваса:

  * m_Index гліфа — СПРАВЖНІЙ ідентифікатор гліфа у шрифті, ніколи не 0
    (0 — це .notdef, «немає гліфа»)
  * m_GlyphTable відсортована за m_Index, індекси унікальні
  * m_CharacterTable відсортована за m_Unicode
  * гліфів із нульовим прямокутником не буває — символи без чорнила
    (пробіл тощо) у таблицю не потрапляють узагалі
  * m_UsedGlyphRects містить рівно по одному прямокутнику на гліф
  * набір символів — лише кирилиця; латиниця, цифри й розділові знаки
    беруться з основного шрифту гри, а не з запасного
"""
import numpy as np
from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageFont
from scipy.ndimage import distance_transform_edt

PAD = 10
GRAD = 11.0
SS = 4                # суперсемплінг растру
ATLAS = 2048

# блоки кирилиці — рівно ті, що тримає рідний асет гри
CYRILLIC_RANGES = [(0x0400, 0x052F), (0x1C80, 0x1C88), (0x2DE0, 0x2DFF), (0xA640, 0xA69F)]


def cyrillic_charset():
    return {chr(u) for a, b in CYRILLIC_RANGES for u in range(a, b + 1)}


def face_metrics(path, point_size):
    """Метрики гарнітури в пікселях при заданому кеглі (як їх тримає TMP)."""
    f = TTFont(path, fontNumber=0)
    upm = f["head"].unitsPerEm
    k = point_size / upm
    os2, hhea = f["OS/2"], f["hhea"]
    asc = getattr(os2, "sTypoAscender", 0) or hhea.ascent
    desc = getattr(os2, "sTypoDescender", 0) or hhea.descent
    gap = getattr(os2, "sTypoLineGap", 0) or 0
    cap = getattr(os2, "sCapHeight", 0) or int(0.7 * upm)
    mean = getattr(os2, "sxHeight", 0) or int(0.5 * upm)
    post = f["post"]
    return {
        "m_FaceIndex": 0,
        "m_FamilyName": str(f["name"].getDebugName(1) or "UA"),
        "m_StyleName": str(f["name"].getDebugName(2) or "Regular"),
        "m_PointSize": float(point_size),
        "m_Scale": 1.0,
        "m_UnitsPerEM": int(upm),
        "m_LineHeight": float((asc - desc + gap) * k),
        "m_AscentLine": float(asc * k),
        "m_CapLine": float(cap * k),
        "m_MeanLine": float(mean * k),
        "m_Baseline": 0.0,
        "m_DescentLine": float(desc * k),
        "m_SuperscriptOffset": float(asc * k),
        "m_SuperscriptSize": 0.5,
        "m_SubscriptOffset": float(desc * k),
        "m_SubscriptSize": 0.5,
        "m_UnderlineOffset": float(getattr(post, "underlinePosition", -100) * k),
        "m_UnderlineThickness": float(getattr(post, "underlineThickness", 50) * k),
        "m_StrikethroughOffset": float(mean * k / 2),
        "m_StrikethroughThickness": float(getattr(post, "underlineThickness", 50) * k),
        "m_TabWidth": float(point_size * 0.26),
    }


def glyph_sdf(pil_font, ch, pad, grad, ss=SS):
    """SDF гліфа, обрізаний по щільній межі чорнила."""
    mask = pil_font.getmask(ch, mode="L")
    w, h = mask.size
    if w == 0 or h == 0:
        return None
    hi = np.frombuffer(bytes(mask), dtype=np.uint8).reshape(h, w) > 127
    if not hi.any():
        return None
    ys, xs = np.where(hi)
    tight = hi[ys.min():ys.max() + 1, xs.min():xs.max() + 1]

    pad_hi = pad * ss
    big = np.zeros((tight.shape[0] + 2 * pad_hi, tight.shape[1] + 2 * pad_hi), dtype=bool)
    big[pad_hi:pad_hi + tight.shape[0], pad_hi:pad_hi + tight.shape[1]] = tight
    signed_hi = (distance_transform_edt(big) - distance_transform_edt(~big)) / ss

    th, tw = signed_hi.shape[0] // ss, signed_hi.shape[1] // ss
    signed = signed_hi[:th * ss, :tw * ss].reshape(th, ss, tw, ss).mean(axis=(1, 3))
    v = np.clip(0.5 + signed / (2.0 * grad), 0.0, 1.0)
    return (v * 255.0).round().astype(np.uint8)


def _collect(font_path, unicodes, point_size, pad, grad, gid_offset=0):
    """Гліфи одного шрифту для заданих символів. -> {unicode: дані}"""
    ttf = TTFont(font_path, fontNumber=0)
    cmap = ttf.getBestCmap()
    hmtx = ttf["hmtx"]
    gs = ttf.getGlyphSet()
    k = point_size / ttf["head"].unitsPerEm
    pil = ImageFont.truetype(font_path, int(round(point_size * SS)))
    out = {}
    for u in sorted(unicodes):
        gname = cmap.get(u)
        if gname is None:
            continue
        bp = BoundsPen(gs)
        gs[gname].draw(bp)
        if bp.bounds is None:              # без чорнила — у таблицю не кладемо
            continue
        img = glyph_sdf(pil, chr(u), pad, grad)
        if img is None:
            continue
        gid = ttf.getGlyphID(gname)
        if gid == 0:                       # .notdef
            continue
        out[u] = dict(img=img, bx=bp.bounds[0] * k, by=bp.bounds[3] * k,
                      adv=hmtx[gname][0] * k, gid=gid + gid_offset)
    return out


def build(font_path, charset, point_size, atlas=ATLAS, pad=PAD, grad=None, filler=None,
          extra=None):
    """-> dict(atlas, face, glyphs, chars, used_rects, free_rects, overflow, peak)

    extra — [(шлях_до_шрифта, набір_символів)]: ці символи беруться саме звідти,
    а не з основного. Використовується для цифр: текст ставимо Light, а цифри —
    на крок товщіші (Regular), щоб числа не тонули поруч із літерами.

    filler — шрифт, з якого добираються символи, відсутні в основному.
    Потрібен, щоб набір символів асета не звузився: якщо TextMeshPro не знайде
    символ тут, він піде далі по ланцюгу запасних шрифтів у порожні CJK-асети,
    які ніколи не ініціалізувалися, і впаде там із NullReferenceException.
    """
    if grad is None:
        grad = pad + 1

    want = {ord(c) for c in charset}
    got = {}
    for i, (xpath, xchars) in enumerate(extra or []):
        xw = {ord(c) for c in xchars} & want
        got.update(_collect(xpath, xw, point_size, pad, grad,
                            gid_offset=2_000_000 + i * 1_000_000))
    got.update(_collect(font_path, want - set(got), point_size, pad, grad))
    filled = 0
    if filler:
        rest = want - set(got)
        extra = _collect(filler, rest, point_size, pad, grad, gid_offset=1_000_000)
        got.update(extra)
        filled = len(extra)

    # групуємо за ідентифікатором гліфа
    items = {}
    for u, g in got.items():
        it = items.setdefault(g["gid"], {"img": g["img"], "bx": g["bx"], "by": g["by"],
                                         "adv": g["adv"], "chars": []})
        it["chars"].append(u)

    # упаковка полицями: спершу високі
    order = sorted(items.items(), key=lambda kv: -kv[1]["img"].shape[0])
    sheet = np.zeros((atlas, atlas), dtype=np.uint8)
    x = y = shelf = 0
    overflow, shelves = [], []
    for gid, it in order:
        h, w = it["img"].shape
        if x + w > atlas:
            shelves.append((y, shelf, x))
            x, y, shelf = 0, y + shelf, 0
        if y + h > atlas:
            overflow.append(gid)
            continue
        sheet[y:y + h, x:x + w] = it["img"]
        it["pos"] = (x, y, w, h)
        x += w
        shelf = max(shelf, h)
    shelves.append((y, shelf, x))

    glyphs, used_rects = [], []
    for gid in sorted(g for g, it in items.items() if "pos" in it):
        it = items[gid]
        px, py, w, h = it["pos"]
        bw, bh = w - 2 * pad, h - 2 * pad
        rect = dict(m_X=int(px + pad), m_Y=int(atlas - (py + h) + pad),
                    m_Width=int(bw), m_Height=int(bh))
        glyphs.append(dict(
            m_Index=int(gid),
            m_Metrics=dict(m_Width=float(bw), m_Height=float(bh),
                           m_HorizontalBearingX=float(it["bx"]),
                           m_HorizontalBearingY=float(it["by"]),
                           m_HorizontalAdvance=float(it["adv"])),
            m_GlyphRect=rect, m_Scale=1.0, m_AtlasIndex=0, m_ClassDefinitionType=0))
        used_rects.append(dict(rect))

    chars = []
    for gid, it in items.items():
        if "pos" not in it:
            continue
        for u in it["chars"]:
            chars.append(dict(m_ElementType=1, m_Unicode=int(u),
                              m_GlyphIndex=int(gid), m_Scale=1.0))
    chars.sort(key=lambda c: c["m_Unicode"])

    # вільні прямокутники: залишок кожної полиці плюс місце під останньою
    free_rects = []
    for top, height, used_w in shelves:
        if height and used_w < atlas:
            free_rects.append(dict(m_X=int(used_w), m_Y=int(atlas - (top + height)),
                                   m_Width=int(atlas - used_w), m_Height=int(height)))
    bottom = shelves[-1][0] + shelves[-1][1]
    if bottom < atlas:
        free_rects.append(dict(m_X=0, m_Y=0, m_Width=int(atlas), m_Height=int(atlas - bottom)))

    return dict(atlas=Image.fromarray(sheet, mode="L"),
                face=face_metrics(font_path, point_size),
                glyphs=glyphs, chars=chars, used_rects=used_rects,
                free_rects=free_rects, overflow=overflow, peak=int(sheet.max()),
                filled=filled)
