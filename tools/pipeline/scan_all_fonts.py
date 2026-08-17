"""
Повний скан ВСІХ бандлів на TMP_FontAsset — БЕЗ завантаження бандла в памʼять.

Ключова знахідка: блоки даних у бандлах гри НЕ стиснені (comp_type=0),
тому кожен SerializedFile (нода CAB-*) читається прямо з диска через вікно-стрім.
Пікова памʼять — десятки МБ, а не 7-20 ГБ.

Вихід: CSV із кожним знайденим шрифтовим асетом:
  bundle, file, path_id, name, family, style, atlas, glyphs, chars, fallbacks
плюс ребра fallback (хто на кого посилається).

Використання:
  python scan_all_fonts.py <тека_з_бандлами> [підрядок-фільтр ...]
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402

OUT_DIR = kitconfig.SCAN

# ─────────────────────────── читання заголовка бандла ───────────────────────────


def _cstr(f):
    out = bytearray()
    while True:
        c = f.read(1)
        if not c or c == b"\0":
            break
        out += c
    return out.decode("utf8", "replace")


def bundle_nodes(path):
    """Повертає (data_start, [(offset, size, flags, name)]) для НЕстисненого бандла."""
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        sig = _cstr(f)
        if sig != "UnityFS":
            raise ValueError(f"не UnityFS: {sig}")
        ver = struct.unpack(">I", f.read(4))[0]
        _cstr(f)
        _cstr(f)
        struct.unpack(">q", f.read(8))[0]
        ci, ui, flags = struct.unpack(">III", f.read(12))
        if ver >= 7:
            f.seek((f.tell() + 15) & ~15)
        if flags & 0x80:
            info_pos = size - ci
            f.seek(info_pos)
        blk = f.read(ci)
        ct = flags & 0x3F
        if ct in (2, 3):
            import lz4.block

            blk = lz4.block.decompress(blk, uncompressed_size=ui)
        elif ct == 1:
            import lzma

            blk = lzma.decompress(blk)
        if not (flags & 0x80):
            data_start = f.tell()
            if flags & 0x200:
                data_start = (data_start + 15) & ~15
        else:
            data_start = (((size - ci) and 0) or 0)  # info в кінці — не наш випадок
            raise ValueError("blockinfo у кінці — не підтримано")

    b = io.BytesIO(blk)
    b.read(16)
    nblocks = struct.unpack(">I", b.read(4))[0]
    blocks = [struct.unpack(">IIH", b.read(10)) for _ in range(nblocks)]
    for u, c, fl in blocks:
        if (fl & 0x3F) != 0:
            raise ValueError("блоки даних стиснені — потрібен інший шлях")
    nnodes = struct.unpack(">I", b.read(4))[0]
    nodes = []
    for _ in range(nnodes):
        off, sz = struct.unpack(">qq", b.read(16))
        fl = struct.unpack(">I", b.read(4))[0]
        nodes.append((off, sz, fl, _cstr(b)))
    return data_start, nodes


class Window(io.RawIOBase):
    """Вікно у файл: read/seek/tell відносно початку ноди."""

    def __init__(self, fh, off, size):
        self._f = fh
        self._off = off
        self._size = size
        self._pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def read(self, n=-1):
        if n is None or n < 0:
            n = self._size - self._pos
        n = max(0, min(n, self._size - self._pos))
        if n == 0:
            return b""
        self._f.seek(self._off + self._pos)
        data = self._f.read(n)
        self._pos += len(data)
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)

    def seek(self, pos, whence=0):
        if whence == 0:
            self._pos = pos
        elif whence == 1:
            self._pos += pos
        else:
            self._pos = self._size + pos
        self._pos = max(0, min(self._pos, self._size))
        return self._pos

    def tell(self):
        return self._pos

    def __len__(self):
        return self._size


# ─────────────────────────── скан однієї ноди ───────────────────────────

FONT_MARKERS = ("m_FaceInfo", "m_GlyphTable", "m_AtlasTextures")


def type_is_font(st):
    if (st.m_ClassName or "") in ("TMP_FontAsset", "TextMeshProFont"):
        return True
    node = st.node
    if node is None:
        return False
    for ch in getattr(node, "m_Children", []) or []:
        if ch.m_Name in FONT_MARKERS:
            return True
    return False


def scan_node(env_mod, fh, off, size, name, bundle, rows, edges):
    import UnityPy

    win = Window(fh, off, size)
    buf = io.BufferedReader(win, buffer_size=1 << 20)
    env = UnityPy.Environment()
    try:
        sf = env.load_file(buf, name=name)
    except Exception as e:
        return f"ПОМИЛКА розбору {name}: {e}"
    if sf is None or not hasattr(sf, "objects"):
        return None

    font_type_ids = set()
    for st in sf.types:
        try:
            if type_is_font(st):
                font_type_ids.add(id(st))
        except Exception:
            pass
    if not font_type_ids:
        return None

    externals = [getattr(e, "path", "") for e in sf.externals]
    found = 0
    for pid, obj in sf.objects.items():
        if id(getattr(obj, "serialized_type", None)) not in font_type_ids:
            continue
        found += 1
        try:
            d = obj.read_typetree()
        except Exception as e:
            rows.append(dict(bundle=bundle, file=name, path_id=pid, name="<НЕ ЧИТАЄТЬСЯ>",
                             err=str(e)[:120]))
            continue
        fi = d.get("m_FaceInfo") or {}
        fb = d.get("m_FallbackFontAssetTable") or []
        fb_ids = []
        for ref in fb:
            if isinstance(ref, dict):
                fb_ids.append((ref.get("m_FileID", 0), ref.get("m_PathID", 0)))
        mat = d.get("material") or {}
        atlases = d.get("m_AtlasTextures") or []
        rows.append(dict(
            bundle=bundle, file=name, path_id=pid,
            name=d.get("m_Name", ""),
            family=fi.get("m_FamilyName", ""),
            style=fi.get("m_StyleName", ""),
            point_size=fi.get("m_PointSize", ""),
            scale=fi.get("m_Scale", ""),
            atlas_w=d.get("m_AtlasWidth", ""), atlas_h=d.get("m_AtlasHeight", ""),
            padding=d.get("m_AtlasPadding", ""),
            glyphs=len(d.get("m_GlyphTable") or []),
            chars=len(d.get("m_CharacterTable") or []),
            n_atlas_tex=len(atlases),
            source_file=d.get("m_SourceFontFilePath", "") or d.get("m_SourceFontFileName", ""),
            mat_pathid=mat.get("m_PathID", ""),
            n_fallbacks=len(fb_ids),
            fallbacks=";".join(f"{a}:{b}" for a, b in fb_ids),
        ))
        for a, b in fb_ids:
            edges.append(dict(bundle=bundle, file=name, src_pathid=pid,
                             src_name=d.get("m_Name", ""),
                             dst_fileid=a, dst_pathid=b,
                             dst_external=externals[a - 1] if 0 < a <= len(externals) else ""))
    return f"{name}: {found} шрифтових асетів"


def scan_bundle(path, rows, edges, log):
    bname = os.path.basename(path)
    t0 = time.time()
    data_start, nodes = bundle_nodes(path)
    sf_nodes = [n for n in nodes if not n[3].endswith(".resS")]
    tot = sum(n[1] for n in sf_nodes)
    print(f"\n=== {bname}: {len(sf_nodes)} SerializedFile-нод, {tot/1e9:.2f} ГБ до сканування", flush=True)
    for i, (off, size, fl, name) in enumerate(sf_nodes, 1):
        with open(path, "rb") as fh:
            msg = scan_node(None, fh, data_start + off, size, name, bname, rows, edges)
        if msg:
            print(f"  [{i}/{len(sf_nodes)}] {msg}", flush=True)
            log.append(f"{bname}|{msg}")
        elif i % 200 == 0 or i == len(sf_nodes):
            print(f"  [{i}/{len(sf_nodes)}] ...", flush=True)
    print(f"  готово за {time.time()-t0:.0f} с", flush=True)


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else kitconfig.AA
    filters = sys.argv[2:]
    files = sorted(
        (os.path.join(src, f) for f in os.listdir(src) if f.endswith(".bundle")),
        key=os.path.getsize,
    )
    if filters:
        files = [f for f in files if any(s in os.path.basename(f) for s in filters)]
    os.makedirs(OUT_DIR, exist_ok=True)
    rows, edges, log = [], [], []
    for f in files:
        try:
            scan_bundle(f, rows, edges, log)
        except Exception as e:
            print(f"!! {os.path.basename(f)}: {e}", flush=True)
        # інкрементальне збереження — щоб не втратити прогрес
        tag = "_".join(filters) if filters else "all"
        with open(os.path.join(OUT_DIR, f"fonts_{tag}.json"), "w", encoding="utf-8") as fp:
            json.dump(dict(rows=rows, edges=edges, log=log), fp, ensure_ascii=False, indent=1)
    print(f"\nУСЬОГО шрифтових асетів: {len(rows)}, fallback-ребер: {len(edges)}")
    for r in rows:
        print(f"  {r.get('name','?'):45s} {r.get('glyphs','?'):>6} гліфів  "
              f"fb={r.get('n_fallbacks','?')}  [{r['bundle'][:22]} / {r['file'][:28]}]")


if __name__ == "__main__":
    main()
