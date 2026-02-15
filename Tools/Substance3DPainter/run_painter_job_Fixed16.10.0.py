# run_painter_job.py
# Fixed16.10.0 - Stable project ensure + proven texture apply logic from Fixed16.7.4.
#   - ChannelType alias resolution (BaseColor, AO->AmbientOcclusion, Roughness, Metallic, Emission->Emissive)
#   - Resource -> ResourceID conversion with multi-step fallback (identifier(), constructors, factories)
#   - Fill layer set_source(ChannelType, ResourceID) - correct argument order
# For Adobe Substance 3D Painter 11.0+ (Steam/Standalone) with --enable-remote-scripting
#
# Usage:
#   python run_painter_job.py path\to\job.json
#
# Outputs under exportFolder:
#   job_runner.local.log
#   painter_remote_apply.log
#   painter_apply_<TextureSetName>_RAW.txt
#   painter_apply_<TextureSetName>_Fixed16.10.0.json

import json
import os
import sys
import time
import subprocess
import traceback

import lib_remote

VERSION = "Fixed16.10.0"

def _clean(v):
    return (v or '').strip()

def _ensure_dir(p):
    if p:
        os.makedirs(p, exist_ok=True)

def _write_text(path, msg):
    _ensure_dir(os.path.dirname(path))
    with open(path, 'w', encoding='utf-8', errors='replace') as f:
        f.write(msg)

def _append(path, msg):
    _ensure_dir(os.path.dirname(path))
    with open(path, 'a', encoding='utf-8', errors='replace') as f:
        f.write(msg + '\n')

def _log(local_log, msg):
    print(msg, flush=True)
    _append(local_log, msg)

def _py_escape_triple(s: str) -> str:
    return s.replace('\\', '\\\\').replace("'''", "\\'\\'\\'")

def _wrap_block_to_expression(block: str) -> str:
    blk = _py_escape_triple(block)
    return "(lambda g: (exec('''%s''', g), g.get('OUT',''))[1])({})" % blk

def _remote_exec_block(remote, block, label, local_log, timeout=1200):
    _log(local_log, f'[remote] exec {label}')
    try:
        res = remote.execScript(_wrap_block_to_expression(block), 'python', timeout=timeout)
        _log(local_log, f'[remote] OK {label} (return_len={len(res) if isinstance(res,str) else "n/a"})')
        return res
    except Exception as e:
        # Return a JSON error object so caller can log/abort gracefully (prevents "logs stop at 2 files" syndrome).
        _log(local_log, f'[remote] NG {label}: {e}')
        return json.dumps({
            "_remote_error": True,
            "label": label,
            "error": str(e),
        }, ensure_ascii=False)

def _wait_remote(remote, local_log, timeout_http=240, timeout_py=300):
    t0 = time.time()
    while True:
        try:
            remote.checkConnection()
            _log(local_log, '[remote] HTTP connected')
            break
        except Exception as e:
            if time.time() - t0 > timeout_http:
                raise RuntimeError(f'Remote HTTP timeout: {e}')
            time.sleep(1)
    t0 = time.time()
    while True:
        try:
            remote.execScript('1+1', 'python', timeout=15)
            _log(local_log, '[remote] Python ready')
            break
        except Exception as e:
            if time.time() - t0 > timeout_py:
                raise RuntimeError(f'Remote Python timeout: {e}')
            time.sleep(1)

def _start_painter(exe_path, spp_path, local_log):
    if not exe_path or not os.path.exists(exe_path):
        raise FileNotFoundError(f'Painter EXE not found: {exe_path}')
    args = [exe_path, '--enable-remote-scripting']
    if spp_path and os.path.exists(spp_path):
        args.append(spp_path)
    _log(local_log, f'[spawn] {args}')
    subprocess.Popen(args, cwd=os.path.dirname(exe_path))

