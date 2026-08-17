"""
Повний інвентар шрифтів і їх користувачів у resources.assets (typetree відсутній).

Прийоми:
  - клас кожного MonoBehaviour визначається за m_Script (карта scripts_map.json);
  - typetree для TMP_FontAsset позичається з бандла duplicateassetisolation;
  - частина шрифтових асетів має СТАРИЙ формат (m_Script веде у
    «Library/unity default resources») — для них fallback-и знаходимо
    пошуком 12-байтових PPtr у сирих байтах;
  - вбудовані класи (GameObject/RectTransform) читаються звичайно, тож
    для кожного напису відновлюємо повний шлях у ієрархії.

Вихід: <work_dir>/fonts_scan/resources_fonts.json + resources_holders.json
"""

from __future__ import annotations

import io
import json
import os
import struct
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402
from scan_all_fonts import Window, bundle_nodes  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

GAME = kitconfig.GAME
AA = kitconfig.AA
SCAN = kitconfig.SCAN


def borrow_typetree():
    import UnityPy

    b = [x for x in os.listdir(AA) if x.startswith("duplicateassetisolation")][0]
    ds, nodes = bundle_nodes(os.path.join(AA, b))
    off, size, fl, name = [n for n in nodes if not n[3].endswith(".resS")][0]
    fh = open(os.path.join(AA, b), "rb")
    sf = UnityPy.Environment().load_file(
        io.BufferedReader(Window(fh, ds + off, size), buffer_size=1 << 20), name=name)
    for st in sf.types:
        if st.node is not None and any(c.m_Name == "m_FaceInfo" for c in (st.node.m_Children or [])):
            return st.node
    return None


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
    import UnityPy

    path = os.path.join(GAME, "resources.assets")
    smap = json.load(open(os.path.join(SCAN, "scripts_map.json"), encoding="utf-8"))
    node = borrow_typetree()
    sf = UnityPy.Environment().load_file(open(path, "rb"), name="resources.assets")
    objs = sf.objects
    print(f"resources.assets: обʼєктів {len(objs)}, typetree={sf._enable_type_tree}")
    print("зовнішні:", [getattr(e, "path", "") for e in sf.externals])

    raws, cls = {}, {}
    for pid, o in objs.items():
        if o.type.name != "MonoBehaviour":
            continue
        raw = o.get_raw_data()
        raws[pid] = raw
        fid, spid = struct.unpack_from("<iq", raw, 16)
        key = f"ggm:{spid}" if fid == 2 else f"fid{fid}:{spid}"
        cls[pid] = smap.get(key, key)

    # ── шрифтові асети: новий формат (TMP_FontAsset) + старий (fid1:19001)
    font_pids = [p for p, c in cls.items() if c in ("TMP_FontAsset", "fid1:19001")]
    names = {p: mb_name(raws[p]) for p in font_pids}
    pats = {p: struct.pack("<iq", 0, p) for p in font_pids}

    fonts = []
    for p in font_pids:
        rec = dict(path_id=p, name=names[p], file="resources.assets",
                   fmt="new" if cls[p] == "TMP_FontAsset" else "old",
                   raw_size=len(raws[p]))
        ok = False
        if node is not None:
            try:
                d = objs[p].read_typetree(node)
                fi = d.get("m_FaceInfo") or {}
                rec.update(glyphs=len(d.get("m_GlyphTable") or []),
                           chars=len(d.get("m_CharacterTable") or []),
                           family=fi.get("m_FamilyName"), style=fi.get("m_StyleName"),
                           point=fi.get("m_PointSize"), scale=fi.get("m_Scale"),
                           cap=fi.get("m_CapLine"),
                           atlas=f"{d.get('m_AtlasWidth')}x{d.get('m_AtlasHeight')}",
                           pad=d.get("m_AtlasPadding"),
                           atlas_tex=[a.get("m_PathID") for a in (d.get("m_AtlasTextures") or [])],
                           fallbacks=[["resources.assets", r.get("m_PathID")]
                                      for r in (d.get("m_FallbackFontAssetTable") or [])])
                ok = True
            except Exception as e:
                rec["read_err"] = str(e)[:80]
        if not ok:
            # старий формат: fallback-и шукаємо в сирих байтах
            raw = raws[p]
            fb = []
            for q, pat in pats.items():
                if q == p:
                    continue
                i = raw.find(pat)
                while i != -1:
                    fb.append((i, q))
                    i = raw.find(pat, i + 1)
            fb.sort()
            rec["fallbacks"] = [["resources.assets", q] for _, q in fb]
            rec["glyphs"] = "?"
        fonts.append(rec)

    print(f"\nшрифтових асетів: {len(fonts)} "
          f"({sum(1 for f in fonts if f['fmt']=='new')} нових / "
          f"{sum(1 for f in fonts if f['fmt']=='old')} старих)")

    # ── користувачі шрифтів
    gocache, trc = {}, {}

    def go(g):
        if g not in gocache:
            try:
                gocache[g] = objs[g].read_typetree()
            except Exception:
                gocache[g] = {}
        return gocache[g]

    def tr(t):
        if t not in trc:
            try:
                trc[t] = objs[t].read_typetree()
            except Exception:
                trc[t] = {}
        return trc[t]

    def label(pid):
        raw = raws.get(pid, b"")
        if len(raw) < 12:
            return ""
        fid, g = struct.unpack_from("<iq", raw, 0)
        if fid != 0 or g not in objs:
            return f"<асет {mb_name(raw)}>" if mb_name(raw) else ""
        d = go(g)
        nm = d.get("m_Name", "")
        tid = 0
        for c in d.get("m_Component") or []:
            cp = c.get("component") if isinstance(c, dict) else None
            if isinstance(cp, dict):
                t = cp.get("m_PathID")
                if t in objs and objs[t].type.name in ("Transform", "RectTransform"):
                    tid = t
                    break
        chain, depth = [], 0
        while tid and depth < 12:
            td = tr(tid)
            f = (td.get("m_Father") or {}).get("m_PathID", 0)
            if not f or f not in objs:
                break
            fd = tr(f)
            gg = (fd.get("m_GameObject") or {}).get("m_PathID", 0)
            n2 = go(gg).get("m_Name", "") if gg in objs else ""
            if n2:
                chain.append(n2)
            tid = f
            depth += 1
        return "/".join(list(reversed(chain)) + [nm])

    holders = defaultdict(list)
    for pid, raw in raws.items():
        if pid in pats:
            continue                     # шрифти самі — вже розібрані
        for q, pat in pats.items():
            if pat in raw:
                holders[q].append(dict(path_id=pid, cls=cls.get(pid, "?"), label=label(pid)))

    print("\n" + "=" * 78)
    print("ХТО ЯКИМ ШРИФТОМ МАЛЮЄ У resources.assets")
    print("=" * 78)
    for f in sorted(fonts, key=lambda x: -len(holders.get(x["path_id"], []))):
        hs = holders.get(f["path_id"], [])
        if not hs:
            continue
        print(f"\n### {f['name']} (path_id={f['path_id']}, {f['fmt']}, гліфів {f.get('glyphs')})"
              f" — {len(hs)} посилань")
        cnt = Counter(f"{h['cls']}: {h['label']}" for h in hs)
        for k, c in cnt.most_common(30):
            print(f"     {c:>3}×  {k}")

    print("\n" + "=" * 78)
    print("FALLBACK-ЛАНЦЮГИ (усередині resources.assets)")
    print("=" * 78)
    nm = {f["path_id"]: f["name"] for f in fonts}
    for f in sorted(fonts, key=lambda x: x["name"] or ""):
        fb = f.get("fallbacks") or []
        if fb:
            print(f"  {f['name']:46s} -> {', '.join(nm.get(x[1], str(x[1])) for x in fb)}")
    print("\nБЕЗ fallback-ів:",
          ", ".join(f["name"] for f in fonts if not (f.get("fallbacks") or [])))

    json.dump(fonts, open(os.path.join(SCAN, "resources_fonts.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    json.dump({str(k): v for k, v in holders.items()},
              open(os.path.join(SCAN, "resources_holders.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("\n→", os.path.join(SCAN, "resources_fonts.json"))


if __name__ == "__main__":
    main()
