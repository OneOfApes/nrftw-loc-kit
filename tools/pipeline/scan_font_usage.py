"""
Скан ВСІХ бандлів: хто посилається на які TMP-шрифти і як цей елемент називається.

Працює потоково з диска (блоки бандлів не стиснені) — пікова памʼять десятки МБ.

Що збирає:
  1) інвентар шрифтових асетів (TMP_FontAsset) у кожному SerializedFile;
  2) УСІ MonoBehaviour, у чиєму типі є поле PPtr<$TMP_FontAsset>
     (це TextMeshProUGUI/TextMeshPro, TMP_Settings, і будь-які скрипти гри),
     з якого поля і на який шрифт вони вказують;
  3) назву GameObject-а й ланцюжок батьків — щоб було видно, ЩО це за напис;
  4) addressable-імена з AssetBundle.m_Container.

  python scan_font_usage.py <тека_бандлів> [підрядок-фільтр ...] [--no-parents]
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import kitconfig  # noqa: E402
from scan_all_fonts import Window, bundle_nodes  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT_DIR = kitconfig.SCAN
FONT_PPTR = "PPtr<$TMP_FontAsset>"
FONT_MARKERS = ("m_FaceInfo", "m_GlyphTable")
CLASS_GAMEOBJECT = 1
CLASS_TRANSFORM = 4
CLASS_RECTTRANSFORM = 224
CLASS_ASSETBUNDLE = 142
MAX_DEPTH = 8


def type_is_font(st):
    if (st.m_ClassName or "") in ("TMP_FontAsset", "TextMeshProFont"):
        return True
    node = st.node
    if node is None:
        return False
    return any(ch.m_Name in FONT_MARKERS for ch in (node.m_Children or []))


def font_fields(st):
    """Імена полів типу, які є посиланням на TMP_FontAsset."""
    node = st.node
    if node is None:
        return ()
    out = []
    for n in node.traverse():
        if n.m_Type == FONT_PPTR:
            out.append(n.m_Name)
    return tuple(dict.fromkeys(out))


def collect_pptrs(obj, names):
    """Рекурсивно витягує всі PPtr під ключами з names."""
    found = []

    def walk(v, key=None):
        if isinstance(v, dict):
            if key in names and "m_PathID" in v:
                found.append((key, v.get("m_FileID", 0), v.get("m_PathID", 0)))
                return
            for k, vv in v.items():
                walk(vv, k)
        elif isinstance(v, list):
            for vv in v:
                walk(vv, key)

    walk(obj)
    return found


def scan_node(path, data_start, off, size, node_name, bundle, out, want_parents=True):
    import UnityPy

    fh = open(path, "rb")
    try:
        buf = io.BufferedReader(Window(fh, data_start + off, size), buffer_size=4 << 20)
        env = UnityPy.Environment()
        try:
            sf = env.load_file(buf, name=node_name)
        except Exception as e:
            out["errors"].append(f"{bundle}|{node_name}|load: {e}")
            return
        if sf is None or not hasattr(sf, "objects"):
            return

        font_tids, holder_tids = set(), {}
        for st in sf.types:
            try:
                if type_is_font(st):
                    font_tids.add(id(st))
                    continue
                ff = font_fields(st)
                if ff:
                    holder_tids[id(st)] = ((st.m_ClassName or f"class{st.class_id}"), ff)
            except Exception:
                pass

        objs = sf.objects
        externals = [getattr(e, "path", "") for e in sf.externals]

        def extname(fid):
            if fid == 0:
                return node_name
            p = externals[fid - 1] if 0 < fid <= len(externals) else f"<fid{fid}>"
            return p.rsplit("/", 1)[-1]

        fonts, holders, bundles_ab = [], [], []
        for pid, obj in objs.items():
            stid = id(getattr(obj, "serialized_type", None))
            if stid in font_tids:
                fonts.append((pid, obj))
            elif stid in holder_tids:
                holders.append((pid, obj))
            elif obj.class_id == CLASS_ASSETBUNDLE:
                bundles_ab.append((pid, obj))
        if not fonts and not holders:
            return

        # ── addressable-контейнер (назви ассетів)
        container = {}
        for pid, obj in bundles_ab:
            try:
                d = obj.read_typetree()
            except Exception:
                continue
            for ent in d.get("m_Container") or []:
                try:
                    nm = ent["first"] if isinstance(ent, (list, tuple)) is False else ent[0]
                except Exception:
                    continue
                if isinstance(ent, (list, tuple)):
                    nm, val = ent[0], ent[1]
                else:
                    nm, val = ent.get("first"), ent.get("second")
                if isinstance(val, dict):
                    a = val.get("asset") or val
                    container[a.get("m_PathID")] = nm

        # ── шрифтові асети цього файлу
        for pid, obj in sorted(fonts, key=lambda x: getattr(x[1], "byte_start", 0)):
            try:
                d = obj.read_typetree()
            except Exception as e:
                out["errors"].append(f"{bundle}|{node_name}|font {pid}: {e}")
                continue
            fi = d.get("m_FaceInfo") or {}
            fb = [(r.get("m_FileID", 0), r.get("m_PathID", 0))
                  for r in (d.get("m_FallbackFontAssetTable") or []) if isinstance(r, dict)]
            out["fonts"].append(dict(
                bundle=bundle, file=node_name, path_id=pid, name=d.get("m_Name", ""),
                family=fi.get("m_FamilyName", ""), style=fi.get("m_StyleName", ""),
                point=fi.get("m_PointSize"), scale=fi.get("m_Scale"),
                cap=fi.get("m_CapLine"), atlas=f"{d.get('m_AtlasWidth')}x{d.get('m_AtlasHeight')}",
                pad=d.get("m_AtlasPadding"), glyphs=len(d.get("m_GlyphTable") or []),
                chars=len(d.get("m_CharacterTable") or []),
                container=container.get(pid, ""),
                fallbacks=[[extname(a), b] for a, b in fb],
            ))

        # ── власники посилань
        need_go = {}
        for pid, obj in sorted(holders, key=lambda x: getattr(x[1], "byte_start", 0)):
            cls, ff = holder_tids[id(obj.serialized_type)]
            try:
                d = obj.read_typetree()
            except Exception as e:
                out["errors"].append(f"{bundle}|{node_name}|holder {pid}: {e}")
                continue
            refs = collect_pptrs(d, set(ff))
            refs = [r for r in refs if r[2] != 0]
            if not refs:
                continue
            go = (d.get("m_GameObject") or {}).get("m_PathID", 0)
            txt = d.get("m_text")
            rec = dict(bundle=bundle, file=node_name, path_id=pid, cls=cls, go=go,
                       sample_text=(txt[:60] if isinstance(txt, str) else ""),
                       refs=[[k, extname(a), b] for k, a, b in refs],
                       container=container.get(pid, ""))
            out["holders"].append(rec)
            if go:
                need_go.setdefault(go, []).append(rec)

        # ── назви GameObject-ів (другий послідовний прохід)
        if need_go:
            go_objs = [(pid, objs[pid]) for pid in need_go if pid in objs]
            names, tr_of = {}, {}
            for pid, obj in sorted(go_objs, key=lambda x: getattr(x[1], "byte_start", 0)):
                try:
                    d = obj.read_typetree()
                except Exception:
                    continue
                names[pid] = d.get("m_Name", "")
                for c in d.get("m_Component") or []:
                    cp = c.get("component") if isinstance(c, dict) else None
                    if isinstance(cp, dict):
                        tid = cp.get("m_PathID")
                        if tid in objs and objs[tid].class_id in (CLASS_TRANSFORM, CLASS_RECTTRANSFORM):
                            tr_of[pid] = tid
                            break
            for pid, recs in need_go.items():
                for r in recs:
                    r["go_name"] = names.get(pid, "")

            # ланцюжок батьків
            if want_parents:
                cache_tr, cache_go = {}, dict(names)

                def tr_data(tid):
                    if tid not in cache_tr:
                        try:
                            cache_tr[tid] = objs[tid].read_typetree()
                        except Exception:
                            cache_tr[tid] = {}
                    return cache_tr[tid]

                def go_name(gid):
                    if gid not in cache_go:
                        try:
                            cache_go[gid] = (objs[gid].read_typetree() or {}).get("m_Name", "")
                        except Exception:
                            cache_go[gid] = ""
                    return cache_go[gid]

                for pid, recs in need_go.items():
                    chain = []
                    tid = tr_of.get(pid)
                    depth = 0
                    while tid and depth < MAX_DEPTH:
                        td = tr_data(tid)
                        f = (td.get("m_Father") or {}).get("m_PathID", 0)
                        if not f or f not in objs:
                            break
                        fd = tr_data(f)
                        g = (fd.get("m_GameObject") or {}).get("m_PathID", 0)
                        nm = go_name(g) if g in objs else ""
                        if nm:
                            chain.append(nm)
                        tid = f
                        depth += 1
                    if chain:
                        for r in recs:
                            r["parents"] = "/".join(reversed(chain))
    finally:
        fh.close()


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else kitconfig.AA
    args = [a for a in sys.argv[2:] if not a.startswith("--")]
    want_parents = "--no-parents" not in sys.argv
    files = sorted((os.path.join(src, f) for f in os.listdir(src)
                    if f.endswith((".bundle", ".assets")) or f == "globalgamemanagers"),
                   key=os.path.getsize)
    if args:
        files = [f for f in files if any(s in os.path.basename(f) for s in args)]
    os.makedirs(OUT_DIR, exist_ok=True)
    out = dict(fonts=[], holders=[], errors=[])
    tag = "_".join(args) if args else "all"
    dst = os.path.join(OUT_DIR, f"usage_{tag}.json")

    for path in files:
        bname = os.path.basename(path)
        t0 = time.time()
        try:
            with open(path, "rb") as _f:
                is_fs = _f.read(7) == b"UnityFS"
            if is_fs:
                data_start, nodes = bundle_nodes(path)
            else:
                # звичайний SerializedFile (resources.assets, globalgamemanagers.assets…)
                data_start, nodes = 0, [(0, os.path.getsize(path), 4, bname)]
        except Exception as e:
            print(f"!! {bname}: {e}", flush=True)
            continue
        sf_nodes = [n for n in nodes if not n[3].endswith(".resS")]
        print(f"\n=== {bname}: {len(sf_nodes)} нод, "
              f"{sum(n[1] for n in sf_nodes)/1e9:.2f} ГБ", flush=True)
        n_f0, n_h0 = len(out["fonts"]), len(out["holders"])
        for i, (off, size, fl, name) in enumerate(sf_nodes, 1):
            before = (len(out["fonts"]), len(out["holders"]))
            scan_node(path, data_start, off, size, name, bname, out, want_parents)
            after = (len(out["fonts"]), len(out["holders"]))
            if after != before:
                print(f"  [{i}/{len(sf_nodes)}] {name}: +{after[0]-before[0]} шрифтів, "
                      f"+{after[1]-before[1]} посилань", flush=True)
            elif i % 300 == 0:
                print(f"  [{i}/{len(sf_nodes)}] ...", flush=True)
        print(f"  {bname}: шрифтів +{len(out['fonts'])-n_f0}, "
              f"посилань +{len(out['holders'])-n_h0}, {time.time()-t0:.0f} с", flush=True)
        with open(dst, "w", encoding="utf-8") as fp:
            json.dump(out, fp, ensure_ascii=False)

    print(f"\nшрифтових асетів: {len(out['fonts'])}, посилань: {len(out['holders'])}, "
          f"помилок: {len(out['errors'])}")
    print("→", dst)


if __name__ == "__main__":
    main()
