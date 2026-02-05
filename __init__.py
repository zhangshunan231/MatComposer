bl_info = {
    "name": "MatComposer",
    "author": "Trae",
    "version": (1, 0),
    "blender": (4, 0, 0),
    "location": "Shader Editor > UI > MatComposer",
    "description": "Neuro-Symbolic procedural material generation",
    "category": "Material",
}

import bpy
from . import ui
from . import operators

# Scene Properties
import json

def _safe_load_json_dict(s):
    if not s:
        return {}
    try:
        data = json.loads(s)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _get_candidate_ids_for_role(props, role):
    data = _safe_load_json_dict(getattr(props, "slot_candidates_json", ""))
    ids = data.get(str(role))
    if not isinstance(ids, list):
        return []
    return [str(x) for x in ids if str(x)]


def _set_selection_for_role(props, role, entry_id):
    entry_id = str(entry_id or "")
    if not entry_id:
        return
    data = _safe_load_json_dict(getattr(props, "slot_selection_json", ""))
    slot_data = data.get(str(role))
    if not isinstance(slot_data, dict):
        slot_data = {}
    prev_id = str(slot_data.get("curr") or "")
    data[str(role)] = {"prev": prev_id, "curr": entry_id}
    props.slot_selection_json = json.dumps(data)


def _candidate_items(self, role):
    if self is None:
        return []
    try:
        from .utils import library_manager as _lm_mod
    except Exception:
        return []
    props = self
    ids = _get_candidate_ids_for_role(props, role)
    lm = _lm_mod.library_manager

    # Determine visibility
    show_all = True
    
    # Determine current selection index to ensure it's always visible
    curr_val = "0"
    try:
        data = _safe_load_json_dict(getattr(props, "slot_selection_json", ""))
        slot_data = data.get(str(role))
        if isinstance(slot_data, dict):
            curr_id = str(slot_data.get("curr") or "")
            if curr_id and curr_id in ids:
                curr_val = str(ids.index(curr_id) + 1)
    except:
        pass

    # Helper for description (tooltip)
    def get_desc(entry):
        if not isinstance(entry, dict): return ""
        lines = []
        vec = entry.get("k_vector")
        if vec and len(vec) >= 6:
            lines.append(f"Structure: N:{vec[0]:.2f} D:{vec[1]:.2f} B:{vec[2]:.2f} P:{vec[4]:.2f}")
        asset_tags = entry.get("asset_tags") or []
        if asset_tags:
            t_str = ", ".join(str(t) for t in asset_tags[:5])
            lines.append(f"Tags: {t_str}")
        else:
            tags = entry.get("tags")
            if tags:
                lib_name = str(entry.get("library_name") or "")
                filtered = []
                for t in tags:
                    s = str(t).strip()
                    if not s:
                        continue
                    sl = s.lower()
                    if sl in ("scanned", "material"):
                        continue
                    if lib_name and sl == lib_name.lower():
                        continue
                    filtered.append(s)
                if filtered:
                    t_str = ", ".join(filtered[:5])
                    lines.append(f"Tags: {t_str}")
        return " | ".join(lines) if lines else ""

    out = []
    
    for i in range(1, 5):
        key = str(i)
        
        # Visibility Logic
        is_visible = show_all
        if not is_visible:
            if key == curr_val:
                is_visible = True
            elif curr_val == "0" and i == 1:
                is_visible = True
        
        if not is_visible:
            continue

        idx = i - 1
        if idx < len(ids):
            eid = ids[idx]
            entry = lm.get_entry_by_id(eid)
            name = str(entry.get("name") or eid) if isinstance(entry, dict) else str(eid)
            desc = get_desc(entry)
            
            icon_id = 0
            if isinstance(entry, dict):
                try:
                    lm.try_load_entry_preview_icon_id(entry)
                except Exception:
                    pass
                try:
                    icon_id = int(entry.get("_mc_preview_icon_id") or 0)
                except Exception:
                    icon_id = 0
            if icon_id > 0:
                out.append((key, name, desc, icon_id, i))
            else:
                out.append((key, name, desc, 'MATERIAL_DATA', i))
        else:
            # Placeholder for empty slot
            out.append((key, f"Empty {i}", "No material", 'NONE', i))
            
    return out


