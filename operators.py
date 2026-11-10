# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

import bpy
import threading
import queue
import json
import datetime
import time
import base64
import os
import mimetypes
from .llm_handler import LLMClient
from .utils import graph_builder, math_utils, library_manager
from .utils import composition_engine, exploration_engine, semantic_init
from .utils.common import dict_to_str, str_to_dict

# Queue to communicate between threads
result_queue = queue.Queue()
semantic_queue = queue.Queue()
search_queue = queue.Queue()
preview_queue = queue.Queue()
_SEARCH_STATE_STACK_LIMIT = 20


def _debug_timing(enabled, message):
    if enabled:
        print(f"[MatComposer][Timing] {message}")

def _tag_redraw_all():
    wm = getattr(bpy.context, "window_manager", None)
    if not wm:
        return
    for win in getattr(wm, "windows", []) or []:
        screen = getattr(win, "screen", None)
        if not screen:
            continue
        for area in getattr(screen, "areas", []) or []:
            try:
                area.tag_redraw()
            except Exception:
                pass


def _safe_load_json_dict(s):
    if not s:
        return {}
    try:
        data = json.loads(s)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _snapshot_search_state(props):
    keys = [
        "semantic_plan_json",
        "semantic_repr_json",
        "slot_candidates_json",
        "slot_selection_json",
        "mask_selection_json",
        "candidate_pick_base",
        "candidate_pick_overlay",
        "candidate_pick_detail",
        "explore_candidate_1_id",
        "explore_candidate_2_id",
        "explore_candidate_3_id",
        "explore_candidate_4_id",
        "apply_slot_role",
        "prev_selected_entry_id",
        "curr_selected_entry_id",
        "generation_status",
    ]
    data = {}
    for k in keys:
        try:
            data[k] = getattr(props, k)
        except Exception:
            data[k] = ""
    stack = []
    raw = getattr(props, "last_search_state_json", "")
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                stack = [x for x in parsed if isinstance(x, dict)]
            elif isinstance(parsed, dict):
                # Backward compatibility: old single-snapshot format.
                stack = [parsed]
        except Exception:
            stack = []
    if not stack or stack[-1] != data:
        stack.append(data)
    if len(stack) > int(_SEARCH_STATE_STACK_LIMIT):
        stack = stack[-int(_SEARCH_STATE_STACK_LIMIT) :]
    try:
        props.last_search_state_json = json.dumps(stack)
    except Exception:
        props.last_search_state_json = ""


def _restore_search_state(props):
    s = getattr(props, "last_search_state_json", "")
    if not s:
        return False
    stack = []
    data = None
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            stack = [x for x in parsed if isinstance(x, dict)]
            if stack:
                data = stack.pop()
        elif isinstance(parsed, dict):
            # Backward compatibility: old single-snapshot format.
            data = parsed
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    for k, v in data.items():
        if not hasattr(props, k):
            continue
        try:
            setattr(props, k, v)
        except Exception:
            pass
    try:
        props.is_generating = False
    except Exception:
        pass
    try:
        props.last_search_state_json = json.dumps(stack) if stack else ""
    except Exception:
        props.last_search_state_json = ""
    return True


def _get_mask_selection_for_role(props, role):
    data = _safe_load_json_dict(getattr(props, "mask_selection_json", ""))
    if not isinstance(data, dict):
        return ""
    return str(data.get(str(role)) or "").strip()


def _set_mask_selection_for_role(props, role, mask_key):
    data = _safe_load_json_dict(getattr(props, "mask_selection_json", ""))
    if not isinstance(data, dict):
        data = {}
    data[str(role)] = str(mask_key or "").strip()
    try:
        props.mask_selection_json = json.dumps(data)
    except Exception:
        props.mask_selection_json = ""


def _sync_mask_defaults_from_plan(props, plan_dict):
    slots = plan_dict.get("slots") or []
    if not isinstance(slots, list):
        slots = []
    data = {}
    for slot in slots:
        if not isinstance(slot, dict):
            continue
        role = str(slot.get("role") or "").strip()
        if not role:
            continue
        data[role] = str(slot.get("mask") or "").strip()
    try:
        props.mask_selection_json = json.dumps(data)
    except Exception:
        props.mask_selection_json = ""


def _image_to_data_url(image):
    if not image:
        return ""
    data = None
    packed = getattr(image, "packed_file", None)
    if packed and getattr(packed, "data", None):
        data = packed.data
    else:
        path = str(getattr(image, "filepath", "") or "")
        if path:
            abs_path = bpy.path.abspath(path)
            if abs_path and os.path.exists(abs_path):
                try:
                    with open(abs_path, "rb") as f:
                        data = f.read()
                except Exception:
                    data = None
    if not data:
        return ""
    mime = ""
    path_for_mime = str(getattr(image, "filepath", "") or "")
    if path_for_mime:
        mime = mimetypes.guess_type(path_for_mime)[0] or ""
    if not mime:
        fmt = str(getattr(image, "file_format", "") or "").lower()
        if fmt == "jpg":
            fmt = "jpeg"
        if fmt in ("png", "jpeg", "webp", "bmp", "tif", "tiff"):
            mime = f"image/{fmt}"
        else:
            mime = "application/octet-stream"
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:{mime};base64,{b64}"


def _get_semantic_plan(props):
    plan = _safe_load_json_dict(getattr(props, "semantic_plan_json", ""))
    slots = plan.get("slots")
    if not isinstance(slots, list):
        slots = []
    return plan, slots


def _find_slot_by_role(slots, role):
    for s in slots:
        if isinstance(s, dict) and str(s.get("role") or "") == role:
            return s
    return None


def _allowed_asset_types_for_role(props, role):
    return ("MATERIAL",)


def _slot_query_rep(prompt_text, slot_dict):
    role = str(slot_dict.get("role") or "Base")
    concept = str(slot_dict.get("concept") or role)
    tags = slot_dict.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip().lower() for t in tags if str(t).strip()]
    semantic_json = {
        "tags": tags,
        "slot_count": 1,
        "slots": [
            {
                "role": role,
                "concept": concept,
                "tags": tags,
                "relation": str(slot_dict.get("relation") or "base"),
            }
        ],
    }
    return semantic_init.build_representation_from_semantic_json(prompt_text or concept, semantic_json)

def _l2_normalize_vec(v):
    if not isinstance(v, list) or not v:
        return None
    n2 = 0.0
    for x in v:
        try:
            fx = float(x)
        except Exception:
            return None
        n2 += fx * fx
    if n2 <= 1e-12:
        return [float(x) for x in v]
    n = n2 ** 0.5
    return [float(x) / n for x in v]

def _dot_safe(a, b):
    if not isinstance(a, list) or not isinstance(b, list) or not a or not b:
        return None
    if len(a) != len(b):
        return None
    s = 0.0
    for x, y in zip(a, b):
        try:
            s += float(x) * float(y)
        except Exception:
            return None
    return s

def _euclidean_safe(a, b):
    if not isinstance(a, list) or not isinstance(b, list) or not a or not b:
        return None
    if len(a) != len(b):
        return None
    s = 0.0
    for x, y in zip(a, b):
        try:
            d = float(x) - float(y)
        except Exception:
            return None
        s += d * d
    return s ** 0.5

def _minmax_norm_map(value_map, invert=False):
    if not isinstance(value_map, dict) or not value_map:
        return {}
    vals = []
    for v in value_map.values():
        try:
            vals.append(float(v))
        except Exception:
            continue
    if not vals:
        return {k: 0.0 for k in value_map.keys()}
    vmin = min(vals)
    vmax = max(vals)
    if abs(vmax - vmin) <= 1e-12:
        return {k: 0.5 for k in value_map.keys()}
    out = {}
    for k, v in value_map.items():
        try:
            x = (float(v) - vmin) / (vmax - vmin)
        except Exception:
            x = 0.0
        if x < 0.0:
            x = 0.0
        if x > 1.0:
            x = 1.0
        out[k] = (1.0 - x) if invert else x
    return out

