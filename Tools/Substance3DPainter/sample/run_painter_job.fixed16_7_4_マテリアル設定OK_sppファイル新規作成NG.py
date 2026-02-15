# Tools/SubstancePainter/run_painter_job.py
# Fixed16.7 - Stable (no f-string blocks) apply Unity-exported textures to a new Fill layer in Substance 3D Painter via remote scripting.
#
# Key design points:
# - Remote script is NOT built with f-strings or .format(). We use token replacement to avoid brace-related syntax errors.
# - Writes both RAW remote return and normalized JSON outputs.
#
# Outputs (in exportFolder):
# - painter_apply_<textureset>_Fixed16.7.json
# - painter_apply_<textureset>_RAW.txt
# - painter_remote_apply.log (summary)
#
# Expected job.json fields (already in your pipeline):
# - painterExePath
# - outputProjectPath
# - exportFolder
# - textureSets: [{ name: "...", textures: [{key:"BaseColor", value:"...png"}, ...] }]
#
# Painter tested target: 11.1.2 (Steam 2025) with --enable-remote-scripting

import json
import os
import sys
import time
import subprocess
import traceback

import lib_remote

VERSION = "Fixed16.7.4"

# ------------------ host utilities ------------------

def clean(v):
    return (v or "").strip()

def ensure_dir(p):
    if p:
        os.makedirs(p, exist_ok=True)

def write_text(path, msg):
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8", errors="replace") as f:
        f.write(msg)

def append(path, msg):
    ensure_dir(os.path.dirname(path))
    with open(path, "a", encoding="utf-8", errors="replace") as f:
        f.write(msg + "\n")

def log(local_log, msg):
    print(msg, flush=True)
    append(local_log, msg)

def py_escape_triple(s: str) -> str:
    # For embedding into remote exec('''...''') wrapper
    return s.replace("\\", "\\\\").replace("'''", "\\'\\'\\'")

def wrap_block_to_expression(block: str) -> str:
    blk = py_escape_triple(block)
    return "(lambda g: (exec('''%s''', g), g.get('OUT',''))[1])({})" % blk

def remote_exec_block(remote, block, label, local_log, timeout=300):
    log(local_log, f"[remote] exec {label}")
    res = remote.execScript(wrap_block_to_expression(block), "python", timeout=timeout)
    log(local_log, f"[remote] OK {label} (return={res})")
    return res

def start_painter(exe_path, spp_path, local_log):
    if not exe_path or not os.path.exists(exe_path):
        raise FileNotFoundError(f"Painter EXE not found: {exe_path}")
    args = [exe_path, "--enable-remote-scripting"]
    if spp_path and os.path.exists(spp_path):
        args.append(spp_path)
    log(local_log, f"[spawn] {args}")
    subprocess.Popen(args, cwd=os.path.dirname(exe_path))

def wait_remote(remote, local_log, timeout_http=240, timeout_py=300):
    t0 = time.time()
    while True:
        try:
            remote.checkConnection()
            log(local_log, "[remote] HTTP connected")
            break
        except Exception as e:
            if time.time() - t0 > timeout_http:
                raise RuntimeError(f"Remote HTTP timeout: {e}")
            time.sleep(1)

    t0 = time.time()
    while True:
        try:
            remote.execScript("1+1", "python", timeout=15)
            log(local_log, "[remote] Python ready")
            break
        except Exception as e:
            if time.time() - t0 > timeout_py:
                raise RuntimeError(f"Remote Python timeout: {e}")
            time.sleep(1)

def extract_texture_sets(job):
    tsets = job.get("textureSets") or []
    out = []
    if not isinstance(tsets, list):
        return out
    for ts in tsets:
        if not isinstance(ts, dict):
            continue
        name = clean(ts.get("name"))
        tex_entries = ts.get("textures") or []
        mapping = {}
        if isinstance(tex_entries, list):
            for e in tex_entries:
                if not isinstance(e, dict):
                    continue
                k = clean(e.get("key"))
                p = clean(e.get("value")) or clean(e.get("path"))
                if k and p:
                    mapping[k] = p
        if name and mapping:
            out.append((name, mapping))
    return out

