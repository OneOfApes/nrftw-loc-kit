"""
Побайтова заміна кириличних шрифтів БЕЗ перезапису бандла.

Чому так можна (перевірено на файлах гри):
  * блоки даних у бандлах НЕ стиснені (comp_type=0);
  * 16-байтовий хеш у blockinfo — нулі, контрольної суми немає;
  * перезбірка асета з typetree дає БАЙТ-У-БАЙТ ті самі байти;
  * розмір асета не змінюється, якщо тримати ті самі кількості записів
    (441 гліф / 441 символ / 441 used_rect) і не чіпати free_rects
    та m_FontFeatureTable;
  * атлас — 2048×2048 Alpha8 = рівно 4 МБ у .resS за фіксованим зсувом.

Тому один тест = запис ~4,2 МБ на місце замість 7 ГБ у памʼять і назад.

Команди:
  python inplace_font.py plan                 # згенерувати, перевірити розміри, НІЧОГО не писати
  python inplace_font.py verify-atlas         # звірити конвенцію перевороту атласу з рідним
  python inplace_font.py apply                # вшити гарнітури на місце (з бекапом)
  python inplace_font.py repoint              # перецілити базові шрифти й написи
  python inplace_font.py restore              # відкат із бекапу
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
ROOT = kitconfig.WORK
BACKUP = kitconfig.BACKUP
SCAN = kitconfig.SCAN

# FIXEL/KYIV — історичні імена слотів: основний текстовий і акцентний шрифт.
# Конкретні гарнітури приносить користувач через config.local.json.
FIXEL = kitconfig.FONT_BODY
KYIV = kitconfig.FONT_ACCENT
NOTO = kitconfig.FONT_NOTO

BUNDLE = kitconfig.BUNDLE

# ─── слоти. 🔴 ТІЛЬКИ TMP-варіанти!
#     SDF-варіанти (Regular SDF / Bold SDF) — це асети ІНШОГО класу: їхній
#     m_Script веде у «Library/unity default resources» pathID 19001, у них
#     38 полів замість 42 (нема m_fontInfo, m_glyphInfoList, m_KerningTable,
#     fontWeights, atlas…). Це залишки старої версії TextMeshPro, які гра
#     ніколи не вантажила — тому на них і не було посилань. Щойно на такий асет
#     веде живий шрифт, TMP_FontAsset.ReadFontAssetDefinition падає з
#     NullReferenceException і гра гине ще до головного меню (перевірено 2026-07-27).
#     Обидва TMP-варіанти мають той самий m_Script, що й усі базові шрифти.
SLOTS = {
    # digit_font=None означає «цифри з основної гарнітури слота» — так число
    # всередині речення завжди тієї ж гарнітури, що й літери навколо.
    "fixel": dict(path_id=-2444889057261992194, name="NotoSerifCyrillic-Regular TMP",
                  font=FIXEL, pt=112, base_point=159.0, base_cap=114.0,
                  digits="regular"),                                       # база: Arcon
    "kyiv": dict(path_id=-5959213582716284887, name="NotoSerifCyrillic-Bold TMP",
                 font=KYIV, pt=106, base_point=145.0, base_cap=102.0,
                 digits=None),                                            # база: friz-quadrata
}
REL = 0.7616   # висота великих літер кирилиці відносно латиниці гри — вибір
               # користувача. Шрифт НЕ збільшувати: цифри зрівняні з текстом
               # не масштабом, а тим, що тепер теж беруться з нашої гарнітури.
# Цифри — на крок товщіше за текст (Light -> Regular), щоб числа не тонули.
DIGIT_FONT = kitconfig.FONT_DIGITS
PAD, GRAD, ATLAS = 10, 11.0, 2048


# ────────────────────────────── доступ до бандла ──────────────────────────────

class BundleView:
    """Читання SerializedFile бандла + абсолютні зсуви для запису на місце."""

    def __init__(self, path):
        import UnityPy

        self.path = path
        self.data_start, self.nodes = bundle_nodes(path)
        self.sf_nodes = {n[3]: n for n in self.nodes if not n[3].endswith(".resS")}
        self.res_nodes = {n[3]: n for n in self.nodes if n[3].endswith(".resS")}
        self.name, node = next(iter(self.sf_nodes.items())), None
        self.node = list(self.sf_nodes.values())[0]
        self._fh = open(path, "rb")
        buf = io.BufferedReader(Window(self._fh, self.data_start + self.node[0], self.node[1]),
                               buffer_size=1 << 20)
        self.sf = UnityPy.Environment().load_file(buf, name=self.node[3])
        # ObjectReader.byte_start УЖЕ містить header.data_offset (див. ObjectReader.py:86),
        # тому додавати його вдруге НЕ можна
        self.base = self.data_start + self.node[0]

    def abs_obj(self, path_id):
        o = self.sf.objects[path_id]
        return self.base + o.byte_start, o.byte_size

    def abs_stream(self, stream_path, offset):
        cab = stream_path.rsplit("/", 1)[-1]
        n = self.res_nodes.get(cab)
        if n is None:
            raise KeyError(f"нема .resS ноди {cab}")
        return self.data_start + n[0] + offset

    def close(self):
        self._fh.close()


class PlainView:
    """Те саме для звичайного SerializedFile (resources.assets)."""

    def __init__(self, path):
        import UnityPy

        self.path = path
        self._fh = open(path, "rb")
        self.sf = UnityPy.Environment().load_file(self._fh, name=os.path.basename(path))
        self.base = 0          # byte_start уже абсолютний для звичайного файлу

    def abs_obj(self, path_id):
        o = self.sf.objects[path_id]
        return self.base + o.byte_start, o.byte_size

    def abs_stream(self, stream_path, offset):
        return offset      # окремий файл .resS

    def close(self):
        self._fh.close()


# ────────────────────────────── збірка гарнітури ──────────────────────────────

def build_slot(view, slot, verbose=True):
    """Готує НОВІ байти асета й атласу, не змінюючи розміру. -> dict"""
    from build_sdf_font import build
    from charset_ua import make_charset
    from UnityPy.helpers import TypeTreeHelper
    from UnityPy.streams import EndianBinaryWriter

    o = view.sf.objects[slot["path_id"]]
    orig_raw = o.get_raw_data()
    d = o.read_typetree()
    node = o.serialized_type.node

    # контроль: перезбірка без змін мусить бути ідентичною
    w = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(d, node, w, o.assets_file)
    if w.bytes != orig_raw:
        raise SystemExit(f"{slot['name']}: перезбірка НЕ ідентична — далі не йдемо")

    dfont = DIGIT_FONT if slot.get("digits") == "regular" else None
    charset, _ = make_charset(slot["font"], NOTO, slot["pt"], verbose=verbose,
                              digit_font=dfont)
    res = build(slot["font"], charset, slot["pt"], atlas=ATLAS,
                pad=PAD, grad=GRAD, filler=NOTO,
                extra=[(dfont, set("0123456789"))] if dfont else None)
    if res["overflow"]:
        raise SystemExit(f"{slot['name']}: атлас переповнено на {len(res['overflow'])} гліфів")

    ng, nc, nu = len(res["glyphs"]), len(res["chars"]), len(res["used_rects"])
    og, oc, ou = len(d["m_GlyphTable"]), len(d["m_CharacterTable"]), len(d["m_UsedGlyphRects"])
    if verbose:
        print(f"  згенеровано: гліфів {ng} (рідних {og}), символів {nc} ({oc}), "
              f"used_rects {nu} ({ou}), добрано з Noto {res['filled']}, пік SDF {res['peak']}")
    if (ng, nc, nu) != (og, oc, ou):
        raise SystemExit(f"{slot['name']}: кількості не збігаються — розмір асета зміниться")

    # масштаб: висота великих літер = REL від латиниці гри
    own = res["face"]["m_CapLine"] / res["face"]["m_PointSize"]
    scale = round(REL * (slot["base_cap"] / slot["base_point"]) / own, 4)

    face = dict(d["m_FaceInfo"])                       # зберігаємо РІДНІ рядки
    for k, v in res["face"].items():
        if k in ("m_FamilyName", "m_StyleName"):       # не чіпати — довжина рядка фіксує розмір
            continue
        if k in face:
            face[k] = v
    face["m_Scale"] = scale

    new = dict(d)
    new["m_FaceInfo"] = face
    new["m_GlyphTable"] = res["glyphs"]
    new["m_CharacterTable"] = res["chars"]
    new["m_UsedGlyphRects"] = res["used_rects"]
    # m_FreeGlyphRects і m_FontFeatureTable лишаємо РІДНІ — вони фіксують розмір

    w2 = EndianBinaryWriter(endian=o.reader.endian)
    TypeTreeHelper.write_typetree(new, node, w2, o.assets_file)
    blob = w2.bytes
    off, size = view.abs_obj(slot["path_id"])
    if verbose:
        print(f"  асет: рідний {size} Б, новий {len(blob)} Б, "
              f"різниця {len(blob)-size:+d} | зсув {off}")
    if len(blob) != size:
        raise SystemExit(f"{slot['name']}: РОЗМІР ЗМІНИВСЯ на {len(blob)-size:+d} — "
                         f"на місці писати не можна")

    # атлас
    tex_pid = d["m_AtlasTextures"][0]["m_PathID"]
    tex = view.sf.objects[tex_pid]
    td = tex.read_typetree()
    sd = td.get("m_StreamData") or {}
    import numpy as np

    sheet = np.array(res["atlas"], dtype=np.uint8)
    raw_atlas = np.flipud(sheet).tobytes()             # Unity тримає текстури знизу вгору
    a_off = view.abs_stream(sd["path"], sd["offset"])
    if verbose:
        print(f"  атлас: {td['m_Width']}x{td['m_Height']} format={td['m_TextureFormat']}, "
              f"{sd['size']} Б у .resS на зсуві {a_off}, нових байтів {len(raw_atlas)}")
    if len(raw_atlas) != sd["size"]:
        raise SystemExit("розмір атласу не збігається")

    return dict(asset_off=off, asset_bytes=blob, atlas_off=a_off, atlas_bytes=raw_atlas,
                scale=scale, face=face, name=slot["name"], tex_name=td.get("m_Name"))


# ────────────────────────────── команди ──────────────────────────────

def cmd_plan():
    print("=" * 74)
    print("ПЛАН ЗАМІНИ — генерація й перевірка розмірів, БЕЗ ЗАПИСУ")
    print("=" * 74)
    v = BundleView(os.path.join(AA, BUNDLE))
    out = {}
    for key, slot in SLOTS.items():
        print(f"\n### {key.upper()} -> {slot['name']}  ({os.path.basename(slot['font'])}, "
              f"кегль {slot['pt']})")
        r = build_slot(v, slot)
        print(f"  m_Scale = {r['scale']}  (висота великих літер = {REL} від латиниці)")
        out[key] = dict(asset_off=r["asset_off"], asset_len=len(r["asset_bytes"]),
                        atlas_off=r["atlas_off"], atlas_len=len(r["atlas_bytes"]),
                        scale=r["scale"], name=r["name"], tex=r["tex_name"])
    v.close()
    os.makedirs(SCAN, exist_ok=True)
    json.dump(out, open(os.path.join(SCAN, "inplace_plan.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\nОБА СЛОТИ ВКЛАДАЮТЬСЯ БЕЗ ЗМІНИ РОЗМІРУ. Запис на місце можливий.")
    print("→", os.path.join(SCAN, "inplace_plan.json"))


def cmd_verify_atlas():
    """Звіряє конвенцію перевороту: у прямокутнику гліфа мусить бути чорнило."""
    import numpy as np

    v = BundleView(os.path.join(AA, BUNDLE))
    slot = SLOTS["fixel"]
    o = v.sf.objects[slot["path_id"]]
    d = o.read_typetree()
    tex = v.sf.objects[d["m_AtlasTextures"][0]["m_PathID"]]
    td = tex.read_typetree()
    sd = td["m_StreamData"]
    a_off = v.abs_stream(sd["path"], sd["offset"])
    with open(v.path, "rb") as f:
        f.seek(a_off)
        raw = f.read(sd["size"])
    img = np.frombuffer(raw, dtype=np.uint8).reshape(td["m_Height"], td["m_Width"])
    top_down = np.flipud(img)          # у наші координати (0,0 — верхній лівий)
    uni = {c["m_Unicode"]: c["m_GlyphIndex"] for c in d["m_CharacterTable"]}
    gl = {g["m_Index"]: g for g in d["m_GlyphTable"]}
    print("перевірка прямокутників рідного атласу (0x0410 «А», 0x0411 «Б», 0x0456 «і»):")
    ok = True
    for u in (0x0410, 0x0411, 0x0456):
        g = gl[uni[u]]
        r = g["m_GlyphRect"]
        y0 = td["m_Height"] - (r["m_Y"] + r["m_Height"])
        patch = top_down[y0:y0 + r["m_Height"], r["m_X"]:r["m_X"] + r["m_Width"]]
        inside = int(patch.max()) if patch.size else 0
        # поза прямокутником (у паддінгу) значення мусять бути нижчими
        print(f"  U+{u:04X}: rect {r} -> max усередині {inside}")
        ok = ok and inside > 200
    v.close()
    print("КОНВЕНЦІЯ ПЕРЕВОРОТУ ПІДТВЕРДЖЕНА" if ok else "🔴 щось не так із переворотом")


def _write(path, patches, tag):
    """patches: [(offset, bytes)]. Робить бекап зачеплених діапазонів."""
    size = os.path.getsize(path)
    for off, blob in patches:
        if off < 0 or off + len(blob) > size:
            raise SystemExit(f"ЗАПИС ЗА МЕЖУ ФАЙЛУ: {off}+{len(blob)} > {size} — скасовано")
    os.makedirs(BACKUP, exist_ok=True)
    meta_path = os.path.join(BACKUP, f"{tag}.json")
    meta = []
    with open(path, "rb") as f:
        for off, blob in patches:
            f.seek(off)
            old = f.read(len(blob))
            bin_name = f"{tag}_{off}.bin"
            open(os.path.join(BACKUP, bin_name), "wb").write(old)
            meta.append(dict(file=path, offset=off, size=len(blob), backup=bin_name))
    json.dump(meta, open(meta_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    total = 0
    with open(path, "r+b") as f:
        for off, blob in patches:
            f.seek(off)
            f.write(blob)
            total += len(blob)
    print(f"  записано {total/1e6:.2f} МБ у {os.path.basename(path)}; "
          f"бекап: {os.path.basename(meta_path)}")


def cmd_apply():
    print("=" * 74)
    print("ЗАПИС ГАРНІТУР НА МІСЦЕ")
    print("=" * 74)
    path = os.path.join(AA, BUNDLE)
    v = BundleView(path)
    patches = []
    for key, slot in SLOTS.items():
        print(f"\n### {key.upper()} -> {slot['name']}")
        r = build_slot(v, slot)
        patches.append((r["asset_off"], r["asset_bytes"]))
        patches.append((r["atlas_off"], r["atlas_bytes"]))
    v.close()
    print()
    _write(path, patches, "bundle_fonts")


def cmd_restore(tag=None):
    tags = [tag] if tag else [f[:-5] for f in os.listdir(BACKUP) if f.endswith(".json")]
    for t in tags:
        meta = json.load(open(os.path.join(BACKUP, f"{t}.json"), encoding="utf-8"))
        for m in meta:
            blob = open(os.path.join(BACKUP, m["backup"]), "rb").read()
            assert len(blob) == m["size"]
            with open(m["file"], "r+b") as f:
                f.seek(m["offset"])
                f.write(blob)
        print(f"відкат {t}: {len(meta)} діапазонів повернуто")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "plan"
    {"plan": cmd_plan, "verify-atlas": cmd_verify_atlas,
     "apply": cmd_apply, "restore": cmd_restore}[cmd]()