def _clip_query_from_scored_ids(lm, scored_ids):
    if not isinstance(scored_ids, list) or not scored_ids:
        return None
    base_scores = [float(s) for s, _eid in scored_ids if isinstance(s, (int, float))]
    if not base_scores:
        return None
    min_s = min(base_scores)

    acc = None
    sum_w = 0.0
    dim = 0
    used = 0
    for s, eid in scored_ids:
        try:
            score = float(s)
        except Exception:
            continue
        entry = lm.get_entry_by_id(str(eid))
        if not entry:
            continue
        vec = entry.get("_mc_clip_vec")
        if not isinstance(vec, list) or not vec:
            continue
        if not all(isinstance(x, (int, float)) for x in vec):
            continue
        if acc is None:
            dim = len(vec)
            acc = [0.0] * dim
        if len(vec) != dim:
            continue
        w = (score - min_s) + 1e-3
        if w <= 0:
            continue
        sum_w += w
        used += 1
        for i, x in enumerate(vec):
            acc[i] += float(x) * w

    if acc is None or sum_w <= 1e-9 or used < 3:
        return None
    avg = [x / sum_w for x in acc]
    return _l2_normalize_vec(avg)

def _clip_directional_score(prev_clip, curr_clip, cand_clip):
    if not isinstance(curr_clip, list) or not isinstance(cand_clip, list) or not curr_clip or not cand_clip:
        return 0.0
    if len(curr_clip) != len(cand_clip):
        return 0.0
    sim_curr = _dot_safe(curr_clip, cand_clip)
    if sim_curr is None:
        return 0.0
    if not isinstance(prev_clip, list) or not prev_clip or len(prev_clip) != len(curr_clip):
        return float(sim_curr)

    dir_v = []
    n2 = 0.0
    for p, c in zip(prev_clip, curr_clip):
        try:
            d = float(c) - float(p)
        except Exception:
            return float(sim_curr)
        dir_v.append(d)
        n2 += d * d
    if n2 <= 1e-10:
        return float(sim_curr)
    dir_n = n2 ** 0.5

    cand_minus_curr = []
    for x, c in zip(cand_clip, curr_clip):
        cand_minus_curr.append(float(x) - float(c))
    proj = _dot_safe(cand_minus_curr, dir_v)
    if proj is None:
        return float(sim_curr)
    proj = float(proj) / (dir_n + 1e-8)

    target = [float(c) + d for c, d in zip(curr_clip, dir_v)]
    dist = _euclidean_safe(cand_clip, target)
    if dist is None:
        return float(sim_curr)
    return float(proj) - 0.35 * float(dist)

def _cosine_distance_safe(a, b):
    sim = _dot_safe(a, b)
    if sim is None:
        return None
    try:
        s = float(sim)
    except Exception:
        return None
    if s < -1.0:
        s = -1.0
    if s > 1.0:
        s = 1.0
    return 1.0 - s

def _gnn_directional_score(prev_gnn, curr_gnn, cand_gnn):
    if not isinstance(curr_gnn, list) or not isinstance(cand_gnn, list) or not curr_gnn or not cand_gnn:
        return 0.0
    if len(curr_gnn) != len(cand_gnn):
        return 0.0
    sim_curr = _dot_safe(curr_gnn, cand_gnn)
    if sim_curr is None:
        return 0.0
    if not isinstance(prev_gnn, list) or not prev_gnn or len(prev_gnn) != len(curr_gnn):
        return float(sim_curr)

    dir_v = []
    n2 = 0.0
    for p, c in zip(prev_gnn, curr_gnn):
        try:
            d = float(c) - float(p)
        except Exception:
            return float(sim_curr)
        dir_v.append(d)
        n2 += d * d
    if n2 <= 1e-10:
        return float(sim_curr)
    dir_n = n2 ** 0.5

    cand_minus_curr = []
    for x, c in zip(cand_gnn, curr_gnn):
        cand_minus_curr.append(float(x) - float(c))
    proj = _dot_safe(cand_minus_curr, dir_v)
    if proj is None:
        return float(sim_curr)
    proj = float(proj) / (dir_n + 1e-8)

    target = [float(c) + d for c, d in zip(curr_gnn, dir_v)]
    dist = _euclidean_safe(cand_gnn, target)
    if dist is None:
        return float(sim_curr)
    return float(proj) - 0.35 * float(dist)

def _structural_directional_score(prev_k, curr_k, cand_k):
    if not isinstance(curr_k, list) or not isinstance(cand_k, list) or not curr_k or not cand_k:
        return 0.0

    # Pad to 6D
    dim = 6
    def _pad(v):
        if not isinstance(v, list):
            return [0.0] * dim
        if len(v) < dim:
            return list(v) + [0.0] * (dim - len(v))
        return list(v)[:dim]

    p = _pad(prev_k) if prev_k else None
    c = _pad(curr_k)
    x = _pad(cand_k)

    if not p:
        return 0.0

    # Direction: Curr - Prev
    dir_v = [c[i] - p[i] for i in range(dim)]
    n2 = sum(d*d for d in dir_v)
    if n2 <= 1e-10:
        return 0.0
    dir_n = n2 ** 0.5

    # Projection
    cand_minus_curr = [x[i] - c[i] for i in range(dim)]
    dot_val = sum(cand_minus_curr[i] * dir_v[i] for i in range(dim))
    proj = dot_val / (dir_n + 1e-8)

    # Distance to Target (Target = Curr + Dir)
    target = [c[i] + dir_v[i] for i in range(dim)]
    dist_sq = sum((x[i] - target[i])**2 for i in range(dim))
    dist = dist_sq ** 0.5

    return proj - 0.35 * dist

def _rank_entries_for_rep(lm, rep, allowed_types, complexity_target, top_k):
    qv = list(rep.s_vector)
    scored = []
    for e in lm.index_data:
        asset_type = str(e.get("asset_type") or "MATERIAL")
        if allowed_types and asset_type not in allowed_types:
            continue
        ev = exploration_engine.entry_vector(e)
        d = semantic_init.euclidean(qv, ev)
        score = -d
        scored.append((score, str(e.get("id") or "")))
    scored.sort(key=lambda x: x[0], reverse=True)
    pre_k = max(int(top_k) * 6, 60)
    pre = scored[:pre_k]
    clip_q = _clip_query_from_scored_ids(lm, pre)
    if clip_q is not None:
        clip_w = 0.35
        rescored = []
        for base_s, eid in pre:
            entry = lm.get_entry_by_id(str(eid))
            clip_s = 0.0
            if entry:
                dval = _dot_safe(clip_q, entry.get("_mc_clip_vec"))
                if dval is not None:
                    clip_s = float(dval)
            rescored.append((float(base_s) + clip_s * clip_w, str(eid)))
        rescored.sort(key=lambda x: x[0], reverse=True)
        scored = rescored

    out = []
    for _s, eid in scored:
        if eid and eid not in out:
            out.append(eid)
        if len(out) >= max(1, int(top_k)):
            break
    return out


