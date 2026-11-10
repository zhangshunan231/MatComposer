# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

import bpy
import json
import os
from .utils import library_manager

_MASK_UI_IMAGE_CACHE = {}
_MASK_UI_DEBUG = {}


def _repo_root_dir():
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__)))
    except Exception:
        return os.path.abspath(os.getcwd())


def _masks_dir():
    return os.path.join(_repo_root_dir(), "masks")


def _mask_preview_path(mask_key):
    root = _masks_dir()
    for ext in (".jpg", ".png", ".jpeg", ".webp"):
        path = os.path.join(root, f"{mask_key}{ext}")
        if os.path.exists(path):
            return path
    return ""


def _mask_keys():
    out = []
    root = _masks_dir()
    try:
        for fn in os.listdir(root):
            if not str(fn).lower().endswith(".blend"):
                continue
            key = os.path.splitext(str(fn))[0].strip()
            if key and key not in out:
                out.append(key)
    except Exception:
        return []
    out.sort()
    return out


def _mask_items_for_ui():
    items = [{"key": "", "label": "No Mask", "icon_id": 0}]
    for key in _mask_keys():
        items.append({"key": key, "label": key, "icon_id": _load_mask_preview_icon(key)})
    return items


def _mask_image_cache_key(mask_key):
    return f"_mc_mask_preview__{mask_key}"


def _load_mask_preview_icon(mask_key):
    key = str(mask_key or "").strip()
    if not key:
        return 0
    dbg = {"path": "", "image_icon_id": 0, "error": ""}
    path = _mask_preview_path(key)
    dbg["path"] = path
    if not path:
        dbg["error"] = "preview file not found"
        _MASK_UI_DEBUG[key] = dbg
        return 0

    img = _MASK_UI_IMAGE_CACHE.get(key)
    img_name = str(getattr(img, "name", "") or "")
    if img and img_name and bpy.data.images.get(img_name) is not None:
        try:
            img.preview_ensure()
            prev = img.preview
            icon_id = int(getattr(prev, "icon_id", 0) or 0) if prev else 0
            dbg["image_icon_id"] = icon_id
            if icon_id > 0:
                _MASK_UI_DEBUG[key] = dbg
                return icon_id
        except Exception as e:
            dbg["error"] = f"image-cache: {e}"

    try:
        img = bpy.data.images.load(path, check_existing=True)
    except Exception as e:
        dbg["error"] = f"image-load: {e}"
        _MASK_UI_DEBUG[key] = dbg
        return 0

    try:
        img.name = _mask_image_cache_key(key)
    except Exception:
        pass

    try:
        img.preview_ensure()
        prev = img.preview
        icon_id = int(getattr(prev, "icon_id", 0) or 0) if prev else 0
        dbg["image_icon_id"] = icon_id
    except Exception as e:
        dbg["error"] = f"image-preview: {e}"
        icon_id = 0
    _MASK_UI_IMAGE_CACHE[key] = img
    _MASK_UI_DEBUG[key] = dbg
    return int(icon_id or 0)


def _mask_debug_info(mask_key):
    key = str(mask_key or "").strip()
    if not key:
        return {"path": "", "image_icon_id": 0, "error": ""}
    return dict(_MASK_UI_DEBUG.get(key) or {})


def _get_mask_selection_for_role(props, role, slot=None):
    try:
        data = json.loads(getattr(props, "mask_selection_json", "") or "")
    except Exception:
        data = {}
    if isinstance(data, dict):
        val = str(data.get(str(role)) or "").strip()
        if val:
            return val
    if isinstance(slot, dict):
        return str(slot.get("mask") or "").strip()
    return ""


def _clamp01(v):
    try:
        x = float(v)
    except Exception:
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _bar(value, width=10):
    x = _clamp01(value)
    n = max(1, int(width))
    fill = int(round(x * n))
    if fill < 0:
        fill = 0
    if fill > n:
        fill = n
    return "■" * fill + "·" * (n - fill)


def _mini_blocks(vec, dims=(0, 1, 2, 4)):
    blocks = "▁▂▃▄▅▆▇█"
    out = []
    for i in dims:
        v = 0.0
        if isinstance(vec, list) and len(vec) > i:
            v = _clamp01(vec[i])
        idx = int(round(v * (len(blocks) - 1)))
        if idx < 0:
            idx = 0
        if idx >= len(blocks):
            idx = len(blocks) - 1
        out.append(blocks[idx])
    return "".join(out)


