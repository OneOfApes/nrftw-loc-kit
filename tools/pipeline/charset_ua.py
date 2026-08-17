"""
Набір символів для кириличного асета — РІВНО 441 запис, як у рідному.

Чому саме 441: розмір асета фіксується кількістями записів, а побайтовий
запис на місце можливий лише коли розмір не змінюється. Тому пунктуацію
не «додаємо», а ВМІЩУЄМО, витісняючи найрідкіснішу церковнослов'янську
кирилицю з хвоста діапазону U+A640..A69F, якої в українському тексті немає.

Гарантії, потрібні формату:
  * кожен символ має ЧОРНИЛО (порожні гліфи в таблицю не потрапляють);
  * один символ = один унікальний гліф (інакше гліфів стане менше за символи
    і розмір асета зміниться).
"""

from __future__ import annotations

from fontTools.pens.boundsPen import BoundsPen
from fontTools.ttLib import TTFont
from PIL import ImageFont

SS = 4          # той самий суперсемплінг, що в build_sdf_font
TOTAL = 441

# Пунктуація й символи, які в українському тексті мусять виглядати як частина
# гарнітури, а не як чужа латинська вставка. Порядок = приоритет.
PUNCT = [
    ".", ",", "!", "?", ":", ";", "-", "—", "–",        # — –
    "…", "«", "»", "(", ")", "’", "‘",   # … « » ’ ‘
    "“", "”", "„", "'", '"', "№", "·",   # “ ” „ № ·
    "•", "/", "*", "%", "°", "−", "+",             # • ° −
    " ", "‐", "­",                                  # nbsp, ‑, soft hyphen
]

DIGITS = list("0123456789")


# Кирилиця за приоритетом: спершу все, що реально трапляється,
# далі — розширення, і найрідкісніше в кінці (його й витісняємо).
def cyr_priority():
    out = []
    out += [chr(u) for u in range(0x0410, 0x0450)]       # А-я — основа
    out += [chr(u) for u in range(0x0400, 0x0410)]       # Ѐ-Џ (Є, І, Ї, Ґ поруч)
    out += [chr(u) for u in range(0x0450, 0x0460)]       # ѐ-џ
    out += [chr(u) for u in range(0x0460, 0x0530)]       # розширена кирилиця
    out += [chr(u) for u in range(0x1C80, 0x1C89)]
    out += [chr(u) for u in range(0x2DE0, 0x2E00)]
    out += [chr(u) for u in range(0xA640, 0xA6A0)]       # найрідкісніше — в хвіст
    return out


class Probe:
    """Чи є в шрифті гліф із чорнилом для символу, і який у нього індекс."""

    def __init__(self, path, point_size, gid_offset=0):
        self.ttf = TTFont(path, fontNumber=0)
        self.cmap = self.ttf.getBestCmap()
        self.gs = self.ttf.getGlyphSet()
        self.pil = ImageFont.truetype(path, int(round(point_size * SS)))
        self.gid_offset = gid_offset

    def gid(self, ch):
        gname = self.cmap.get(ord(ch))
        if gname is None:
            return None
        bp = BoundsPen(self.gs)
        self.gs[gname].draw(bp)
        if bp.bounds is None:                       # без чорнила
            return None
        g = self.ttf.getGlyphID(gname)
        if g == 0:                                  # .notdef
            return None
        mask = self.pil.getmask(ch, mode="L")       # так само перевіряє build_sdf_font
        if mask.size[0] == 0 or mask.size[1] == 0:
            return None
        if max(bytes(mask) or b"\0") <= 127:
            return None
        return g + self.gid_offset


def make_charset(main_font, filler_font, point_size, total=TOTAL, verbose=True,
                 digit_font=None):
    """-> (set символів рівно `total`, статистика)

    digit_font — файл, з якого братимуться цифри (окреме, товщіше накреслення).
    """
    pm = Probe(main_font, point_size)
    pf = Probe(filler_font, point_size, gid_offset=1_000_000)
    pd = Probe(digit_font, point_size, gid_offset=2_000_000) if digit_font else None

    chosen, used_gids = [], set()
    from_main = from_filler = 0
    skipped = []

    def take(ch):
        nonlocal from_main, from_filler
        g = pm.gid(ch)
        src = "main"
        if g is None:
            g = pf.gid(ch)
            src = "filler"
        if g is None or g in used_gids:
            skipped.append(ch)
            return False
        used_gids.add(g)
        chosen.append(ch)
        if src == "main":
            from_main += 1
        else:
            from_filler += 1
        return True

    digits_ok = []
    if pd is not None:
        # цифри з окремого (товщішого) накреслення
        for ch in DIGITS:
            g = pd.gid(ch)
            if g is not None and g not in used_gids:
                used_gids.add(g)
                chosen.append(ch)
                digits_ok.append(ch)
    else:
        # цифри з основної гарнітури — щоб число в реченні було тією ж гарнітурою
        for ch in DIGITS:
            if take(ch):
                digits_ok.append(ch)

    punct_ok = []
    for ch in PUNCT:
        if len(chosen) >= total:
            break
        if take(ch):
            punct_ok.append(ch)
    for ch in cyr_priority():
        if len(chosen) >= total:
            break
        take(ch)

    if verbose:
        print(f"    набір: {len(chosen)} символів "
              f"(з гарнітури {from_main}, добрано {from_filler}); "
              f"пунктуації {len(punct_ok)}/{len(PUNCT)}, цифр {len(digits_ok)}/10")
        miss = [c for c in PUNCT if c not in punct_ok]
        if miss:
            print(f"    пунктуація не вмістилась/відсутня: {' '.join(repr(c) for c in miss)}")
        cyr = [c for c in chosen if ord(c) >= 0x0400]
        print(f"    кирилиці {len(cyr)}, найвищий кодпоінт U+{max(ord(c) for c in cyr):04X}")
    if len(chosen) != total:
        raise SystemExit(f"набралось {len(chosen)} замість {total}")
    return set(chosen), dict(punct=punct_ok, digits=digits_ok, from_filler=from_filler)


if __name__ == "__main__":
    import os
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from inplace_font import FIXEL, KYIV, NOTO

    for f, pt in ((FIXEL, 112), (KYIV, 106)):
        print(f"\n{os.path.basename(f)} @ {pt}:")
        make_charset(f, NOTO, pt)