def _finalize_ids_for_rep_with_complexity(lm, rep, ids, complexity_target):
    qv = list(rep.s_vector)
    sem_scored = []
    id_to_entry = {}
    for eid in ids:
        entry = lm.get_entry_by_id(str(eid))
        if not entry:
            continue
        id_key = str(entry.get("id") or "")
        if not id_key:
            continue
        id_to_entry[id_key] = entry
        ev = exploration_engine.entry_vector(entry)
        d = semantic_init.euclidean(qv, ev)
        score = -d
        sem_scored.append((float(score), id_key))
    if not sem_scored:
        return []

    clip_q = _clip_query_from_scored_ids(lm, sem_scored)
    k_vecs = {}
    for _s, eid in sem_scored:
        entry = id_to_entry.get(eid)
        if not entry:
            continue
        try:
            lm.ensure_entry_complexity(entry)
        except Exception:
            pass
        kv = entry.get("k_vector")
        if not isinstance(kv, list) or not kv:
            c = float(entry.get("complexity_norm") or 0.0)
            kv = [c, 0.0, 0.0, 0.0, 0.0, 0.0]
        if len(kv) < 6:
            kv = list(kv) + [0.0] * (6 - len(kv))
        else:
            kv = list(kv)[:6]
        k_vecs[eid] = kv

    target_k = [float(complexity_target), 0.0, 0.0, 0.0, 0.0, 0.0]
    if k_vecs:
        dims = [1, 2, 4]
        for di in dims:
            vals = [float(v[di]) for v in k_vecs.values() if len(v) > di]
            if vals:
                target_k[di] = sum(vals) / float(len(vals))
    k_weights = [0.45, 0.2, 0.2, 0.0, 0.15, 0.0]

    sem_raw = {}
    clip_raw = {}
    struct_dist = {}
    for score, eid in sem_scored:
        entry = id_to_entry.get(eid)
        if not entry:
            continue
        sem_raw[eid] = float(score)
        clip_val = 0.0
        if clip_q is not None:
            dval = _dot_safe(clip_q, entry.get("_mc_clip_vec"))
            if dval is not None:
                clip_val = float(dval)
        clip_raw[eid] = clip_val
        kv = k_vecs.get(eid, [0.0] * 6)
        try:
            penalty = exploration_engine.calculate_structural_penalty(kv, target_k, weights=k_weights)
        except Exception:
            penalty = 0.0
        struct_dist[eid] = float(penalty)

    sem_norm = _minmax_norm_map(sem_raw, invert=False)
    clip_norm = _minmax_norm_map(clip_raw, invert=False)
    struct_norm = _minmax_norm_map(struct_dist, invert=True)

    rescored = []
    for _score, eid in sem_scored:
        rerank_score = (
            sem_norm.get(eid, 0.0) * 0.5
            + clip_norm.get(eid, 0.0) * 0.2
            + struct_norm.get(eid, 0.0) * 0.3
        )
        rescored.append((float(rerank_score), eid))
    rescored.sort(key=lambda x: x[0], reverse=True)
    out = []
    for _s, eid in rescored:
        if eid and eid not in out:
            out.append(eid)
    return out


def _set_candidates_for_role(props, role, ids):
    data = _safe_load_json_dict(getattr(props, "slot_candidates_json", ""))
    data[str(role)] = list(ids)
    props.slot_candidates_json = json.dumps(data)

    if getattr(props, "apply_slot_role", "Base") == role:
        props.explore_candidate_1_id = ids[0] if len(ids) > 0 else ""
        props.explore_candidate_2_id = ids[1] if len(ids) > 1 else ""
        props.explore_candidate_3_id = ids[2] if len(ids) > 2 else ""
        props.explore_candidate_4_id = ids[3] if len(ids) > 3 else ""

    pick_prop = {
        "Base": "candidate_pick_base",
        "Overlay": "candidate_pick_overlay",
        "Detail": "candidate_pick_detail",
    }.get(str(role), "")
    if pick_prop:
        try:
            # New logic: '1' is the first slot, '0' is None
            setattr(props, pick_prop, "1" if ids else "0")
        except Exception:
            pass


def _get_candidates_for_role(props, role):
    data = _safe_load_json_dict(getattr(props, "slot_candidates_json", ""))
    ids = data.get(str(role))
    if isinstance(ids, list):
        return [str(x) for x in ids]
    ids = []
    for v in (
        getattr(props, "explore_candidate_1_id", ""),
        getattr(props, "explore_candidate_2_id", ""),
        getattr(props, "explore_candidate_3_id", ""),
        getattr(props, "explore_candidate_4_id", ""),
    ):
        if v:
            ids.append(str(v))
    return ids


def _get_selection_for_role(props, role):
    data = _safe_load_json_dict(getattr(props, "slot_selection_json", ""))
    slot_data = data.get(str(role))
    if not isinstance(slot_data, dict):
        slot_data = {}
    return str(slot_data.get("prev") or ""), str(slot_data.get("curr") or "")


def _set_selection_for_role(props, role, prev_id, curr_id):
    data = _safe_load_json_dict(getattr(props, "slot_selection_json", ""))
    data[str(role)] = {"prev": prev_id or "", "curr": curr_id or ""}
    props.slot_selection_json = json.dumps(data)

def get_active_material(context):
    obj = context.active_object
    if obj and obj.type == 'MESH' and obj.active_material:
        return obj.active_material
    return None

def save_to_history(context, material, params):
    """Save the current state to history."""
    props = context.scene.mat_composer
    item = props.history.add()
    item.material_name = material.name
    item.params_json = dict_to_str(params)
    props.current_history_index = len(props.history) - 1