def _entry_struct_data(entry, lm):
    if not isinstance(entry, dict):
        return None
    try:
        lm.ensure_entry_complexity(entry)
    except Exception:
        pass
    vec = entry.get("k_vector")
    if not isinstance(vec, list) or len(vec) < 6:
        return None
    vec = [float(x) for x in vec[:6]]
    complexity = _clamp01(entry.get("complexity_norm", vec[0]))
    return {"vec": vec, "complexity": complexity}


class MATCOMPOSER_PT_Panel(bpy.types.Panel):
    bl_label = "MatComposer"
    bl_idname = "MATCOMPOSER_PT_Panel"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "MatComposer"

    def draw(self, context):
        layout = self.layout
        scene = context.scene
        props = scene.mat_composer
        has_prompt = bool(props.text_prompt)
        has_api_key = bool(props.api_key)
        can_call_llm = (not props.is_generating) and has_prompt and has_api_key
        obj = context.active_object
        has_active_material = bool(obj and getattr(obj, "active_material", None))
        library_ready = bool(library_manager.library_manager.index_data)

        # API Key
        layout.prop(props, "api_key")

        # Model Selection (Auto-switched, hidden from UI)
        # layout.prop(props, "model_selection")

        # Debug Mode
        layout.prop(props, "debug_mode")

        # Asset Libraries
        layout.label(text="Material Library:")
        layout.operator("matcomposer.scan_library", text="Scan Asset Libraries", icon='ASSET_MANAGER')

        layout.separator()

        # Prompt
        layout.label(text="Description:")
        layout.prop(props, "text_prompt", text="")
        layout.prop(props, "image_input", text="Image")
        layout.prop(props, "search_complexity")
        row = layout.row()
        row.enabled = can_call_llm
        row.operator("matcomposer.semantic_init", icon='OUTLINER_OB_FONT')

        if props.semantic_plan_json:
            box = layout.box()
            box.label(text="Semantic Init Result:")
            try:
                data = json.loads(props.semantic_plan_json)
            except Exception:
                data = None

            if isinstance(data, dict):
                tags = data.get("tags") or []
                if isinstance(tags, list) and tags:
                    tags_preview = ", ".join(str(t) for t in tags[:16])
                    if len(tags) > 16:
                        tags_preview += " ..."
                    box.label(text=f"Tags: {tags_preview}")

                slot_count = data.get("slot_count")
                if slot_count is not None:
                    box.label(text=f"Slots: {slot_count}")

                slots = data.get("slots") or []
                if isinstance(slots, list) and slots:
                    for i, s in enumerate(slots[:3], start=1):
                        if not isinstance(s, dict):
                            continue
                        role = str(s.get("role") or "")
                        concept = str(s.get("concept") or "")
                        relation = str(s.get("relation") or "")
                        header = f"{i}. {role}"
                        if concept:
                            header += f" / {concept}"
                        if relation:
                            header += f" ({relation})"
                        box.label(text=header)

                        stags = s.get("tags") or []
                        if isinstance(stags, list) and stags:
                            stags_preview = ", ".join(str(t) for t in stags[:10])
                            if len(stags) > 10:
                                stags_preview += " ..."
                            box.label(text=f"  - {stags_preview}")
            else:
                box.label(text="(Invalid semantic JSON)")

        layout.separator()

        if props.is_generating:
            layout.label(text=props.generation_status, icon='TIME')
        else:
            row = layout.row()
            row.enabled = bool(props.semantic_plan_json) and bool(props.text_prompt) and (not props.is_generating)
            row.operator("matcomposer.generate_material", text="Search Slots", icon='VIEWZOOM')
            layout.label(text=props.generation_status)

        if props.semantic_plan_json and library_ready:
            layout.separator()
            plan = None
            try:
                plan = json.loads(props.semantic_plan_json)
            except Exception:
                plan = None

            if isinstance(plan, dict):
                row = layout.row()
                row.enabled = (not props.is_generating)
                row.operator("matcomposer.load_candidate_previews", text="Refresh Previews", icon='FILE_REFRESH')

                # Exploration Mode Selector
                row.prop(props, "exploration_mode", text="")

                slots = plan.get("slots") or []
                if isinstance(slots, list) and slots:
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

                    candidates_by_role = {}
                    try:
                        data = json.loads(props.slot_candidates_json) if props.slot_candidates_json else {}
                        if isinstance(data, dict):
                            candidates_by_role = data
                    except Exception:
                        candidates_by_role = {}

                    selection_by_role = {}
                    try:
                        data = json.loads(props.slot_selection_json) if props.slot_selection_json else {}
                        if isinstance(data, dict):
                            selection_by_role = data
                    except Exception:
                        selection_by_role = {}

                    for role in ordered_roles:
                        slot = role_to_slot.get(role)
                        if not slot:
                            continue

                        box = layout.box()
                        concept = str(slot.get("concept") or "")
                        relation = str(slot.get("relation") or "")
                        header = role
                        if concept:
                            header += f" / {concept}"
                        if relation:
                            header += f" ({relation})"
                        box.label(text=header)

                        # Per-Slot Exploration Controls
                        row = box.row(align=True)
                        can_explore = (not props.is_generating) and library_ready
                        row.enabled = can_explore

                        op = row.operator("matcomposer.explore_auto", text="Explore", icon='VIEWZOOM')
                        op.role = role

                        sub = row.row(align=True)
                        sub.enabled = bool(getattr(props, "last_search_state_json", "")) and (not props.is_generating)
                        # Revert is currently global (undo last step), but placing it here provides context.
                        # Ideally revert should also be per-slot, but the operator is global.
                        sub.operator("matcomposer.revert_search_state", text="Revert", icon='BACK')

                        sel = selection_by_role.get(role) if isinstance(selection_by_role, dict) else None
                        curr_id = ""
                        if isinstance(sel, dict):
                            curr_id = str(sel.get("curr") or "")
                        if curr_id:
                            entry = library_manager.library_manager.get_entry_by_id(curr_id)
                            if entry:
                                box.label(text=f"Selected: {entry.get('name')}")
                                lm = library_manager.library_manager
                                sdata = _entry_struct_data(entry, lm)
                                if sdata:
                                    v = sdata["vec"]
                                    c = sdata["complexity"]
                                    box.label(text=f"Complexity {c:.2f}  {_bar(c, 12)}")
                                    box.label(text=f"N {_bar(v[0], 8)}  D {_bar(v[1], 8)}")
                                    box.label(text=f"B {_bar(v[2], 8)}  P {_bar(v[4], 8)}")

                                # Structural Difference Explanation
                                prev_id = str(props.prev_selected_entry_id or "")
                                if prev_id and prev_id != curr_id:
                                    prev_entry = library_manager.library_manager.get_entry_by_id(prev_id)
                                    if prev_entry:
                                        diff_text = library_manager.library_manager.get_structural_diff_explanation(prev_entry, entry)
                                        if diff_text:
                                            box.label(text=diff_text, icon='INFO')

                        show_mask = bool(role != "Base" or relation != "base")
                        llm_mask = str(slot.get("mask") or "").strip() if show_mask else ""
                        curr_mask = _get_mask_selection_for_role(props, role, slot=slot) if show_mask else ""
                        mask_items = _mask_items_for_ui() if show_mask else []
                        current_item = None
                        if show_mask:
                            for item in mask_items:
                                if str(item.get("key") or "") == curr_mask:
                                    current_item = item
                                    break
                            if current_item is None:
                                current_item = mask_items[0] if mask_items else {"key": "", "label": "No Mask", "icon_id": 0}

                        ids = candidates_by_role.get(role) if isinstance(candidates_by_role, dict) else None
                        if not isinstance(ids, list):
                            ids = []
                        ids = [str(x) for x in ids if str(x)]

                        if ids:
                            ids = ids[:4]
                            region_w = 0
                            try:
                                region_w = int(getattr(getattr(context, "region", None), "width", 0) or 0)
                            except Exception:
                                region_w = 0

                            columns = 4
                            if region_w > 0:
                                try:
                                    columns = int(region_w // 140)
                                except Exception:
                                    columns = 4
                            if columns < 1:
                                columns = 1
                            if columns > 4:
                                columns = 4
                            if columns > len(ids):
                                columns = len(ids)

                            tile_scale_y = 5.0
                            if region_w > 0 and columns > 0:
                                inner_w = region_w - 32
                                if inner_w < 80:
                                    inner_w = region_w
                                tile_w = float(inner_w) / float(columns)
                                # base_row_px adjusted to 26.0 to reduce height slightly (avoid "too tall" feel)
                                # Larger denominator = smaller scale = smaller height
                                base_row_px = 26.0
                                tile_scale_y = tile_w / base_row_px
                                if tile_scale_y < 1.0:
                                    tile_scale_y = 1.0
                                if tile_scale_y > 20.0:
                                    tile_scale_y = 20.0

                            flow = box.grid_flow(columns=columns, even_columns=True, even_rows=True, align=True)
                            lm = library_manager.library_manager

                            for eid in ids:
                                entry = lm.get_entry_by_id(eid)
                                name = str(entry.get("name") or eid) if isinstance(entry, dict) else str(eid)

                                icon_id = 0
                                preview_img = None
                                if isinstance(entry, dict):
                                    # Try to get icon_id first (most reliable for size scaling via template_icon)
                                    try:
                                        lm.try_load_entry_preview_icon_id(entry)
                                    except Exception:
                                        pass
                                    try:
                                        icon_id = int(entry.get("_mc_preview_icon_id") or 0)
                                    except Exception:
                                        icon_id = 0

                                    # Fallback to direct image load if icon_id fails
                                    if icon_id <= 0:
                                        try:
                                            preview_img = lm.try_load_entry_preview_image(entry)
                                        except Exception:
                                            preview_img = None

                                col = flow.column(align=True)

                                # 1. Render Preview (Image or Icon)
                                # We separate preview from the button because operator icons cannot be arbitrarily scaled.
                                is_selected = bool(curr_id and str(curr_id) == str(eid))

                                if icon_id > 0:
                                    # Use template_icon with scale to create a large square preview
                                    # Removing container scaling (scale_y/scale_x) to prevent double scaling or layout stretching
                                    icon_col = col.column(align=True)
                                    icon_col.template_icon(icon_value=icon_id, scale=tile_scale_y)
                                elif preview_img:
                                    # Use template_preview for direct image objects
                                    # It fills the width automatically
                                    col.template_preview(preview_img, show_buttons=False)
                                else:
                                    # Placeholder if nothing is available
                                    # Make a box to occupy space
                                    sub = col.column(align=True)
                                    sub.scale_y = tile_scale_y * 0.8 # Slightly smaller placeholder
                                    sub.label(text="No Preview", icon='MATERIAL_DATA')

                                # 2. Render Interaction Button (Name)
                                label = name
                                if len(label) > 18:
                                    label = label[:17] + "…"

                                sub = col.column(align=True)
                                sub.scale_y = 1.2
                                op = sub.operator(
                                    "matcomposer.select_slot_candidate",
                                    text=label,
                                    depress=is_selected,
                                    emboss=True,
                                )
                                op.role = role
                                op.entry_id = str(eid)
                                if isinstance(entry, dict):
                                    sdata = _entry_struct_data(entry, lm)
                                    if sdata:
                                        vec = sdata["vec"]
                                        mini = _mini_blocks(vec, dims=(0, 1, 2, 4))
                                        col.label(text=f"C {sdata['complexity']:.2f}  NDBP {mini}")
                        else:
                            box.label(text="No candidates yet. Click Search Slots.")

                        if show_mask:
                            box.separator()
                            box.label(text="Mask")
                            if llm_mask:
                                box.label(text=f"LLM Mask: {llm_mask}")

                            current_box = box.box()
                            icon_id = int(current_item.get("icon_id") or 0)
                            if icon_id > 0:
                                current_box.template_icon(icon_value=icon_id, scale=5.0)
                            else:
                                current_box.label(text="", icon='TEXTURE')
                            open_picker = current_box.operator(
                                "matcomposer.open_mask_picker",
                                text=str(current_item.get("label") or "No Mask"),
                                icon_value=icon_id if icon_id > 0 else 0,
                            )
                            open_picker.role = role
                            if curr_mask:
                                box.label(text=f"Using Mask: {curr_mask}")
                            else:
                                box.label(text="Using Mask: none")

class MATCOMPOSER_PT_Exploration(bpy.types.Panel):
    bl_label = "Exploration & Evolution"
    bl_idname = "MATCOMPOSER_PT_Exploration"
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "MatComposer"
    bl_parent_id = "MATCOMPOSER_PT_Panel"

    def draw(self, context):
        layout = self.layout
        props = context.scene.mat_composer
        library_ready = bool(library_manager.library_manager.index_data)
        semantic_ready = bool(props.semantic_plan_json)

        layout.label(text="Library Exploration:")

        row = layout.row()
        row.enabled = semantic_ready and library_ready and (not props.is_generating)
        row.operator("matcomposer.assemble_slots", icon='NODE_MATERIAL')
        row = layout.row()
        row.prop(props, "force_external_mapping", text="Force External UV Mapping")

classes = [
    MATCOMPOSER_PT_Panel,
    MATCOMPOSER_PT_Exploration
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    global _MASK_UI_IMAGE_CACHE, _MASK_UI_DEBUG
    try:
        for img in list(_MASK_UI_IMAGE_CACHE.values()):
            img_name = str(getattr(img, "name", "") or "")
            if img and img_name and bpy.data.images.get(img_name) is not None:
                bpy.data.images.remove(img)
    except Exception:
        pass
    _MASK_UI_IMAGE_CACHE = {}
    _MASK_UI_DEBUG = {}
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