def normalize_remote_json(res):
    if res is None:
        return None
    s = res if isinstance(res, str) else str(res)
    s = s.strip()
    try:
        obj = json.loads(s)
    except Exception:
        return None
    if isinstance(obj, str):
        inner = obj.strip()
        try:
            return json.loads(inner)
        except Exception:
            return {"_raw_string": obj}
    return obj

# ------------------ remote block template (NO f-string) ------------------

REMOTE_APPLY_TEMPLATE = r"""
import json, os, time, inspect, traceback

OUT_OBJ = {
  "_version": "__VERSION__",
  "_ts": int(time.time()),
  "textureset": "__TEX_SET_NAME__",
  "keys": [],
  "channeltype_members": [],
  "channeltype_map": {},
  "imports": [],
  "stack": None,
  "roots": [],
  "insert_position": None,
  "fill": None,
  "attempts": [],
  "errors": []
}

KEY_TO_PATH = __KEY_TO_PATH_JSON__
OUT_OBJ["keys"] = list(KEY_TO_PATH.keys())

# --- locate TextureSet & Stack ---
try:
    import substance_painter.textureset as textureset
    import substance_painter.layerstack as ls
except Exception as e:
    OUT_OBJ["errors"].append("import_modules_failed: " + str(e))
    OUT = json.dumps(OUT_OBJ, ensure_ascii=False)
else:
    ts = None
    try:
        for t in textureset.all_texture_sets():
            if t.name() == OUT_OBJ["textureset"]:
                ts = t
                break
    except Exception as e:
        OUT_OBJ["errors"].append("all_texture_sets_failed: " + str(e))

    if ts is None:
        OUT_OBJ["errors"].append("TextureSet not found")
        OUT = json.dumps(OUT_OBJ, ensure_ascii=False)
    else:
        stack = None
        try:
            if hasattr(ts, "all_stacks"):
                st = ts.all_stacks()
                if st:
                    stack = list(st)[0]
                    OUT_OBJ["attempts"].append({"step":"ts.all_stacks","ok":True,"count":len(list(st))})
        except Exception as e:
            OUT_OBJ["attempts"].append({"step":"ts.all_stacks","ok":False,"err":str(e)})

        if stack is None:
            try:
                if hasattr(ts, "get_stack"):
                    stack = ts.get_stack()
                    OUT_OBJ["attempts"].append({"step":"ts.get_stack()","ok":True,"type":str(type(stack))})
            except Exception as e:
                OUT_OBJ["attempts"].append({"step":"ts.get_stack()","ok":False,"err":str(e)})

        if stack is None:
            OUT_OBJ["errors"].append("No stack obtained from TextureSet")
            OUT = json.dumps(OUT_OBJ, ensure_ascii=False)
        else:
            OUT_OBJ["stack"] = {"type": str(type(stack)), "repr": str(stack)}

            roots = []
            try:
                roots = ls.get_root_layer_nodes(stack)
                OUT_OBJ["roots"] = [{"type": str(type(r)), "repr": str(r)} for r in roots]
            except Exception as e:
                OUT_OBJ["errors"].append("get_root_layer_nodes_failed: " + str(e))

            # --- ChannelType discovery ---
            CT = None
            try:
                if hasattr(textureset, "ChannelType"):
                    CT = textureset.ChannelType
                elif hasattr(textureset, "Channel"):
                    CT = textureset.Channel
            except Exception as e:
                OUT_OBJ["errors"].append("ChannelType_discovery_failed: " + str(e))

            lower_to_member = {}
            if CT is not None:
                try:
                    for _nm in dir(CT):
                        if _nm.startswith("_"):
                            continue
                        OUT_OBJ["channeltype_members"].append(_nm)
                        lower_to_member[_nm.lower()] = _nm
                except Exception as e:
                    OUT_OBJ["errors"].append("ChannelType_dir_failed: " + str(e))

            def pick_channel(key):
                k = (key or "").lower()
                # prefer exact matches first
                for cand in (k, k.replace(" ", ""), k.replace("_","")):
                    if cand in lower_to_member:
                        return getattr(CT, lower_to_member[cand])
                # common aliases
                if "base" in k or "albedo" in k or "diffuse" in k or "color" in k:
                    for cand in ("basecolor","base_color","albedo","diffuse","color"):
                        if cand in lower_to_member:
                            return getattr(CT, lower_to_member[cand])
                if "normal" in k:
                    for cand in ("normal","normalmap","normal_map"):
                        if cand in lower_to_member:
                            return getattr(CT, lower_to_member[cand])
                if "rough" in k:
                    for cand in ("roughness","rough"):
                        if cand in lower_to_member:
                            return getattr(CT, lower_to_member[cand])
                if "metal" in k:
                    for cand in ("metallic","metalness","metal"):
                        if cand in lower_to_member:
                            return getattr(CT, lower_to_member[cand])
                if "ao" in k or "occlusion" in k:
                    for cand in ("ao","ambientocclusion","occlusion"):
                        if cand in lower_to_member:
                            return getattr(CT, lower_to_member[cand])
                return None

            for k in KEY_TO_PATH.keys():
                try:
                    ch = pick_channel(k)
                    OUT_OBJ["channeltype_map"][k] = str(ch) if ch is not None else None
                except Exception as e:
                    OUT_OBJ["channeltype_map"][k] = "ERR:" + str(e)

            # --- create insert position + fill ---
            pos = None
            try:
                if hasattr(ls, "InsertPosition") and hasattr(ls.InsertPosition, "from_textureset_stack"):
                    pos = ls.InsertPosition.from_textureset_stack(stack)
                    OUT_OBJ["attempts"].append({"step":"InsertPosition.from_textureset_stack","ok":True,"type":str(type(pos))})
            except Exception as e:
                OUT_OBJ["attempts"].append({"step":"InsertPosition.from_textureset_stack","ok":False,"err":str(e)})

            if pos is None and roots:
                for fn in ("above_node","below_node","inside_node"):
                    try:
                        if hasattr(ls, "InsertPosition") and hasattr(ls.InsertPosition, fn):
                            pos = getattr(ls.InsertPosition, fn)(roots[0])
                            OUT_OBJ["attempts"].append({"step":"InsertPosition."+fn,"ok":True,"type":str(type(pos))})
                            break
                    except Exception as e:
                        OUT_OBJ["attempts"].append({"step":"InsertPosition."+fn,"ok":False,"err":str(e)})

            OUT_OBJ["insert_position"] = str(pos) if pos is not None else None

            fill = None
            try:
                if hasattr(ls, "insert_fill"):
                    fill = ls.insert_fill(pos) if pos is not None else ls.insert_fill()
                    OUT_OBJ["attempts"].append({"step":"ls.insert_fill","ok":True,"type":str(type(fill))})
            except Exception as e:
                OUT_OBJ["attempts"].append({"step":"ls.insert_fill","ok":False,"err":str(e)})

            if fill is None:
                OUT_OBJ["errors"].append("Fill creation failed")
                OUT = json.dumps(OUT_OBJ, ensure_ascii=False)
            else:
                OUT_OBJ["fill"] = {"type": str(type(fill)), "repr": str(fill)}

                # --- import textures and bind to fill ---
                def _pick_resource_usage(res_mod):
                    # Try to locate a usage enum/value for textures. Fallback to first enum member.
                    usage = None
                    try:
                        RU = getattr(res_mod, "ResourceUsage", None) or getattr(res_mod, "Usage", None)
                        if RU is None:
                            return None
                        names = [n for n in dir(RU) if not n.startswith("_")]
                        # Prefer names containing TEXTURE / BITMAP / IMAGE
                        prefer = []
                        for n in names:
                            ln = n.lower()
                            if "texture" in ln or "bitmap" in ln or "image" in ln:
                                prefer.append(n)
                        pick = prefer[0] if prefer else (names[0] if names else None)
                        return getattr(RU, pick) if pick else None
                    except Exception:
                        return None

                def import_texture(path):
                    try:
                        import substance_painter.resource as res
                    except Exception as e:
                        return (False, None, "resource_module_failed:" + str(e))

                    # Try import_project_resource first (it exists but may require resource_usage)
                    if hasattr(res, "import_project_resource"):
                        try:
                            sig = None
                            try:
                                import inspect
                                sig = str(inspect.signature(res.import_project_resource))
                            except Exception:
                                sig = None

                            # If it needs resource_usage, provide it.
                            usage = _pick_resource_usage(res)
                            if usage is not None:
                                try:
                                    rid = res.import_project_resource(path, usage)
                                    return (True, rid, "import_project_resource(path, usage)")
                                except TypeError:
                                    # maybe keyword name
                                    rid = res.import_project_resource(path, resource_usage=usage)
                                    return (True, rid, "import_project_resource(path, resource_usage=usage)")
                            # Otherwise try plain call
                            rid = res.import_project_resource(path)
                            return (True, rid, "import_project_resource(path)")
                        except Exception as e:
                            OUT_OBJ["attempts"].append({"step":"resource.import_project_resource","ok":False,"path":path,"err":str(e)})

                    # Other candidates (best-effort)
                    for fn in ("import_project","import_","import"):
                        if hasattr(res, fn):
                            try:
                                rid = getattr(res, fn)(path)
                                return (True, rid, fn)
                            except Exception as e:
                                OUT_OBJ["attempts"].append({"step":"resource."+fn,"ok":False,"path":path,"err":str(e)})

                    return (False, None, "no_import_fn_worked")

                for key, path in KEY_TO_PATH.items():
                    item = {"key": key, "path": path, "import_ok": False, "import_via": None, "resource": None, "set_ok": False, "set_err": None}
                    try:
                        if not os.path.exists(path):
                            item["set_err"] = "missing_file"
                            OUT_OBJ["imports"].append(item)
                            continue
                        ok, rid, via = import_texture(path)
                        item["import_ok"] = bool(ok)
                        item["import_via"] = via
                        item["resource"] = str(rid) if rid is not None else None
                        # Convert returned Resource -> ResourceID if needed
                        rid_id = rid
                        item["resource_type"] = str(type(rid)) if rid is not None else None
                        item["resource_id_type"] = None
                        item["resource_id"] = None
                        try:
                            import substance_painter.resource as resmod

                            # 1) Already a ResourceID?
                            if hasattr(resmod, "ResourceID") and rid is not None and isinstance(rid, resmod.ResourceID):
                                rid_id = rid
                                item["resource_id_type"] = str(type(rid_id))
                                item["resource_id"] = str(rid_id)

                            # 2) Try common attributes on Resource-like objects
                            if rid is not None and item["resource_id"] is None:
                                for _attr in ("identifier", "resource_id", "id", "resourceId"):
                                    try:
                                        if not hasattr(rid, _attr):
                                            continue
                                        _v = getattr(rid, _attr)
                                        _v = _v() if callable(_v) else _v
                                        if _v is None:
                                            continue
                                        if hasattr(resmod, "ResourceID") and isinstance(_v, resmod.ResourceID):
                                            rid_id = _v
                                            item["resource_id_type"] = str(type(rid_id))
                                            item["resource_id"] = str(rid_id)
                                            break
                                        # Sometimes it's a handle or primitive; keep it for later constructor attempts
                                        item["resource_id_candidate"] = str(_v)
                                    except Exception as e:
                                        OUT_OBJ["attempts"].append({"step":"rid.attr."+_attr,"ok":False,"err":str(e)})

                            # 3) Try ResourceID constructors / factories
                            if hasattr(resmod, "ResourceID") and rid is not None and item["resource_id"] is None:
                                _cands = []
                                _cands.append(("ResourceID(resource)", lambda: resmod.ResourceID(rid)))
                                if hasattr(rid, "handle"):
                                    _cands.append(("ResourceID(handle)", lambda: resmod.ResourceID(rid.handle)))
                                for _fn in ("from_resource", "fromResource", "from_handle", "fromHandle"):
                                    if hasattr(resmod.ResourceID, _fn):
                                        _cands.append((f"ResourceID.{_fn}(resource)", lambda _fn=_fn: getattr(resmod.ResourceID, _fn)(rid)))
                                        if hasattr(rid, "handle"):
                                            _cands.append((f"ResourceID.{_fn}(handle)", lambda _fn=_fn: getattr(resmod.ResourceID, _fn)(rid.handle)))
                                for _label, _call in _cands:
                                    try:
                                        _v = _call()
                                        if _v is None:
                                            continue
                                        if isinstance(_v, resmod.ResourceID):
                                            rid_id = _v
                                            item["resource_id_type"] = str(type(rid_id))
                                            item["resource_id"] = str(rid_id)
                                            break
                                    except Exception as e:
                                        OUT_OBJ["attempts"].append({"step":"rid.to_resourceid."+_label,"ok":False,"err":str(e)})

                        except Exception as e:
                            OUT_OBJ["attempts"].append({"step":"rid.to_resourceid","ok":False,"err":str(e)})
                        if not ok:
                            item["set_err"] = "import_failed"
                            OUT_OBJ["imports"].append(item)
                            continue

                        ch = pick_channel(key) if CT is not None else None
                        if ch is None:
                            item["set_err"] = "channeltype_not_found_for_key"
                            OUT_OBJ["imports"].append(item)
                            continue

                        # bind to fill
                        try:
                            if hasattr(fill, "set_source"):
                                fill.set_source(ch, rid_id)
                                item["set_ok"] = True
                            else:
                                item["set_err"] = "fill_has_no_set_source"
                        except Exception as e:
                            item["set_err"] = str(e)

                        OUT_OBJ["imports"].append(item)
                    except Exception as e:
                        item["set_err"] = "EX:" + str(e)
                        OUT_OBJ["imports"].append(item)

                OUT = json.dumps(OUT_OBJ, ensure_ascii=False)
"""