class MATCOMPOSER_OT_Generate(bpy.types.Operator):
    bl_idname = "matcomposer.generate_material"
    bl_label = "Search Slots"
    bl_description = "Search library candidates for each semantic slot"

    _timer = None
    _thread = None
    _phase = "search"
    _preview_pending_ids = None
    _preview_total = 0
    _preview_done = 0
    _search_started_at = 0.0
    _preview_started_at = 0.0

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        props = context.scene.mat_composer

        if self._phase == "search":
            if not (self._thread and not self._thread.is_alive()):
                return {'PASS_THROUGH'}

            result = None
            try:
                result = search_queue.get_nowait()
            except queue.Empty:
                return {'PASS_THROUGH'}

            try:
                self.handle_result(context, result)
            except Exception as e:
                self.report({'ERROR'}, f"Error handling search result: {e}")
                if props.debug_mode:
                    import traceback
                    traceback.print_exc()
                props.is_generating = False
                context.window_manager.event_timer_remove(self._timer)
                return {'FINISHED'}

            if props.debug_mode:
                elapsed = time.perf_counter() - float(self._search_started_at or time.perf_counter())
                _debug_timing(True, f"search_to_candidates={elapsed:.3f}s")

            if isinstance(result, dict) and result.get("error"):
                props.is_generating = False
                context.window_manager.event_timer_remove(self._timer)
                return {'FINISHED'}

            candidates_by_role = _safe_load_json_dict(getattr(props, "slot_candidates_json", ""))
            pending = []
            if isinstance(candidates_by_role, dict):
                for _role, ids in candidates_by_role.items():
                    if not isinstance(ids, list):
                        continue
                    for eid in ids[:4]:
                        eid = str(eid or "")
                        if eid and eid not in pending:
                            pending.append(eid)

            self._preview_pending_ids = pending
            self._preview_total = len(pending)
            self._preview_done = 0
            if self._preview_total <= 0:
                props.is_generating = False
                context.window_manager.event_timer_remove(self._timer)
                if props.debug_mode:
                    total = time.perf_counter() - float(self._search_started_at or time.perf_counter())
                    _debug_timing(True, f"search_total_no_previews={total:.3f}s")
                _tag_redraw_all()
                return {'FINISHED'}

            self._phase = "previews"
            self._preview_started_at = time.perf_counter()
            props.generation_status = f"Loading Previews (0/{self._preview_total})"
            _tag_redraw_all()
            return {'PASS_THROUGH'}

        if self._phase == "previews":
            if not self._preview_pending_ids:
                props.generation_status = "Slots Ready"
                props.is_generating = False
                context.window_manager.event_timer_remove(self._timer)
                if props.debug_mode:
                    now = time.perf_counter()
                    preview_elapsed = now - float(self._preview_started_at or now)
                    total_elapsed = now - float(self._search_started_at or now)
                    _debug_timing(
                        True,
                        f"preview_total={preview_elapsed:.3f}s count={self._preview_total} end_to_end={total_elapsed:.3f}s",
                    )
                _tag_redraw_all()
                return {'FINISHED'}

            entry_id = self._preview_pending_ids.pop(0)
            lm = library_manager.library_manager
            entry = lm.get_entry_by_id(entry_id)
            preview_t0 = time.perf_counter()
            if entry:
                lm.ensure_entry_preview_icon_id(entry)
            if props.debug_mode:
                preview_elapsed = time.perf_counter() - preview_t0
                entry_name = str(entry.get("name") or entry_id) if entry else str(entry_id)
                _debug_timing(True, f"preview role_candidate name='{entry_name}' time={preview_elapsed:.3f}s")
            self._preview_done += 1
            props.generation_status = f"Loading Previews ({self._preview_done}/{self._preview_total})"
            _tag_redraw_all()
            return {'PASS_THROUGH'}

        props.is_generating = False
        context.window_manager.event_timer_remove(self._timer)
        _tag_redraw_all()
        return {'FINISHED'}

    def execute(self, context):
        props = context.scene.mat_composer
        prompt = props.text_prompt

        if not prompt:
            self.report({'ERROR'}, "Please enter a prompt")
            return {'CANCELLED'}

        plan, slots = _get_semantic_plan(props)
        if not slots:
            self.report({'ERROR'}, "Please run Semantic Init first")
            return {'CANCELLED'}

        if props.is_generating:
            self.report({'WARNING'}, "Busy")
            return {'CANCELLED'}

        try:
            _snapshot_search_state(props)
        except Exception:
            pass

        self._phase = "search"
        self._preview_pending_ids = []
        self._preview_total = 0
        self._preview_done = 0
        self._search_started_at = time.perf_counter()
        self._preview_started_at = 0.0

        props.is_generating = True
        props.generation_status = "Searching Slots..."
        _tag_redraw_all()

        lm = library_manager.library_manager
        if not lm.index_data:
            scan_t0 = time.perf_counter()
            lm.scan_asset_libraries()
            _debug_timing(
                props.debug_mode,
                f"scan_asset_libraries={time.perf_counter() - scan_t0:.3f}s entries={len(lm.index_data)}",
            )
        else:
            _debug_timing(props.debug_mode, f"index_ready entries={len(lm.index_data)}")

        complexity_target = float(getattr(props, "search_complexity", 0.4))

        props.slot_candidates_json = ""

        slot_payload = []
        roles_seen = set()
        for s in slots:
            if not isinstance(s, dict):
                continue
            role = str(s.get("role") or "Base")
            if role in roles_seen:
                continue
            roles_seen.add(role)

            allowed = _allowed_asset_types_for_role(props, role)
            slot_payload.append((role, allowed, dict(s)))

        _debug_timing(props.debug_mode, f"search_start slots={len(slot_payload)} complexity={complexity_target:.3f}")

        self._thread = threading.Thread(
            target=self.run_search,
            args=(prompt, complexity_target, slot_payload, bool(props.debug_mode)),
        )
        self._thread.start()

        self._timer = context.window_manager.event_timer_add(0.05, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def run_search(self, prompt, complexity_target, slot_payload, debug_enabled=False):
        try:
            lm = library_manager.library_manager
            out = {}
            worker_t0 = time.perf_counter()
            for role, allowed, slot_dict in slot_payload:
                role_t0 = time.perf_counter()
                rep = _slot_query_rep(prompt, slot_dict)
                rep_t1 = time.perf_counter()
                ids = _rank_entries_for_rep(lm, rep, allowed, complexity_target, top_k=12)
                rank_t1 = time.perf_counter()
                _debug_timing(
                    debug_enabled,
                    "role='{0}' rep={1:.3f}s rank={2:.3f}s raw_candidates={3}".format(
                        role,
                        rep_t1 - role_t0,
                        rank_t1 - rep_t1,
                        len(ids),
                    ),
                )
                out[str(role)] = {"ids": ids, "rep_json": semantic_init.representation_to_json_str(rep)}
            _debug_timing(debug_enabled, f"worker_total={time.perf_counter() - worker_t0:.3f}s")
            search_queue.put(out)
        except Exception as e:
            search_queue.put({"error": str(e)})

    def handle_result(self, context, result):
        props = context.scene.mat_composer
        if isinstance(result, dict) and result.get("error"):
            self.report({'ERROR'}, str(result.get("error")))
            props.generation_status = "Search Error"
            return

        lm = library_manager.library_manager
        complexity_target = float(getattr(props, "search_complexity", 0.4))

        if not isinstance(result, dict):
            props.generation_status = "Search Error"
            return

        role_to_pick_prop = {
            "Base": "candidate_pick_base",
            "Overlay": "candidate_pick_overlay",
            "Detail": "candidate_pick_detail",
        }

        handle_t0 = time.perf_counter()
        for role, payload in result.items():
            if str(role).startswith("_"):
                continue
            if not isinstance(payload, dict):
                continue
            ids = payload.get("ids") or []
            rep_json = str(payload.get("rep_json") or "")
            rep = semantic_init.json_str_to_representation(rep_json) if rep_json else None
            if rep and isinstance(ids, list):
                finalize_t0 = time.perf_counter()
                ids = _finalize_ids_for_rep_with_complexity(lm, rep, ids, complexity_target)[:4]
                _debug_timing(
                    props.debug_mode,
                    f"role='{role}' finalize_complexity={time.perf_counter() - finalize_t0:.3f}s final_candidates={len(ids)}",
                )
            else:
                ids = [str(x) for x in ids if str(x)][:4] if isinstance(ids, list) else []
            _set_candidates_for_role(props, str(role), ids)


        props.generation_status = "Slots Ready"
        _debug_timing(props.debug_mode, f"handle_result={time.perf_counter() - handle_t0:.3f}s")
        _tag_redraw_all()


class MATCOMPOSER_OT_RevertSearchState(bpy.types.Operator):
    bl_idname = "matcomposer.revert_search_state"
    bl_label = "Revert Search"
    bl_description = "Revert to the previous search state"

    def execute(self, context):
        props = context.scene.mat_composer
        if getattr(props, "is_generating", False):
            self.report({'WARNING'}, "Cannot revert while generating")
            return {'CANCELLED'}
        ok = _restore_search_state(props)
        if not ok:
            self.report({'WARNING'}, "No previous search state")
            return {'CANCELLED'}
        _tag_redraw_all()
        return {'FINISHED'}


class MATCOMPOSER_OT_AssembleSlots(bpy.types.Operator):
    bl_idname = "matcomposer.assemble_slots"
    bl_label = "Assemble Slots"
    bl_description = "Assemble selected slot entries into a combined material"

    def execute(self, context):
        props = context.scene.mat_composer
        lm = library_manager.library_manager
        if not lm.index_data:
            lm.scan_asset_libraries()

        plan, slots = _get_semantic_plan(props)
        if not slots:
            self.report({'ERROR'}, "Please run Semantic Init first")
            return {'CANCELLED'}

        role_to_slot = {}
        for s in slots:
            if not isinstance(s, dict):
                continue
            role = str(s.get("role") or "")
            if role and role not in role_to_slot:
                role_to_slot[role] = s

        ordered_roles = ["Base", "Overlay", "Detail"]
        for r in role_to_slot.keys():
            if r not in ordered_roles:
                ordered_roles.append(r)

        applied = False
        for role in ordered_roles:
            slot = role_to_slot.get(role)
            if not slot:
                continue

            _prev, curr_id = _get_selection_for_role(props, role)
            if not curr_id:
                ids = _get_candidates_for_role(props, role)
                curr_id = ids[0] if ids else ""
                if curr_id:
                    _set_selection_for_role(props, role, "", curr_id)

            if not curr_id:
                continue

            entry = lm.get_entry_by_id(curr_id)
            if not entry:
                continue
            relation = "base" if role == "Base" else "overlay"
            slot_to_apply = dict(slot)
            slot_to_apply["mask"] = _get_mask_selection_for_role(props, role)
            ok = composition_engine.apply_library_entry_to_object_material(
                context,
                entry,
                slot_role=role,
                relation=relation,
                slot_spec=slot_to_apply,
                use_external_mapping=bool(getattr(props, "force_external_mapping", False)),
            )
            applied = applied or bool(ok)

        if not applied:
            self.report({'WARNING'}, "No slot selections to assemble")
            return {'CANCELLED'}

        props.generation_status = "Assembled"
        return {'FINISHED'}


class MATCOMPOSER_OT_SelectSlotCandidate(bpy.types.Operator):
    bl_idname = "matcomposer.select_slot_candidate"
    bl_label = "Select Candidate"
    bl_description = "Select a candidate for a slot (does not apply yet)"

    role: bpy.props.StringProperty()
    entry_id: bpy.props.StringProperty()

    @classmethod
    def description(cls, context, properties):
        entry_id = str(properties.entry_id or "")
        if not entry_id:
            return "Select this candidate"

        try:
            lm = library_manager.library_manager
            entry = lm.get_entry_by_id(entry_id)
            if not entry:
                return "Unknown entry"

            lines = []
            name = str(entry.get("name") or "Material")
            lines.append(f"Name: {name}")

            # Add structural info
            vec = entry.get("k_vector")
            if vec and len(vec) >= 6:
                lines.append("Structure:")
                lines.append(f"  NodeCount: {vec[0]:.2f}")
                lines.append(f"  Depth: {vec[1]:.2f}")
                lines.append(f"  Branching: {vec[2]:.2f}")
                lines.append(f"  Dominance: {vec[3]:.2f}")
                lines.append(f"  Procedural: {vec[4]:.2f}")
                lines.append(f"  MathRatio: {vec[5]:.2f}")

            # Add tags
            tags = entry.get("tags")
            if tags and isinstance(tags, (list, tuple)):
                t_str = ", ".join(str(t) for t in tags[:5])
                if len(tags) > 5:
                    t_str += "..."
                lines.append(f"Tags: {t_str}")

            return "\n".join(lines)
        except Exception:
            return "Select this candidate"

    def execute(self, context):
        props = context.scene.mat_composer
        role = str(self.role or props.apply_slot_role or "Base")
        entry_id = str(self.entry_id or "")
        if not entry_id:
            return {'CANCELLED'}
        try:
            _snapshot_search_state(props)
        except Exception:
            pass

        prev_id, curr_id = _get_selection_for_role(props, role)
        _set_selection_for_role(props, role, curr_id, entry_id)

        props.apply_slot_role = role
        props.prev_selected_entry_id = curr_id
        props.curr_selected_entry_id = entry_id
        props.generation_status = "Selected"
        return {'FINISHED'}


class MATCOMPOSER_OT_SelectMask(bpy.types.Operator):
    bl_idname = "matcomposer.select_mask"
    bl_label = "Select Mask"
    bl_description = "Select the mask override for a slot"

    role: bpy.props.StringProperty()
    mask_key: bpy.props.StringProperty()

    def execute(self, context):
        props = context.scene.mat_composer
        role = str(self.role or "")
        if not role:
            return {'CANCELLED'}
        try:
            _snapshot_search_state(props)
        except Exception:
            pass
        mask_key = str(self.mask_key or "").strip()
        _set_mask_selection_for_role(props, role, mask_key)
        props.generation_status = "Mask Selected"
        _tag_redraw_all()
        return {'FINISHED'}


class MATCOMPOSER_OT_OpenMaskPicker(bpy.types.Operator):
    bl_idname = "matcomposer.open_mask_picker"
    bl_label = "Choose Mask"
    bl_description = "Open the mask picker"

    role: bpy.props.StringProperty()

    def invoke(self, context, event):
        return context.window_manager.invoke_popup(self, width=520)

    def draw(self, context):
        from . import ui as ui_mod

        layout = self.layout
        props = context.scene.mat_composer
        role = str(self.role or "")
        current = ui_mod._get_mask_selection_for_role(props, role, slot=None)
        items = ui_mod._mask_items_for_ui()
        flow = layout.grid_flow(columns=3, even_columns=True, even_rows=True, align=True)
        for item in items:
            col = flow.column(align=True)
            icon_id = int(item.get("icon_id") or 0)
            if icon_id > 0:
                col.template_icon(icon_value=icon_id, scale=6.0)
            else:
                placeholder = col.column(align=True)
                placeholder.scale_y = 4.0
                placeholder.label(text="", icon='TEXTURE')
            label = str(item.get("label") or "")
            button_text = label if len(label) <= 16 else (label[:15] + "…")
            op = col.operator(
                "matcomposer.select_mask",
                text=button_text,
                depress=(str(item.get("key") or "") == current),
            )
            op.role = role
            op.mask_key = str(item.get("key") or "")
            if bool(getattr(props, "debug_mode", False)):
                dbg = ui_mod._mask_debug_info(item.get("key") or "")
                path = str(dbg.get("path") or "")
                if path:
                    col.label(text=os.path.basename(path))
                col.label(text=f"I:{int(dbg.get('image_icon_id') or 0)}")
                err = str(dbg.get("error") or "").strip()
                if err:
                    col.label(text="ERR", icon='ERROR')

    def execute(self, context):
        role = str(self.role or "").strip()
        if not role:
            return {'CANCELLED'}
        return context.window_manager.invoke_popup(self, width=520)


class MATCOMPOSER_OT_LoadCandidatePreviews(bpy.types.Operator):
    bl_idname = "matcomposer.load_candidate_previews"
    bl_label = "Load Previews"
    bl_description = "Load preview thumbnails for visible slot candidates"

    _timer = None
    _pending_ids = None
    _total = 0
    _done = 0

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}

        props = context.scene.mat_composer
        if not self._pending_ids:
            props.is_generating = False
            props.generation_status = "Previews Ready"
            context.window_manager.event_timer_remove(self._timer)
            return {'FINISHED'}

        entry_id = self._pending_ids.pop(0)
        lm = library_manager.library_manager
        entry = lm.get_entry_by_id(entry_id)
        if entry:
            lm.ensure_entry_preview_icon_id(entry)
            # Ensure structural data is available for badges
            try:
                lm.ensure_entry_complexity(entry)
            except Exception:
                pass

        self._done += 1
        props.generation_status = f"Loading Previews ({self._done}/{self._total})"
        return {'PASS_THROUGH'}

    def execute(self, context):
        props = context.scene.mat_composer
        lm = library_manager.library_manager
        if not lm.index_data:
            lm.scan_asset_libraries()

        if props.is_generating:
            self.report({'WARNING'}, "Busy")
            return {'CANCELLED'}

        plan, slots = _get_semantic_plan(props)
        if not slots:
            self.report({'ERROR'}, "Please run Semantic Init first")
            return {'CANCELLED'}

        candidates_by_role = _safe_load_json_dict(getattr(props, "slot_candidates_json", ""))
        pending = []
        roles_seen = set()
        for s in slots:
            if not isinstance(s, dict):
                continue
            role = str(s.get("role") or "")
            if not role or role in roles_seen:
                continue
            roles_seen.add(role)
            ids = candidates_by_role.get(role)
            if not isinstance(ids, list):
                continue
            for eid in ids[:4]:
                eid = str(eid or "")
                if eid and eid not in pending:
                    pending.append(eid)

        if not pending:
            self.report({'WARNING'}, "No candidates to preview")
            return {'CANCELLED'}

        self._pending_ids = pending
        self._total = len(pending)
        self._done = 0

        props.is_generating = True
        props.generation_status = f"Loading Previews (0/{self._total})"

        self._timer = context.window_manager.event_timer_add(0.01, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}