def _extract_texture_sets(job):
    tsets = job.get('textureSets') or []
    out = []
    if not isinstance(tsets, list):
        return out
    for ts in tsets:
        if not isinstance(ts, dict):
            continue
        name = _clean(ts.get('name'))
        tex_entries = ts.get('textures') or []
        mapping = {}
        if isinstance(tex_entries, list):
            for e in tex_entries:
                if not isinstance(e, dict):
                    continue
                k = _clean(e.get('key'))
                p = _clean(e.get('value')) or _clean(e.get('path'))
                if k and p:
                    mapping[k] = p
        if name and mapping:
            out.append((name, mapping))
    return out

def _normalize_remote_json(res):
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
            return {'_raw_string': obj}
    return obj

REMOTE_ENSURE_PROJECT_ASYNC_START = r'''
import json, os, time, traceback, threading
import substance_painter.application as app
import substance_painter.project as project

OUT_OBJ = {
  '_version': '__VERSION__',
  '_ts': int(time.time()),
  'meshPath': '__MESH__',
  'outputProjectPath': '__SPP__',
  'saveDelaySec': __SAVE_DELAY__,
  'reopenDelaySec': __REOPEN_DELAY__,
  'job_id': None,
  'errors': [],
}

def _norm(p):
  if p is None: return None
  p = str(p).strip().strip('"')
  p = os.path.normpath(p)
  # keep drive letter, convert to forward slashes for consistency in logs
  p = p.replace('\\', '/')
  # collapse duplicate slashes after drive (C://// -> C:/)
  if len(p) >= 3 and p[1] == ':' and p[2] == '/':
    while len(p) >= 4 and p[3] == '/':
      p = p[:3] + p[3:].replace('//','/')
      break
  while '//' in p:
    p = p.replace('//','/')
  return p

MESH = _norm(OUT_OBJ['meshPath'])
SPP  = _norm(OUT_OBJ['outputProjectPath'])
OUT_OBJ['meshPath_norm'] = MESH
OUT_OBJ['outputProjectPath_norm'] = SPP

job_id = str(int(time.time()*1000))
OUT_OBJ['job_id'] = job_id

if not hasattr(app, '_unity_job_state'):
  app._unity_job_state = {}

state = {
  'job_id': job_id,
  'status': 'running',
  'step': 'start',
  'ts': time.time(),
  'mesh': MESH,
  'spp': SPP,
  'error': None,
  'trace': None,
}

app._unity_job_state[job_id] = state

def _set(step, status=None):
  state['step'] = step
  state['ts'] = time.time()
  if status:
    state['status'] = status

def _worker_create_only():
  try:
    _set('precheck')
    if not (MESH and os.path.exists(MESH)):
      raise RuntimeError('mesh_missing_or_not_found')
    _set('create_begin')
    try:
      project.create(MESH)
    except TypeError:
      project.create(mesh_file_path=MESH)
    _set('create_done', status='ready_for_save')
  except Exception as e:
    _set('error', status='error')
    state['error'] = (repr(e) if isinstance(e, BaseException) else str(e))
    try:
      state['trace'] = traceback.format_exc()
    except Exception:
      pass

threading.Thread(target=_worker_create_only, daemon=True).start()

OUT = json.dumps(OUT_OBJ, ensure_ascii=False)

'''


REMOTE_ENSURE_PROJECT_ASYNC_POLL = r'''
import json
import substance_painter.application as app
job_id = r"__JOB_ID__"
st = None
if hasattr(app, '_unity_job_state'):
  st = app._unity_job_state.get(job_id)
OUT = json.dumps(st, ensure_ascii=False)

'''