def _candidate_items_base(self, context):
    return _candidate_items(self, "Base")


def _candidate_items_overlay(self, context):
    return _candidate_items(self, "Overlay")


def _candidate_items_detail(self, context):
    return _candidate_items(self, "Detail")


def _candidate_update(self, context, role, prop_name):
    try:
        val_str = str(getattr(self, prop_name) or "0")
    except Exception:
        val_str = "0"
    
    if val_str == "0":
        return

    try:
        idx = int(val_str) - 1
    except ValueError:
        return

    if idx < 0:
        return

    ids = _get_candidate_ids_for_role(self, role)
    if idx < len(ids):
        real_id = ids[idx]
        if real_id:
            # Check for duplicates across slots
            data = _safe_load_json_dict(getattr(self, "slot_selection_json", ""))
            all_roles = ["Base", "Overlay", "Detail"]
            
            for other_role in all_roles:
                if other_role == role:
                    continue
                
                other_data = data.get(other_role)
                if isinstance(other_data, dict):
                    other_id = str(other_data.get("curr") or "")
                    if other_id == str(real_id):
                        # Found duplicate
                        def draw_warning(self, context):
                            self.layout.label(text=f"Material already selected in {other_role}!")
                        
                        bpy.context.window_manager.popup_menu(draw_warning, title="Duplicate Selection", icon='ERROR')
                        
                        # Reset selection to None ("0")
                        setattr(self, prop_name, "0")
                        return

            _set_selection_for_role(self, role, real_id)


def _candidate_update_base(self, context):
    _candidate_update(self, context, "Base", "candidate_pick_base")


def _candidate_update_overlay(self, context):
    _candidate_update(self, context, "Overlay", "candidate_pick_overlay")


def _candidate_update_detail(self, context):
    _candidate_update(self, context, "Detail", "candidate_pick_detail")

# PropertyGroup for History/Variants
class MatComposerHistoryItem(bpy.types.PropertyGroup):
    material_name: bpy.props.StringProperty()
    params_json: bpy.props.StringProperty() # JSON string of parameters