class MATCOMPOSER_OT_SemanticInit(bpy.types.Operator):
    bl_idname = "matcomposer.semantic_init"
    bl_label = "Semantic Init"
    bl_description = "Normalize prompt into tags and slot plan"

    _timer = None
    _thread = None

    def modal(self, context, event):
        if event.type == 'TIMER':
            if self._thread and not self._thread.is_alive():
                try:
                    result = semantic_queue.get_nowait()
                    self.handle_result(context, result)
                except queue.Empty:
                    pass
                except Exception as e:
                    self.report({'ERROR'}, f"Error handling semantic result: {e}")
                    if context.scene.mat_composer.debug_mode:
                        import traceback
                        traceback.print_exc()
                finally:
                    context.scene.mat_composer.is_generating = False
                    context.window_manager.event_timer_remove(self._timer)
                    return {'FINISHED'}
        return {'PASS_THROUGH'}

    def execute(self, context):
        props = context.scene.mat_composer
        if props.is_generating:
            self.report({'WARNING'}, "Busy")
            return {'CANCELLED'}

        api_key = props.api_key
        prompt = props.text_prompt
        model = props.model_selection
        debug = props.debug_mode
        image_data_url = _image_to_data_url(props.image_input)

        # Auto-switch model logic
        if image_data_url:
            model = "qwen-vl-plus"
        else:
            model = "qwen-plus"

        print(f"[MatComposer] Auto-switching model to: {model}")

        if not api_key:
            self.report({'ERROR'}, "Please enter a DashScope API Key")
            return {'CANCELLED'}
        if not prompt:
            self.report({'ERROR'}, "Please enter a prompt")
            return {'CANCELLED'}

        props.is_generating = True
        props.generation_status = "Semantic Init (LLM)..."

        self._thread = threading.Thread(target=self.run_llm_semantic, args=(api_key, model, prompt, image_data_url, debug))
        self._thread.start()

        self._timer = context.window_manager.event_timer_add(0.5, window=context.window)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def run_llm_semantic(self, api_key, model, prompt, image_data_url, debug):
        try:
            client = LLMClient(api_key, model)
            response = client.generate_semantic_init(prompt, image_data_url=image_data_url, debug=debug)
            semantic_queue.put(response)
        except Exception as e:
            if debug:
                print(f"[MatComposer DEBUG] Semantic Thread Error: {str(e)}")
            semantic_queue.put({"error": str(e)})

    def handle_result(self, context, result):
        props = context.scene.mat_composer
        if "error" in result:
            self.report({'ERROR'}, result["error"])
            props.generation_status = "Semantic Error"
            return

        slot_count = result.get("slot_count")
        try:
            slot_count = semantic_init.clamp_slot_count(int(slot_count)) if slot_count is not None else None
        except Exception:
            slot_count = None

        slots = result.get("slots")
        if not isinstance(slots, list):
            slots = []
        if slot_count is None:
            slot_count = semantic_init.clamp_slot_count(len(slots) if slots else 1)
        result["slot_count"] = slot_count
        result["slots"] = (slots or [])[:slot_count]

        props.semantic_plan_json = dict_to_str(result)
        _sync_mask_defaults_from_plan(props, result)

        mat = get_active_material(context)
        k = semantic_init.build_k_topology_from_node_tree(mat.node_tree if mat and mat.use_nodes else None)
        rep = semantic_init.build_representation_from_semantic_json(props.text_prompt, result, k_topology=k)
        props.semantic_repr_json = semantic_init.representation_to_json_str(rep)

        props.generation_status = "Semantic Ready"