REMOTE_ENSURE_PROJECT_ASYNC_SAVE = r'''
import json, os, time, traceback
import substance_painter.application as app
import substance_painter.project as project

job_id = r"__JOB_ID__"
spp = r"__SPP__"
save_delay = float("__SAVE_DELAY__")
reopen_delay = float("__REOPEN_DELAY__")

OUT_OBJ = {'job_id': job_id, 'status': None, 'step': None, 'error': None}

try:
  st = None
  if hasattr(app, '_unity_job_state'):
    st = app._unity_job_state.get(job_id)
  if not st:
    raise RuntimeError('job_state_missing')
  if st.get('status') != 'ready_for_save':
    raise RuntimeError('not_ready_for_save:' + str(st.get('status')))

  st['step'] = 'save_as_begin'; st['ts']=time.time()
  d = os.path.dirname(spp)
  if d and (not os.path.exists(d)):
    os.makedirs(d, exist_ok=True)

  project.save_as(spp)
  st['step'] = 'save_as_done'; st['ts']=time.time()

  if save_delay > 0:
    time.sleep(min(2.0, max(0.0, save_delay)))

  # close/reopen best-effort
  try:
    if hasattr(project, 'close'):
      project.close()
      st['step'] = 'close_after_save'; st['ts']=time.time()
      time.sleep(min(2.0, max(0.0, reopen_delay)))
  except Exception as e:
    st['close_error'] = str(e)

  try:
    project.open(spp)
    st['step'] = 'open_after_save'; st['ts']=time.time()
  except Exception as e:
    st['open_error'] = str(e)

  st['status'] = 'done'; st['step'] = 'done'; st['ts']=time.time()
  OUT_OBJ['status']='done'; OUT_OBJ['step']=st['step']

except Exception as e:
  OUT_OBJ['status']='error'
  OUT_OBJ['step']='error'
  OUT_OBJ['error']= (repr(e) if isinstance(e, BaseException) else str(e))
  try:
    OUT_OBJ['trace']=traceback.format_exc()
  except Exception:
    pass

OUT = json.dumps(OUT_OBJ, ensure_ascii=False)

'''

REMOTE_APPLY_TEMPLATE = r'''import json, os, time, traceback

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
                if "emis" in k or "emission" in k:
                    for cand in ("emissive","emission","emis"):
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
                    usage = None
                    try:
                        RU = getattr(res_mod, "ResourceUsage", None) or getattr(res_mod, "Usage", None)
                        if RU is None:
                            return None
                        names = [n for n in dir(RU) if not n.startswith("_")]
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

                    if hasattr(res, "import_project_resource"):
                        try:
                            usage = _pick_resource_usage(res)
                            if usage is not None:
                                try:
                                    rid = res.import_project_resource(path, usage)
                                    return (True, rid, "import_project_resource(path, usage)")
                                except TypeError:
                                    rid = res.import_project_resource(path, resource_usage=usage)
                                    return (True, rid, "import_project_resource(path, resource_usage=usage)")
                            rid = res.import_project_resource(path)
                            return (True, rid, "import_project_resource(path)")
                        except Exception as e:
                            OUT_OBJ["attempts"].append({"step":"resource.import_project_resource","ok":False,"path":path,"err":str(e)})

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
                                        _cands.append(("ResourceID."+_fn+"(resource)", lambda _fn=_fn: getattr(resmod.ResourceID, _fn)(rid)))
                                        if hasattr(rid, "handle"):
                                            _cands.append(("ResourceID."+_fn+"(handle)", lambda _fn=_fn: getattr(resmod.ResourceID, _fn)(rid.handle)))
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

                        # bind to fill layer (ChannelType, ResourceID)
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
'''

def _build_ensure_project_async_start(mesh_path: str, spp_path: str, save_delay: float, reopen_delay: float) -> str:
    b = REMOTE_ENSURE_PROJECT_ASYNC_START
    b = b.replace('__VERSION__', VERSION)
    b = b.replace('__MESH__', (mesh_path or '').replace('\\', '\\\\').replace('"','\\"'))
    b = b.replace('__SPP__', (spp_path or '').replace('\\', '\\\\').replace('"','\\"'))
    b = b.replace('__SAVE_DELAY__', str(float(save_delay)))
    b = b.replace('__REOPEN_DELAY__', str(float(reopen_delay)))
    return b

def _build_ensure_project_async_poll(job_id: str) -> str:
    b = REMOTE_ENSURE_PROJECT_ASYNC_POLL
    b = b.replace('__JOB_ID__', (job_id or '').replace('\\', '\\\\').replace('"','\\"'))
    return b

def _build_remote_apply_block(ts_name: str, key_to_path: dict) -> str:
    block = REMOTE_APPLY_TEMPLATE
    block = block.replace('__VERSION__', VERSION)
    block = block.replace('__TEX_SET_NAME__', ts_name.replace('\\','\\\\').replace('"','\\"'))
    block = block.replace('__KEY_TO_PATH_JSON__', json.dumps(key_to_path, ensure_ascii=False))
    return block