class MatComposerProperties(bpy.types.PropertyGroup):
    api_key: bpy.props.StringProperty(
        name="API Key",
        description="DashScope API Key",
        default="",
        subtype='PASSWORD'
    )
    text_prompt: bpy.props.StringProperty(
        name="Text Prompt",
        description="Describe the material you want",
        default="",
        options={'SKIP_SAVE'} 
    )
    image_input: bpy.props.PointerProperty(
        name="Image",
        description="Optional image input",
        type=bpy.types.Image
    )
    model_selection: bpy.props.EnumProperty(
        name="Model",
        description="Select the LLM model",
        items=[
            ('qwen-vl-plus', "Qwen VL Plus", "Qwen VL Plus"),
            ('qwen-vl-max', "Qwen VL Max", "Qwen VL Max"),
        ],
        default='qwen-vl-plus'
    )
    # Status/Progress
    is_generating: bpy.props.BoolProperty(
        name="Is Generating",
        default=False
    )
    generation_status: bpy.props.StringProperty(
        name="Status",
        default="Ready"
    )
    # UI State
    show_candidates_expanded: bpy.props.BoolProperty(
        name="Show All Candidates",
        description="Expand to show all candidates or collapse to show only the selected one",
        default=False
    )
    debug_mode: bpy.props.BoolProperty(
        name="Debug Mode",
        description="Print debug info to system console",
        default=False
    )
    
    # State Management
    history: bpy.props.CollectionProperty(type=MatComposerHistoryItem)
    current_history_index: bpy.props.IntProperty(default=-1)
    
    # Variants (we store 4 slots)
    variant_1_params: bpy.props.StringProperty(default="")
    variant_2_params: bpy.props.StringProperty(default="")
    variant_3_params: bpy.props.StringProperty(default="")
    variant_4_params: bpy.props.StringProperty(default="")

    semantic_plan_json: bpy.props.StringProperty(
        name="Semantic Plan",
        default="",
        options={'SKIP_SAVE'}
    )
    semantic_repr_json: bpy.props.StringProperty(
        name="Semantic Representation",
        default="",
        options={'SKIP_SAVE'}
    )

    search_complexity: bpy.props.FloatProperty(
        name="Search Complexity",
        min=0.0,
        max=1.0,
        default=0.4
    )

    exploration_mode: bpy.props.EnumProperty(
        name="Exploration Mode",
        description="Choose how to explore the material space",
        items=[
            ('JOINT', "Joint Exploration", "Explore both Semantics and Structure"),
            ('LOCK_SEMANTICS', "Lock Semantics", "Keep Style, Explore Structure"),
            ('LOCK_STRUCTURE', "Lock Structure", "Keep Structure, Explore Style"),
        ],
        default='JOINT'
    )

    slot_candidates_json: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    slot_selection_json: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    last_search_state_json: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    candidate_pick_base: bpy.props.EnumProperty(items=_candidate_items_base, update=_candidate_update_base, options={'SKIP_SAVE'})
    candidate_pick_overlay: bpy.props.EnumProperty(items=_candidate_items_overlay, update=_candidate_update_overlay, options={'SKIP_SAVE'})
    candidate_pick_detail: bpy.props.EnumProperty(items=_candidate_items_detail, update=_candidate_update_detail, options={'SKIP_SAVE'})

    explore_candidate_1_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    explore_candidate_2_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    explore_candidate_3_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    explore_candidate_4_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    explore_asset_scope: bpy.props.EnumProperty(
        name="Explore Asset Type",
        items=[
            ('MATERIAL', "Materials Only", ""),
        ],
        default='MATERIAL'
    )

    lock_base_slot: bpy.props.BoolProperty(name="Lock Base", default=False)
    lock_overlay_slot: bpy.props.BoolProperty(name="Lock Overlay", default=False)
    lock_detail_slot: bpy.props.BoolProperty(name="Lock Detail", default=False)

    apply_slot_role: bpy.props.EnumProperty(
        name="Apply To Slot",
        items=[
            ('Base', "Base", ""),
            ('Overlay', "Overlay", ""),
            ('Detail', "Detail", ""),
        ],
        default='Base'
    )

    prev_selected_entry_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    curr_selected_entry_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    
    last_exploration_mode: bpy.props.StringProperty(
        name="Last Exploration Mode",
        default="LOCAL",
        options={'SKIP_SAVE'}
    )

classes = [
    MatComposerHistoryItem,
    MatComposerProperties,
]

def _reset_candidate_picks_for_scene(scene):
    if not scene:
        return
    props = getattr(scene, "mat_composer", None)
    if not props:
        return
    try:
        props.candidate_pick_base = "0"
        props.candidate_pick_overlay = "0"
        props.candidate_pick_detail = "0"
    except Exception:
        pass

def _on_load_post(_dummy):
    for scene in getattr(bpy.data, "scenes", []) or []:
        _reset_candidate_picks_for_scene(scene)

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    
    bpy.types.Scene.mat_composer = bpy.props.PointerProperty(type=MatComposerProperties)

    for scene in getattr(bpy.data, "scenes", []) or []:
        _reset_candidate_picks_for_scene(scene)
    try:
        if _on_load_post not in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.append(_on_load_post)
    except Exception:
        pass
    
    ui.register()
    operators.register()

def unregister():
    ui.unregister()
    operators.unregister()

    try:
        if _on_load_post in bpy.app.handlers.load_post:
            bpy.app.handlers.load_post.remove(_on_load_post)
    except Exception:
        pass
    
    del bpy.types.Scene.mat_composer
    
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

if __name__ == "__main__":
    register()