def build_remote_apply_block(ts_name: str, key_to_path: dict):
    # Token replacement only (no formatting), avoids brace issues.
    block = REMOTE_APPLY_TEMPLATE
    block = block.replace("__VERSION__", VERSION)
    block = block.replace("__TEX_SET_NAME__", ts_name.replace("\\", "\\\\").replace('"', '\"'))
    block = block.replace("__KEY_TO_PATH_JSON__", json.dumps(key_to_path, ensure_ascii=False))
    return block

# ------------------ main ------------------

def main():
    if len(sys.argv) < 2:
        print("Usage: run_painter_job.py job.json", flush=True)
        return 1

    job_json = os.path.abspath(sys.argv[1])
    with open(job_json, "r", encoding="utf-8-sig") as f:
        job = json.load(f)

    painter_exe = clean(job.get("painterExePath"))
    out_spp = clean(job.get("outputProjectPath"))
    export_folder = clean(job.get("exportFolder"))

    if not export_folder:
        print("exportFolder missing in job.json")
        return 2

    ensure_dir(export_folder)
    local_log = os.path.join(export_folder, "job_runner.local.log")
    apply_log = os.path.join(export_folder, "painter_remote_apply.log")

    log(local_log, f"=== START {VERSION} ===")
    log(local_log, f"JOB_JSON={job_json}")
    log(local_log, f"PainterExe={painter_exe}")
    log(local_log, f"OutputSPP={out_spp}")
    log(local_log, f"ExportFolder={export_folder}")

    write_text(apply_log, f"=== START painter_remote_apply.log ({VERSION}) ===\n")
    append(apply_log, f"JOB_JSON={job_json}")
    append(apply_log, f"OutputSPP={out_spp}")

    start_painter(painter_exe, out_spp, local_log)

    remote = lib_remote.RemotePainter()
    wait_remote(remote, local_log)

    tsets = extract_texture_sets(job)
    append(apply_log, f"textureSets_count={len(tsets)}")

    for (ts_name, key_to_path) in tsets:
        block = build_remote_apply_block(ts_name, key_to_path)
        raw = remote_exec_block(remote, block, f"apply_{ts_name}", local_log, timeout=1200)

        safe = ts_name.replace(":", "_").replace("/", "_")
        raw_path = os.path.join(export_folder, f"painter_apply_{safe}_RAW.txt")
        write_text(raw_path, (raw if isinstance(raw, str) else str(raw)) + "\n")
        append(apply_log, f"apply_raw_saved={raw_path}")

        obj = normalize_remote_json(raw)
        out_path = os.path.join(export_folder, f"painter_apply_{safe}_{VERSION}.json")
        if obj is None:
            write_text(out_path, json.dumps({"_version": VERSION, "_raw": raw}, ensure_ascii=False, indent=2) + "\n")
            append(apply_log, f"apply_saved_rawwrap={out_path}")
        else:
            write_text(out_path, json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
            append(apply_log, f"apply_saved={out_path}")

    append(apply_log, "=== END ===")
    log(local_log, f"=== DONE {VERSION} ===")
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as e:
        print("FATAL:", e, flush=True)
        traceback.print_exc()
        raise