def main():
    if len(sys.argv) < 2:
        print('Usage: run_painter_job.py job.json', flush=True)
        return 1
    job_json = os.path.abspath(sys.argv[1])
    with open(job_json, 'r', encoding='utf-8-sig') as f:
        job = json.load(f)
    painter_exe = _clean(job.get('painterExePath'))
    out_spp = _clean(job.get('outputProjectPath'))
    export_folder = _clean(job.get('exportFolder'))
    mesh_path = _clean(job.get('meshPath'))
    save_delay = float(job.get('saveDelaySec', 3.0))
    reopen_delay = float(job.get('reopenDelaySec', 1.5))
    if not export_folder:
        print('exportFolder missing in job.json', flush=True)
        return 2
    _ensure_dir(export_folder)
    local_log = os.path.join(export_folder, 'job_runner.local.log')
    apply_log = os.path.join(export_folder, 'painter_remote_apply.log')
    _log(local_log, f'=== START {VERSION} ===')
    _log(local_log, f'JOB_JSON={job_json}')
    _log(local_log, f'PainterExe={painter_exe}')
    _log(local_log, f'OutputSPP={out_spp}')
    _log(local_log, f'MeshPath={mesh_path}')
    _log(local_log, f'ExportFolder={export_folder}')
    _log(local_log, f'saveDelaySec={save_delay}')
    _log(local_log, f'reopenDelaySec={reopen_delay}')
    _write_text(apply_log, f'=== START painter_remote_apply.log ({VERSION}) ===\n')
    _append(apply_log, f'JOB_JSON={job_json}')
    _append(apply_log, f'OutputSPP={out_spp}')
    _append(apply_log, f'MeshPath={mesh_path}')
    _append(apply_log, f'saveDelaySec={save_delay}')
    _append(apply_log, f'reopenDelaySec={reopen_delay}')
    _start_painter(painter_exe, out_spp, local_log)
    remote = lib_remote.RemotePainter()
    _wait_remote(remote, local_log)
    _append(apply_log, 'Ensuring project open/create/save_as (remote)...')
    # Start ensure project job (returns quickly)
    ensure_start = _build_ensure_project_async_start(mesh_path, out_spp, save_delay, reopen_delay)
    start_raw = _remote_exec_block(remote, ensure_start, 'ensure_project_start', local_log, timeout=30)
    start_obj = _normalize_remote_json(start_raw) or {}
    job_id = start_obj.get('job_id')
    _append(apply_log, 'ensure_project_job_id=' + str(job_id))
    if not job_id:
        _append(apply_log, 'ensure_project_start_raw=' + str(start_raw)[:2000])
        raise RuntimeError('ensure_project_start_no_job_id')


    # Poll until done/error
    t0 = time.time()
    timeout_sec = 900  # 15 min max for heavy FBX
    last_step = None
    final_state = None
    while True:
        poll_block = _build_ensure_project_async_poll(str(job_id))
        poll_raw = _remote_exec_block(remote, poll_block, 'ensure_project_poll', local_log, timeout=20)
        st = _normalize_remote_json(poll_raw)
        if isinstance(st, dict):
            step = st.get('step')
            status = st.get('status')
            if step != last_step:
                _log(local_log, f"[ensure_project] status={status} step={step}")
                last_step = step
            if status in ('ready_for_save','done', 'error'):
                final_state = st
                break
        if time.time() - t0 > timeout_sec:
            _log(local_log, '[ensure_project] TIMEOUT')
            final_state = {'status':'timeout','step':last_step}
            break
        time.sleep(1.0)

    
    # If create finished, run save_as on main (separate remote call)
    if isinstance(final_state, dict) and final_state.get('status') == 'ready_for_save':
        save_block = REMOTE_ENSURE_PROJECT_ASYNC_SAVE.replace('__JOB_ID__', str(job_id)).replace('__SPP__', out_spp).replace('__SAVE_DELAY__', str(save_delay)).replace('__REOPEN_DELAY__', str(reopen_delay))
        save_raw = _remote_exec_block(remote, save_block, 'ensure_project_save', local_log, timeout=120)
        save_obj = _normalize_remote_json(save_raw) or {}
        _append(apply_log, 'ensure_project_save=' + json.dumps(save_obj, ensure_ascii=False))
        # refresh final_state by polling once more
        poll_block = _build_ensure_project_async_poll(str(job_id))
        poll_raw = _remote_exec_block(remote, poll_block, 'ensure_project_poll_after_save', local_log, timeout=20)
        final_state = _normalize_remote_json(poll_raw) or final_state

    _append(apply_log, 'ensure_project_result=' + json.dumps(final_state, ensure_ascii=False))
    if isinstance(final_state, dict) and final_state.get('status') == 'error':
        _log(local_log, '[ensure_project] ERROR')
        _log(local_log, (final_state.get('error') or '')[:2000])
        return 10

    if isinstance(final_state, dict) and final_state.get('status') == 'timeout':
        return 11

    _append(apply_log, 'Waiting texture sets to be ready (remote)...')
    wait_block = r'''
import json, time
OUT_OBJ={'_version':'__VERSION__','_ts':int(time.time()),'tries':[],'ok':False,'count':0,'names':[]}
try:
  import substance_painter.textureset as textureset
except Exception as e:
  OUT_OBJ['tries'].append({'i':0,'err':'import_failed:'+str(e)})
  OUT=json.dumps(OUT_OBJ, ensure_ascii=False)
else:
  for i in range(20):
    try:
      ts=list(textureset.all_texture_sets())
      names=[]
      for t in ts:
        try: names.append(t.name())
        except Exception: names.append(str(t))
      OUT_OBJ['tries'].append({'i':i,'count':len(ts),'names':names})
      if len(ts)>0:
        OUT_OBJ['ok']=True; OUT_OBJ['count']=len(ts); OUT_OBJ['names']=names
        break
    except Exception as e:
      OUT_OBJ['tries'].append({'i':i,'err':str(e)})
    time.sleep(0.5)
  OUT=json.dumps(OUT_OBJ, ensure_ascii=False)
'''
    wait_block = wait_block.replace('__VERSION__', VERSION)
    wait_raw = _remote_exec_block(remote, wait_block, 'wait_texturesets', local_log, timeout=600)
    _append(apply_log, 'wait_texturesets_return=' + str(wait_raw)[:4000])
    tsets = _extract_texture_sets(job)
    _append(apply_log, f'textureSets_count={len(tsets)}')
    for (ts_name, key_to_path) in tsets:
        _append(apply_log, f'--- APPLY TextureSet={ts_name} keys={list(key_to_path.keys())} ---')
        block = _build_remote_apply_block(ts_name, key_to_path)
        raw = _remote_exec_block(remote, block, f'apply_{ts_name}', local_log, timeout=1800)
        safe = ts_name.replace(':','_').replace('/','_').replace('\\','_').replace(' ','_')
        raw_path = os.path.join(export_folder, f'painter_apply_{safe}_RAW.txt')
        _write_text(raw_path, (raw if isinstance(raw,str) else str(raw)) + '\n')
        _append(apply_log, f'apply_raw_saved={raw_path}')
        obj = _normalize_remote_json(raw)
        out_path = os.path.join(export_folder, f'painter_apply_{safe}_{VERSION}.json')
        if obj is None:
            _write_text(out_path, json.dumps({'_version':VERSION,'_raw':raw}, ensure_ascii=False, indent=2) + '\n')
            _append(apply_log, f'apply_saved_rawwrap={out_path}')
        else:
            _write_text(out_path, json.dumps(obj, ensure_ascii=False, indent=2) + '\n')
            _append(apply_log, f'apply_saved={out_path}')
    _append(apply_log, '=== END ===')
    _log(local_log, f'=== DONE {VERSION} ===')
    return 0

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except Exception as e:
        print('FATAL:', e, flush=True)
        traceback.print_exc()
        raise