class MATCOMPOSER_OT_ExploreLocalLibrary(bpy.types.Operator):
    bl_idname = "matcomposer.explore_local"
    bl_label = "Explore Local"
    bl_description = "Find nearest neighbors in library"

    def execute(self, context):
        props = context.scene.mat_composer
        lm = library_manager.library_manager
        if not lm.index_data:
            lm.scan_asset_libraries()

        _plan, slots = _get_semantic_plan(props)
        role = props.apply_slot_role
        slot = _find_slot_by_role(slots, role)
        if not slot:
            self.report({'ERROR'}, "No slot found. Run Semantic Init.")
            return {'CANCELLED'}

        rep = _slot_query_rep(props.text_prompt, slot)
        complexity_target = float(getattr(props, "search_complexity", 0.4))
        allowed = _allowed_asset_types_for_role(props, role)
        ids = _rank_entries_for_rep(lm, rep, allowed, complexity_target, top_k=18)
        ids = _finalize_ids_for_rep_with_complexity(lm, rep, ids, complexity_target)[:18]
        _set_candidates_for_role(props, role, ids)

        props.generation_status = "Explore Ready"
        return {'FINISHED'}


class MATCOMPOSER_OT_ExploreAuto(bpy.types.Operator):
    bl_idname = "matcomposer.explore_auto"
    bl_label = "Explore"
    bl_description = "Explore local first, then directional when history exists"

    role: bpy.props.StringProperty()

    def execute(self, context):
        props = context.scene.mat_composer
        lm = library_manager.library_manager
        if not lm.index_data:
            lm.scan_asset_libraries()
        try:
            lm.attach_gnn_vectors_to_entries()
        except Exception:
            pass

        plan, slots = _get_semantic_plan(props)
        role = self.role if self.role else props.apply_slot_role
        slot = _find_slot_by_role(slots, role)
        if not slot:
            self.report({'ERROR'}, "No slot found. Run Semantic Init.")
            return {'CANCELLED'}
        try:
            _snapshot_search_state(props)
        except Exception:
            pass

        # Update global role property for consistency/UI feedback
        props.apply_slot_role = role

        prev_id, curr_id = _get_selection_for_role(props, role)

        # Determine Exploration Mode
        # "Alternating" Logic: Local -> Directional -> Local -> ...
        last_mode = getattr(props, "last_exploration_mode", "LOCAL")
        mode = "LOCAL"

        if prev_id and curr_id and last_mode == "LOCAL":
            # If we have a vector (prev->curr) and just finished a Local step (selection),
            # we switch to Directional.
            mode = "DIRECTIONAL"

        # Verify Directional viability
        prev_entry = None
        curr_entry = None
        if mode == "DIRECTIONAL":
            prev_entry = lm.get_entry_by_id(prev_id)
            curr_entry = lm.get_entry_by_id(curr_id)
            if not prev_entry or not curr_entry:
                mode = "LOCAL"

        if mode == "LOCAL":
            props.last_exploration_mode = "LOCAL"
            allowed = _allowed_asset_types_for_role(props, role)
            complexity_target = float(getattr(props, "search_complexity", 0.4))

            # Use Current Selection as query center if available
            rep = None
            if curr_id:
                curr_entry = lm.get_entry_by_id(curr_id)
                if curr_entry:
                    rep = exploration_engine.representation_from_entry(curr_entry)

            # Fallback to Text Prompt
            if not rep:
                rep = _slot_query_rep(props.text_prompt, slot)

            ids = _rank_entries_for_rep(lm, rep, allowed, complexity_target, top_k=18)
            ids = _finalize_ids_for_rep_with_complexity(lm, rep, ids, complexity_target)[:18]
            _set_candidates_for_role(props, role, ids)
            props.generation_status = "Explore Ready (Local)"
            return {'FINISHED'}

        # Directional Mode
        props.last_exploration_mode = "DIRECTIONAL"
        expl_mode = getattr(props, "exploration_mode", "JOINT")

        prompt_rep = semantic_init.build_representation_from_semantic_json(
            props.text_prompt,
            plan if isinstance(plan, dict) else {"tags": [], "slot_count": 1, "slots": []},
        )

        prev_base = exploration_engine.representation_from_entry(prev_entry)
        curr_base = exploration_engine.representation_from_entry(curr_entry)

        prev_rep = semantic_init.MaterialRepresentation(
            raw_text=prev_base.raw_text,
            tags=prompt_rep.tags,
            slots=prompt_rep.slots,
            s_vector=prev_base.s_vector,
            k_topology={},
        )
        curr_rep = semantic_init.MaterialRepresentation(
            raw_text=curr_base.raw_text,
            tags=prompt_rep.tags,
            slots=prompt_rep.slots,
            s_vector=curr_base.s_vector,
            k_topology={},
        )

        locked = []
        if props.lock_base_slot:
            locked.append("Base")
        if props.lock_overlay_slot:
            locked.append("Overlay")
        if props.lock_detail_slot:
            locked.append("Detail")

        allowed = _allowed_asset_types_for_role(props, role)

        # Base Candidate Retrieval
        candidates = []
        if expl_mode == 'LOCK_SEMANTICS':
             # Lock Semantics: Use Local Exploration (Semantic Neighbors of Curr)
             candidates = exploration_engine.local_exploration(
                curr_rep,
                lm.index_data,
                top_k=60,
                allowed_asset_types=allowed
            )
        else:
             # JOINT or LOCK_STRUCTURE: Use Directional Exploration (Semantic Direction)
             candidates = exploration_engine.directional_exploration(
                prev_rep,
                curr_rep,
                lm.index_data,
                top_k=60,
                locked_roles=tuple(locked) if locked else None,
                allowed_asset_types=allowed,
            )

        complexity_target = float(getattr(props, "search_complexity", 0.4))
        shortlist = []
        for c in candidates:
            eid = str(c.entry_id or "")
            if not eid or eid in shortlist:
                continue
            shortlist.append(eid)
            if len(shortlist) >= 30:
                break

        prev_clip = prev_entry.get("_mc_clip_vec") if isinstance(prev_entry, dict) else None
        curr_clip = curr_entry.get("_mc_clip_vec") if isinstance(curr_entry, dict) else None
        prev_gnn = prev_entry.get("_mc_gnn_vec") if isinstance(prev_entry, dict) else None
        curr_gnn = curr_entry.get("_mc_gnn_vec") if isinstance(curr_entry, dict) else None

        # Pre-fetch structural vectors
        try:
             lm.ensure_entry_complexity(prev_entry)
             lm.ensure_entry_complexity(curr_entry)
        except Exception:
             pass
        prev_k = prev_entry.get("k_vector")
        curr_k = curr_entry.get("k_vector")

        base_raw = {}
        clip_raw = {}
        gnn_raw = {}
        struct_raw = {}
        k_dist_raw = {}
        g_dist_raw = {}
        for eid in shortlist:
            e = lm.get_entry_by_id(eid)
            if not e:
                continue
            base_score = 0.0
            for c in candidates:
                if str(c.entry_id) == eid:
                    base_score = float(c.score)
                    break
            clip_score = 0.0
            try:
                clip_score = _clip_directional_score(prev_clip, curr_clip, e.get("_mc_clip_vec"))
            except Exception:
                pass
            gnn_score = 0.0
            try:
                gnn_score = _gnn_directional_score(prev_gnn, curr_gnn, e.get("_mc_gnn_vec"))
            except Exception:
                pass
            struct_score = 0.0
            try:
                _ = lm.ensure_entry_complexity(e)
                struct_score = _structural_directional_score(prev_k, curr_k, e.get("k_vector"))
            except Exception:
                pass

            k_dist = 0.0
            ek = e.get("k_vector")
            if curr_k and ek:
                k_dist = _euclidean_safe(curr_k, ek) or 0.0
            g_dist = 0.0
            try:
                dval = _cosine_distance_safe(curr_gnn, e.get("_mc_gnn_vec"))
                if dval is not None:
                    g_dist = float(dval)
            except Exception:
                pass

            base_raw[eid] = float(base_score)
            clip_raw[eid] = float(clip_score)
            gnn_raw[eid] = float(gnn_score)
            struct_raw[eid] = float(struct_score)
            k_dist_raw[eid] = float(k_dist)
            g_dist_raw[eid] = float(g_dist)

        base_norm = _minmax_norm_map(base_raw, invert=False)
        clip_norm = _minmax_norm_map(clip_raw, invert=False)
        gnn_norm = _minmax_norm_map(gnn_raw, invert=False)
        struct_norm = _minmax_norm_map(struct_raw, invert=False)
        k_compat_norm = _minmax_norm_map(k_dist_raw, invert=True)
        g_compat_norm = _minmax_norm_map(g_dist_raw, invert=True)

        rescored = []
        for eid in shortlist:
            if eid not in base_norm:
                continue
            if expl_mode == 'LOCK_SEMANTICS':
                final_score = (
                    base_norm.get(eid, 0.0) * 0.45
                    + struct_norm.get(eid, 0.0) * 0.30
                    + gnn_norm.get(eid, 0.0) * 0.25
                )
            elif expl_mode == 'LOCK_STRUCTURE':
                final_score = (
                    base_norm.get(eid, 0.0) * 0.60
                    + k_compat_norm.get(eid, 0.0) * 0.25
                    + g_compat_norm.get(eid, 0.0) * 0.15
                )
            else:
                final_score = (
                    base_norm.get(eid, 0.0) * 0.40
                    + clip_norm.get(eid, 0.0) * 0.20
                    + struct_norm.get(eid, 0.0) * 0.20
                    + gnn_norm.get(eid, 0.0) * 0.20
                )
            rescored.append((float(final_score), eid))

        rescored.sort(key=lambda x: x[0], reverse=True)
        top_ids = [eid for _, eid in rescored[:18]]

        _set_candidates_for_role(props, role, top_ids)

        status_map = {
            'JOINT': 'Joint',
            'LOCK_SEMANTICS': 'Lock Sem',
            'LOCK_STRUCTURE': 'Lock Str'
        }
        props.generation_status = f"Explore Ready ({status_map.get(expl_mode, 'Dir')})"
        return {'FINISHED'}


class MATCOMPOSER_OT_ExploreDirectionalLibrary(bpy.types.Operator):
    bl_idname = "matcomposer.explore_directional"
    bl_label = "Explore Direction"
    bl_description = "Extrapolate along selection trajectory"

    def execute(self, context):
        props = context.scene.mat_composer
        lm = library_manager.library_manager
        if not lm.index_data:
            lm.scan_asset_libraries()
        try:
            lm.attach_gnn_vectors_to_entries()
        except Exception:
            pass

        role = props.apply_slot_role
        prev_id, curr_id = _get_selection_for_role(props, role)
        if not prev_id or not curr_id:
            self.report({'WARNING'}, "Need two selections for directional exploration")
            return {'CANCELLED'}

        prev_entry = lm.get_entry_by_id(prev_id)
        curr_entry = lm.get_entry_by_id(curr_id)
        if not prev_entry or not curr_entry:
            self.report({'ERROR'}, "Selection not found in library")
            return {'CANCELLED'}

        plan, slots = _get_semantic_plan(props)
        prompt_rep = semantic_init.build_representation_from_semantic_json(props.text_prompt, plan if isinstance(plan, dict) else {"tags": [], "slot_count": 1, "slots": []})

        prev_base = exploration_engine.representation_from_entry(prev_entry)
        curr_base = exploration_engine.representation_from_entry(curr_entry)

        prev_rep = semantic_init.MaterialRepresentation(
            raw_text=prev_base.raw_text,
            tags=prompt_rep.tags,
            slots=prompt_rep.slots,
            s_vector=prev_base.s_vector,
            k_topology={},
        )
        curr_rep = semantic_init.MaterialRepresentation(
            raw_text=curr_base.raw_text,
            tags=prompt_rep.tags,
            slots=prompt_rep.slots,
            s_vector=curr_base.s_vector,
            k_topology={},
        )

        locked = []
        if props.lock_base_slot:
            locked.append("Base")
        if props.lock_overlay_slot:
            locked.append("Overlay")
        if props.lock_detail_slot:
            locked.append("Detail")

        allowed = _allowed_asset_types_for_role(props, role)

        source_index = lm.index_data

        candidates = exploration_engine.directional_exploration(
            prev_rep,
            curr_rep,
            source_index,
            top_k=60,
            locked_roles=tuple(locked) if locked else None,
            allowed_asset_types=allowed,
        )

        complexity_target = float(getattr(props, "search_complexity", 0.4))
        shortlist = []
        for c in candidates:
            eid = str(c.entry_id or "")
            if not eid or eid in shortlist:
                continue
            shortlist.append(eid)
            if len(shortlist) >= 30:
                break

        prev_clip = prev_entry.get("_mc_clip_vec") if isinstance(prev_entry, dict) else None
        curr_clip = curr_entry.get("_mc_clip_vec") if isinstance(curr_entry, dict) else None
        clip_w = 0.25
        prev_gnn = prev_entry.get("_mc_gnn_vec") if isinstance(prev_entry, dict) else None
        curr_gnn = curr_entry.get("_mc_gnn_vec") if isinstance(curr_entry, dict) else None
        try:
            lm.ensure_entry_complexity(prev_entry)
            lm.ensure_entry_complexity(curr_entry)
        except Exception:
            pass
        prev_k = prev_entry.get("k_vector")
        curr_k = curr_entry.get("k_vector")

        rescored = []
        for eid in shortlist:
            e = lm.get_entry_by_id(eid)
            if not e:
                continue
            base_score = 0.0
            for c in candidates:
                if str(c.entry_id) == eid:
                    base_score = float(c.score)
                    break
            score = base_score
            try:
                score += _clip_directional_score(prev_clip, curr_clip, e.get("_mc_clip_vec")) * clip_w
            except Exception:
                pass
            try:
                score += _gnn_directional_score(prev_gnn, curr_gnn, e.get("_mc_gnn_vec")) * 0.35
            except Exception:
                pass
            try:
                _ = lm.ensure_entry_complexity(e)
                score += _structural_directional_score(prev_k, curr_k, e.get("k_vector")) * 0.35
            except Exception:
                pass
            try:
                comp = lm.ensure_entry_complexity(e)
                score -= abs(float(comp) - float(complexity_target)) * 0.65
            except Exception:
                pass
            rescored.append((score, eid))
        rescored.sort(key=lambda x: x[0], reverse=True)
        top_ids = [eid for _s, eid in rescored[:4] if eid]

        _set_candidates_for_role(props, role, top_ids)

        props.generation_status = "Explore Ready"
        return {'FINISHED'}


class MATCOMPOSER_OT_ApplyExploreCandidate(bpy.types.Operator):
    bl_idname = "matcomposer.apply_explore_candidate"
    bl_label = "Apply Candidate"
    bl_description = "Apply a library candidate to current material"

    candidate_index: bpy.props.IntProperty()

    def execute(self, context):
        props = context.scene.mat_composer
        lm = library_manager.library_manager
        if not lm.index_data:
            lm.scan_asset_libraries()

        entry_id = ""
        if self.candidate_index == 1:
            entry_id = props.explore_candidate_1_id
        elif self.candidate_index == 2:
            entry_id = props.explore_candidate_2_id
        elif self.candidate_index == 3:
            entry_id = props.explore_candidate_3_id
        elif self.candidate_index == 4:
            entry_id = props.explore_candidate_4_id

        if not entry_id:
            return {'CANCELLED'}

        entry = lm.get_entry_by_id(entry_id)
        if not entry:
            self.report({'ERROR'}, "Candidate not found")
            return {'CANCELLED'}

        role = props.apply_slot_role
        prev_id, curr_id = _get_selection_for_role(props, role)
        _set_selection_for_role(props, role, curr_id, entry_id)
        props.prev_selected_entry_id = curr_id
        props.curr_selected_entry_id = entry_id
        props.generation_status = "Selected"
        return {'FINISHED'}

class MATCOMPOSER_OT_ScanLibrary(bpy.types.Operator):
    bl_idname = "matcomposer.scan_library"
    bl_label = "Scan Asset Libraries"
    bl_description = "Scan all registered Blender Asset Libraries for materials"

    def execute(self, context):
        lm = library_manager.library_manager
        count = lm.scan_asset_libraries()

        if count > 0:
            self.report({'INFO'}, f"Scanned {count} materials from MyMaterial.")
        else:
            self.report({'WARNING'}, "No materials found in MyMaterial.")

        return {'FINISHED'}


class MATCOMPOSER_OT_GenerateVariants(bpy.types.Operator):
    bl_idname = "matcomposer.generate_variants"
    bl_label = "Generate Variants"
    bl_description = "Generate 4 variations of the current material"

    def execute(self, context):
        mat = get_active_material(context)
        if not mat or not mat.use_nodes:
            self.report({'ERROR'}, "No active material found")
            return {'CANCELLED'}

        props = context.scene.mat_composer

        # 1. Extract current parameters
        base_params = graph_builder.get_node_parameters(mat.node_tree)

        # 2. Generate 4 variants using noise
        # We store them in the props as JSON strings
        props.variant_1_params = dict_to_str(math_utils.apply_noise(base_params, intensity=0.05))
        props.variant_2_params = dict_to_str(math_utils.apply_noise(base_params, intensity=0.10))
        props.variant_3_params = dict_to_str(math_utils.apply_noise(base_params, intensity=0.15))
        props.variant_4_params = dict_to_str(math_utils.apply_noise(base_params, intensity=0.20))

        self.report({'INFO'}, "Variants Generated")
        return {'FINISHED'}

class MATCOMPOSER_OT_ApplyVariant(bpy.types.Operator):
    bl_idname = "matcomposer.apply_variant"
    bl_label = "Apply Variant"
    bl_description = "Apply this variant to the material"

    variant_index: bpy.props.IntProperty()

    def execute(self, context):
        mat = get_active_material(context)
        if not mat:
            return {'CANCELLED'}

        props = context.scene.mat_composer

        # Get params from storage
        param_str = ""
        if self.variant_index == 1: param_str = props.variant_1_params
        elif self.variant_index == 2: param_str = props.variant_2_params
        elif self.variant_index == 3: param_str = props.variant_3_params
        elif self.variant_index == 4: param_str = props.variant_4_params

        if not param_str:
            return {'CANCELLED'}

        params = str_to_dict(param_str)

        # Apply to graph
        graph_builder.apply_parameters(mat.node_tree, params)

        # Save to history
        save_to_history(context, mat, params)

        return {'FINISHED'}

class MATCOMPOSER_OT_Evolve(bpy.types.Operator):
    bl_idname = "matcomposer.evolve"
    bl_label = "Evolve / Extrapolate"
    bl_description = "Evolve material based on selection history"

    def execute(self, context):
        props = context.scene.mat_composer
        history = props.history
        curr_idx = props.current_history_index

        # Need at least 2 items: Current and Previous
        if curr_idx < 1 or len(history) < 2:
            self.report({'WARNING'}, "Need at least 2 history steps to evolve")
            return {'CANCELLED'}

        # Get Previous and Current
        prev_item = history[curr_idx - 1]
        curr_item = history[curr_idx]

        prev_params = str_to_dict(prev_item.params_json)
        curr_params = str_to_dict(curr_item.params_json)

        # Calculate Delta (Current - Previous)
        delta = math_utils.calculate_difference(prev_params, curr_params)

        # Extrapolate (Current + Delta * 1.5)
        new_params = math_utils.extrapolate(curr_params, delta, factor=1.5)

        # Apply
        mat = get_active_material(context)
        if mat:
            graph_builder.apply_parameters(mat.node_tree, new_params)
            save_to_history(context, mat, new_params)

        self.report({'INFO'}, "Material Evolved")
        return {'FINISHED'}

classes = [
    MATCOMPOSER_OT_Generate,
    MATCOMPOSER_OT_RevertSearchState,
    MATCOMPOSER_OT_AssembleSlots,
    MATCOMPOSER_OT_SelectSlotCandidate,
    MATCOMPOSER_OT_SelectMask,
    MATCOMPOSER_OT_OpenMaskPicker,
    MATCOMPOSER_OT_LoadCandidatePreviews,
    MATCOMPOSER_OT_ScanLibrary,
    MATCOMPOSER_OT_GenerateVariants,
    MATCOMPOSER_OT_ApplyVariant,
    MATCOMPOSER_OT_Evolve,
    MATCOMPOSER_OT_SemanticInit,
    MATCOMPOSER_OT_ExploreAuto,
    MATCOMPOSER_OT_ExploreLocalLibrary,
    MATCOMPOSER_OT_ExploreDirectionalLibrary,
    MATCOMPOSER_OT_ApplyExploreCandidate,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
