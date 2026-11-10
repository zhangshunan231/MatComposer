# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

import bpy
import os


HOOK_OUTPUT_TO_PRINCIPLED_INPUT = {
    "Hook_BaseColor": "Base Color",
    "Hook_Roughness": "Roughness",
    "Hook_Metallic": "Metallic",
    "Hook_Normal": "Normal",
    "Hook_Emission": "Emission Color",
    "Hook_Alpha": "Alpha",
}

_MASK_BLENDS_CACHE = None


def _repo_root_dir():
    try:
        return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    except Exception:
        return os.path.abspath(os.getcwd())


def _masks_dir():
    return os.path.join(_repo_root_dir(), "masks")


def _list_mask_blends():
    global _MASK_BLENDS_CACHE
    if isinstance(_MASK_BLENDS_CACHE, dict) and _MASK_BLENDS_CACHE:
        return dict(_MASK_BLENDS_CACHE)
    root = _masks_dir()
    out = {}
    try:
        for fn in os.listdir(root):
            if not str(fn).lower().endswith(".blend"):
                continue
            key = os.path.splitext(str(fn))[0].strip()
            if not key:
                continue
            out[key] = os.path.join(root, fn)
    except Exception:
        out = {}
    _MASK_BLENDS_CACHE = dict(out)
    return out


def _append_first_node_group(full_path: str, prefer_name: str = ""):
    prefer_name = str(prefer_name or "").strip()
    try:
        with bpy.data.libraries.load(full_path, link=False) as (data_from, data_to):
            names = list(getattr(data_from, "node_groups", []) or [])
            if not names:
                return None
            pick = None
            if prefer_name:
                for n in names:
                    if str(n) == prefer_name:
                        pick = n
                        break
                if pick is None:
                    for n in names:
                        if prefer_name.lower() in str(n).lower():
                            pick = n
                            break
            if pick is None:
                pick = names[0]
            data_to.node_groups = [pick]
        return bpy.data.node_groups.get(pick)
    except Exception:
        return None


def _pick_mask_key(hints, available_keys, context=None):
    if not available_keys:
        return ""
    normalized_available = {str(k).strip().lower(): k for k in available_keys if str(k).strip()}
    if hints:
        for h in hints:
            if h is None:
                continue
            if isinstance(h, (list, tuple, set)):
                for x in h:
                    s = str(x or "").strip().lower()
                    if s:
                        if s in normalized_available:
                            return normalized_available[s]
                        s2 = s.replace("-", "_").replace(" ", "_")
                        if s2 in normalized_available:
                            return normalized_available[s2]
                        for nk, raw in normalized_available.items():
                            if nk and (nk in s or nk in s2):
                                return raw
                continue
            s = str(h or "").strip().lower()
            if s:
                if s in normalized_available:
                    return normalized_available[s]
                s2 = s.replace("-", "_").replace(" ", "_")
                if s2 in normalized_available:
                    return normalized_available[s2]
                for nk, raw in normalized_available.items():
                    if nk and (nk in s or nk in s2):
                        return raw
    if "ao_mask" in normalized_available:
        return normalized_available["ao_mask"]
    return sorted(list(available_keys))[0]


def _mask_fac_socket(tree, mapping, mask_hints, location=(-350, -520), context=None):
    blends = _list_mask_blends()
    key = _pick_mask_key(mask_hints, set(blends.keys()), context=context)
    if not key:
        return None
    full_path = blends.get(key)
    if not full_path or not os.path.exists(full_path):
        return None
    ng = _append_first_node_group(full_path, prefer_name=key)
    if not ng:
        return None

    group_node = tree.nodes.new(type="ShaderNodeGroup")
    group_node.node_tree = ng
    group_node.label = f"Mask: {key}"
    group_node.name = f"MC_Mask_{key}"
    group_node.location = location

    if mapping:
        linked = False
        for inp_name in ("Vector", "UV", "Mapping"):
            inp = group_node.inputs.get(inp_name)
            if inp and not inp.is_linked:
                try:
                    tree.links.new(mapping.outputs.get("Vector"), inp)
                    linked = True
                except Exception:
                    pass
                break
        if not linked:
            try:
                inputs = list(getattr(group_node, "inputs", []) or [])
            except Exception:
                inputs = []
            for inp in inputs:
                if not inp or getattr(inp, "is_linked", False):
                    continue
                try:
                    stype = str(getattr(inp, "type", "") or "")
                except Exception:
                    stype = ""
                if stype == "VECTOR":
                    try:
                        tree.links.new(mapping.outputs.get("Vector"), inp)
                        linked = True
                        break
                    except Exception:
                        pass

    out_priority = ("Fac", "Factor", "Mask", "Value", "Result", "Alpha", "Color")
    picked = None
    for name in out_priority:
        s = group_node.outputs.get(name)
        if s is not None:
            picked = s
            break
    if picked is None:
        try:
            outs = list(getattr(group_node, "outputs", []) or [])
        except Exception:
            outs = []
        for s in outs:
            if s is not None:
                picked = s
                break
    if picked is None:
        return None

    try:
        stype = str(getattr(picked, "type", "") or "")
    except Exception:
        stype = ""
    if stype in ("VALUE", "FLOAT"):
        return picked
    if stype in ("RGBA", "COLOR"):
        rgb2bw = tree.nodes.new(type="ShaderNodeRGBToBW")
        rgb2bw.location = (location[0] + 220, location[1])
        try:
            tree.links.new(picked, rgb2bw.inputs.get("Color"))
        except Exception:
            pass
        return rgb2bw.outputs.get("Val")
    return None

def _interface_iter_sockets(node_tree):
    interface = getattr(node_tree, "interface", None)
    if not interface:
        return []
    items_tree = getattr(interface, "items_tree", None)
    if not items_tree:
        return []
    out = []
    try:
        stack = list(items_tree)
    except Exception:
        stack = []
    while stack:
        item = stack.pop(0)
        if not item:
            continue
        if getattr(item, "item_type", "") == "SOCKET":
            out.append(item)
        try:
            children = list(getattr(item, "items", []) or [])
        except Exception:
            children = []
        if children:
            stack.extend(children)
    return out


def _ensure_tree_socket(node_tree, in_out, socket_type, name):
    name = str(name or "")
    if not name:
        return False

    try:
        if in_out == "INPUT" and hasattr(node_tree, "inputs"):
            if name in node_tree.inputs:
                return True
        if in_out == "OUTPUT" and hasattr(node_tree, "outputs"):
            if name in node_tree.outputs:
                return True
    except Exception:
        pass

    for s in _interface_iter_sockets(node_tree):
        if str(getattr(s, "name", "") or "") != name:
            continue
        if str(getattr(s, "in_out", "") or "") == str(in_out):
            return True

    interface = getattr(node_tree, "interface", None)
    if interface:
        try:
            interface.new_socket(name=name, in_out=str(in_out), socket_type=str(socket_type))
            return True
        except Exception:
            pass

    try:
        if in_out == "INPUT" and hasattr(node_tree, "inputs"):
            node_tree.inputs.new(str(socket_type), name)
            return True
        if in_out == "OUTPUT" and hasattr(node_tree, "outputs"):
            node_tree.outputs.new(str(socket_type), name)
            return True
    except Exception:
        return False

    return False


def _get_or_create_output(tree):
    for n in tree.nodes:
        if n.type == "OUTPUT_MATERIAL":
            return n
    n = tree.nodes.new(type="ShaderNodeOutputMaterial")
    n.name = "Material Output"
    n.label = "Material Output"
    n.location = (500, 0)
    return n


def _get_or_create_principled(tree):
    for n in tree.nodes:
        if n.type == "BSDF_PRINCIPLED":
            return n
    n = tree.nodes.new(type="ShaderNodeBsdfPrincipled")
    n.name = "Principled BSDF"
    n.label = "Principled BSDF"
    n.location = (200, 0)
    return n


def ensure_master_shader(tree, create_principled: bool = True):
    out = _get_or_create_output(tree)
    if not create_principled:
        return None, out
    bsdf = _get_or_create_principled(tree)
    surface = out.inputs.get("Surface")
    bsdf_out = bsdf.outputs.get("BSDF")
    if surface and bsdf_out and not surface.is_linked:
        tree.links.new(bsdf_out, surface)
    return bsdf, out


def _ensure_mapping_chain(tree):
    texcoord = tree.nodes.get("MC_TexCoord")
    if not texcoord:
        texcoord = tree.nodes.new(type="ShaderNodeTexCoord")
        texcoord.name = "MC_TexCoord"
        texcoord.label = "MC_TexCoord"
        texcoord.location = (-900, -300)

    mapping = tree.nodes.get("MC_Mapping")
    if not mapping:
        mapping = tree.nodes.new(type="ShaderNodeMapping")
        mapping.name = "MC_Mapping"
        mapping.label = "MC_Mapping"
        mapping.location = (-650, -300)

    mv = mapping.inputs.get("Vector")
    uv = texcoord.outputs.get("UV")
    if mv and uv and not mv.is_linked:
        tree.links.new(uv, mv)

    return mapping


def _append_node_group(full_path: str, group_name: str):
    if group_name in bpy.data.node_groups:
        return bpy.data.node_groups[group_name]
    with bpy.data.libraries.load(full_path, link=False) as (data_from, data_to):
        if group_name in data_from.node_groups:
            data_to.node_groups = [group_name]
    return bpy.data.node_groups.get(group_name)


def _append_material(full_path: str, mat_name: str):
    if mat_name in bpy.data.materials:
        return bpy.data.materials[mat_name], False
    existing_names = {m.name for m in bpy.data.materials}
    with bpy.data.libraries.load(full_path, link=False) as (data_from, data_to):
        if mat_name in data_from.materials:
            data_to.materials = [mat_name]
    mats = [m for m in bpy.data.materials if m.name == mat_name]
    if not mats:
        return None, False
    return mats[0], mats[0].name not in existing_names


def _copy_node_attributes(src, dst):
    props_to_copy = [
        "operation", "blend_type", "data_type", "clamp_factor", "clamp_result", "use_clamp",
        "mode", "interpolation", "projection", "extension", "distribution",
        "color_mode", "distance_metric", "falloff", "gradient_type",
        "musgrave_type", "noise_dimensions", "noise_type", "offset", "offset_type",
        "rotation_mode", "space", "texture_mapping", "tolerance", "vector_type",
        "wave_profile", "wave_type", "axis", "channel", "component",
        "factor_mode", "feature", "turbulence_depth"
    ]

    for p in props_to_copy:
        if hasattr(src, p) and hasattr(dst, p):
            try:
                setattr(dst, p, getattr(src, p))
            except Exception:
                pass

    if hasattr(src, "color_ramp") and hasattr(dst, "color_ramp"):
        try:
            src_cr = src.color_ramp
            dst_cr = dst.color_ramp
            dst_cr.color_mode = src_cr.color_mode
            dst_cr.hue_interpolation = src_cr.hue_interpolation
            dst_cr.interpolation = src_cr.interpolation

            src_elems = src_cr.elements
            dst_elems = dst_cr.elements

            while len(dst_elems) > len(src_elems):
                dst_elems.remove(dst_elems[-1])
            while len(dst_elems) < len(src_elems):
                dst_elems.new(1.0)

            for i, src_el in enumerate(src_elems):
                dst_el = dst_elems[i]
                dst_el.position = src_el.position
                dst_el.color = src_el.color
                dst_el.alpha = src_el.alpha
        except Exception:
            pass


def _material_to_node_group(source_material: bpy.types.Material, group_name: str):
    if not source_material or not getattr(source_material, "use_nodes", False):
        return None
    src_tree = getattr(source_material, "node_tree", None)
    if not src_tree:
        return None

    base_name = group_name or (source_material.name + "_MCGroup")
    name = base_name
    if name in bpy.data.node_groups:
        i = 2
        while f"{base_name}_{i}" in bpy.data.node_groups:
            i += 1
        name = f"{base_name}_{i}"

    ng = bpy.data.node_groups.new(name=name, type='ShaderNodeTree')

    def _node_xy(node):
        try:
            return float(node.location.x), float(node.location.y)
        except Exception:
            try:
                return float(node.location[0]), float(node.location[1])
            except Exception:
                return 0.0, 0.0

    def _abs_location_src(node):
        x, y = _node_xy(node)
        parent = getattr(node, "parent", None)
        while parent:
            px, py = _node_xy(parent)
            x += px
            y += py
            parent = getattr(parent, "parent", None)
        return x, y

    node_map = {}
    output_nodes = []
    for n in src_tree.nodes:
        try:
            if getattr(n, "type", "") == "OUTPUT_MATERIAL":
                output_nodes.append(n)
                continue
        except Exception:
            pass
        try:
            if getattr(n, "type", "") == "FRAME":
                continue
        except Exception:
            pass
        try:
            nn = ng.nodes.new(type=n.bl_idname)
        except Exception:
            continue
        nn.name = n.name
        nn.label = n.label
        try:
            if hasattr(n, "node_tree") and hasattr(nn, "node_tree"):
                if getattr(n, "node_tree", None):
                    nn.node_tree = n.node_tree
        except Exception:
            pass
        try:
            ax, ay = _abs_location_src(n)
            nn.location = (ax, ay)
        except Exception:
            pass
        try:
            nn.width = n.width
        except Exception:
            pass
        try:
            nn.height = n.height
        except Exception:
            pass
        try:
            nn.hide = n.hide
        except Exception:
            pass
        node_map[n] = nn

        try:
            if hasattr(n, "image") and hasattr(nn, "image"):
                nn.image = n.image
        except Exception:
            pass

        _copy_node_attributes(n, nn)

        for inp in getattr(n, "inputs", []) or []:
            if getattr(inp, "is_linked", False):
                continue
            try:
                src_val = inp.default_value
            except Exception:
                continue
            dst_inp = nn.inputs.get(inp.name)
            if not dst_inp or getattr(dst_inp, "is_linked", False):
                continue
            try:
                dst_inp.default_value = src_val
            except Exception:
                pass

    group_in = ng.nodes.new(type="NodeGroupInput")
    group_out = ng.nodes.new(type="NodeGroupOutput")

    xs = []
    ys = []
    for n in ng.nodes:
        if n in (group_in, group_out):
            continue
        try:
            ax, ay = _node_xy(n)
            xs.append(float(ax))
            ys.append(float(ay))
        except Exception:
            continue
    if xs and ys:
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        center_y = (min_y + max_y) * 0.5
        group_in.location = (min_x - 200.0, center_y)
        group_out.location = (max_x + 200.0, center_y)
    else:
        group_in.location = (-600, 0)
        group_out.location = (400, 0)

    _ensure_tree_socket(ng, "INPUT", "NodeSocketVector", "Vector")

    vector_socket = group_in.outputs.get("Vector")
    if vector_socket:
        for node in ng.nodes:
            if node in (group_in, group_out):
                continue
            for inp_name in ("Vector", "UV", "Mapping"):
                inp = node.inputs.get(inp_name) if getattr(node, "inputs", None) else None
                if inp and not inp.is_linked:
                    try:
                        ng.links.new(vector_socket, inp)
                    except Exception:
                        pass
                    break

    def _socket_type_for_socket(sock):
        if not sock:
            return "NodeSocketFloat"
        try:
            st = str(getattr(sock, "type", "") or "")
        except Exception:
            st = ""
        if st == "SHADER":
            return "NodeSocketShader"
        if st in ("RGBA", "COLOR"):
            return "NodeSocketColor"
        if st == "VECTOR":
            return "NodeSocketVector"
        if st in ("VALUE", "FLOAT"):
            return "NodeSocketFloat"
        return "NodeSocketFloat"

    for l in src_tree.links:
        fn = node_map.get(l.from_node)
        if not fn:
            continue
        fs = fn.outputs.get(l.from_socket.name) if fn.outputs else None
        if not fs:
            continue
        if l.to_node in output_nodes:
            out_name = str(l.to_socket.name or "")
            if out_name:
                if out_name == "Surface":
                    if _ensure_tree_socket(ng, "OUTPUT", "NodeSocketShader", "Hook_BSDF"):
                        hook_bsdf = group_out.inputs.get("Hook_BSDF")
                        if hook_bsdf:
                            try:
                                ng.links.new(fs, hook_bsdf)
                            except Exception:
                                pass
                if _ensure_tree_socket(ng, "OUTPUT", _socket_type_for_socket(fs), out_name):
                    dst = group_out.inputs.get(out_name)
                    if dst:
                        try:
                            ng.links.new(fs, dst)
                        except Exception:
                            pass
            continue
        tn = node_map.get(l.to_node)
        if not tn:
            continue
        ts = tn.inputs.get(l.to_socket.name) if tn.inputs else None
        if not ts:
            continue
        try:
            ng.links.new(fs, ts)
        except Exception:
            pass

    output_node = output_nodes[0] if output_nodes else None

    principled = None
    if output_node:
        try:
            if output_node.inputs.get("Surface") and output_node.inputs["Surface"].is_linked:
                from_node = output_node.inputs["Surface"].links[0].from_node
                if getattr(from_node, "type", "") == "BSDF_PRINCIPLED":
                    principled = from_node
        except Exception:
            principled = None

    if not principled:
        for n in src_tree.nodes:
            if getattr(n, "type", "") == "BSDF_PRINCIPLED":
                principled = n
                break

    if principled and principled in node_map:
        pn = node_map[principled]
        mapping = {
            "Base Color": ("Hook_BaseColor", "NodeSocketColor"),
            "Roughness": ("Hook_Roughness", "NodeSocketFloat"),
            "Metallic": ("Hook_Metallic", "NodeSocketFloat"),
            "Normal": ("Hook_Normal", "NodeSocketVector"),
            "Emission Color": ("Hook_Emission", "NodeSocketColor"),
            "Alpha": ("Hook_Alpha", "NodeSocketFloat"),
        }
        if _ensure_tree_socket(ng, "OUTPUT", "NodeSocketShader", "Hook_BSDF"):
            out_bsdf = group_out.inputs.get("Hook_BSDF")
            if out_bsdf:
                bsdf_out = pn.outputs.get("BSDF") if getattr(pn, "outputs", None) else None
                if bsdf_out:
                    try:
                        ng.links.new(bsdf_out, out_bsdf)
                    except Exception:
                        pass
        for src_in, (hook_name, socket_type) in mapping.items():
            try:
                src_sock = pn.inputs.get(src_in)
            except Exception:
                src_sock = None
            if not src_sock:
                continue
            if not _ensure_tree_socket(ng, "OUTPUT", socket_type, hook_name):
                continue
            out_sock = group_out.inputs.get(hook_name)
            if out_sock and src_sock.is_linked:
                try:
                    ng.links.new(src_sock.links[0].from_socket, out_sock)
                except Exception:
                    pass
            elif out_sock:
                try:
                    out_sock.default_value = src_sock.default_value
                except Exception:
                    pass

    return ng


def _create_ao_mask(tree, location=(-200, -400)):
    ao = tree.nodes.new(type="ShaderNodeAmbientOcclusion")
    ao.location = location
    ramp = tree.nodes.new(type="ShaderNodeValToRGB")
    ramp.location = (location[0] + 220, location[1])
    tree.links.new(ao.outputs.get("AO"), ramp.inputs.get("Fac"))
    return ramp.outputs.get("Alpha") or ramp.outputs.get("Color")


def _mix_input(tree, base_socket, overlay_socket, fac_socket, location):
    mix = tree.nodes.new(type="ShaderNodeMix")
    mix.location = location
    try:
        mix.data_type = "RGBA"
    except Exception:
        pass
    if fac_socket:
        tree.links.new(fac_socket, mix.inputs.get("Factor"))
    if base_socket:
        tree.links.new(base_socket, mix.inputs.get("A"))
    if overlay_socket:
        tree.links.new(overlay_socket, mix.inputs.get("B"))
    return mix.outputs.get("Result")


def _mix_float(tree, base_socket, overlay_socket, fac_socket, location):
    mix = tree.nodes.new(type="ShaderNodeMix")
    mix.location = location
    try:
        mix.data_type = "FLOAT"
    except Exception:
        pass
    if fac_socket:
        tree.links.new(fac_socket, mix.inputs.get("Factor"))
    if base_socket:
        tree.links.new(base_socket, mix.inputs.get("A"))
    if overlay_socket:
        tree.links.new(overlay_socket, mix.inputs.get("B"))
    return mix.outputs.get("Result")


def inject_node_group_into_material(
    material: bpy.types.Material,
    node_group: bpy.types.NodeTree,
    slot_role: str = "Base",
    relation: str = "base",
    mask_hints=None,
    use_external_mapping: bool = True,
    context=None,
):
    if not material or not material.use_nodes or not material.node_tree:
        return False

    tree = material.node_tree
    out_node = _get_or_create_output(tree)

    mapping = _ensure_mapping_chain(tree) if use_external_mapping or relation == "overlay" else None

    group_node = tree.nodes.new(type="ShaderNodeGroup")
    group_node.node_tree = node_group
    group_node.label = f"{slot_role}: {node_group.name}"
    group_node.name = f"MC_{slot_role}_{node_group.name}"
    group_node.location = (-350, 0 if slot_role == "Base" else -220)

    if use_external_mapping and mapping:
        for inp_name in ("Vector", "UV", "Mapping"):
            inp = group_node.inputs.get(inp_name)
            if inp and not inp.is_linked:
                tree.links.new(mapping.outputs.get("Vector"), inp)
                break

    fac = None
    if relation == "overlay":
        fac = _mask_fac_socket(tree, mapping, mask_hints, location=(-350, -520), context=context)
        if not fac:
            fac = _create_ao_mask(tree, location=(-350, -520))

    bsdf_out = group_node.outputs.get("Hook_BSDF")
    if bsdf_out:
        surface = out_node.inputs.get("Surface") if out_node else None
        if surface:
            if relation == "overlay" and surface.is_linked:
                base_link = surface.links[0]
                base_socket = base_link.from_socket
                tree.links.remove(base_link)
                mix = tree.nodes.new(type="ShaderNodeMixShader")
                mix.location = (120, -120 if slot_role != "Base" else 0)
                fac_in = mix.inputs.get("Fac") or mix.inputs.get("Factor")
                if fac_in and fac:
                    tree.links.new(fac, fac_in)
                try:
                    tree.links.new(base_socket, mix.inputs[1])
                except Exception:
                    pass
                try:
                    tree.links.new(bsdf_out, mix.inputs[2])
                except Exception:
                    pass
                tree.links.new(mix.outputs.get("Shader"), surface)
            else:
                if surface.is_linked:
                    tree.links.remove(surface.links[0])
                tree.links.new(bsdf_out, surface)
        return True

    _principled, _out = ensure_master_shader(tree, create_principled=True)
    for hook_out, principled_in in HOOK_OUTPUT_TO_PRINCIPLED_INPUT.items():
        out_socket = group_node.outputs.get(hook_out)
        if not out_socket:
            continue
        in_socket = _principled.inputs.get(principled_in)
        if not in_socket:
            continue

        if relation == "overlay" and in_socket.is_linked:
            base_link = in_socket.links[0]
            base_socket = base_link.from_socket
            tree.links.remove(base_link)
            if in_socket.type == "RGBA":
                mixed = _mix_input(tree, base_socket, out_socket, fac, location=(0, in_socket.node.location.y - 220))
            else:
                mixed = _mix_float(tree, base_socket, out_socket, fac, location=(0, in_socket.node.location.y - 220))
            tree.links.new(mixed, in_socket)
        else:
            if in_socket.is_linked:
                tree.links.remove(in_socket.links[0])
            tree.links.new(out_socket, in_socket)

    return True


def apply_library_entry_to_object_material(
    context, entry: dict, slot_role: str = "Base", relation: str = "base", slot_spec: dict = None, use_external_mapping: bool = True
):
    obj = getattr(context, "active_object", None)
    if not obj or obj.type != "MESH":
        return False

    def _ensure_target_material(reset: bool):
        existing = obj.data.materials[0] if getattr(obj.data, "materials", None) and obj.data.materials else None
        if existing and str(existing.name).startswith("MatComposer_Assembled"):
            mat_local = existing
            mat_local.use_nodes = True
        else:
            mat_local = bpy.data.materials.new(name="MatComposer_Assembled")
            mat_local.use_nodes = True
            try:
                obj.data.materials.clear()
            except Exception:
                pass
            obj.data.materials.append(mat_local)

        if reset:
            tree = getattr(mat_local, "node_tree", None)
            if tree:
                try:
                    tree.nodes.clear()
                except Exception:
                    pass
        return mat_local

    full_path = entry.get("full_path")
    name = entry.get("name")
    if not full_path or not name:
        return False

    lib_mat, lib_mat_temp = _append_material(full_path, name)
    if not lib_mat:
        return False

    if not getattr(lib_mat, "use_nodes", False) or not getattr(lib_mat, "node_tree", None):
        if lib_mat_temp:
            try:
                bpy.data.materials.remove(lib_mat, do_unlink=True)
            except Exception:
                pass
        return False

    is_reset = str(slot_role) == "Base" and str(relation) == "base"
    mat = _ensure_target_material(reset=is_reset)

    ng = _material_to_node_group(lib_mat, group_name=f"MC_{slot_role}_{lib_mat.name}")
    if lib_mat_temp:
        try:
            bpy.data.materials.remove(lib_mat, do_unlink=True)
        except Exception:
            pass
    if not ng:
        return False
    mask_hints = []
    if slot_role:
        mask_hints.append(str(slot_role))
    if isinstance(slot_spec, dict):
        mask_pref = str(slot_spec.get("mask") or "").strip()
        if mask_pref:
            mask_hints.append(mask_pref)
        concept = slot_spec.get("concept") or slot_spec.get("label") or ""
        if concept:
            mask_hints.append(str(concept))
        stags = slot_spec.get("tags") or []
        if isinstance(stags, (list, tuple)):
            mask_hints.extend([str(t) for t in stags if str(t).strip()])
    if isinstance(entry, dict):
        if entry.get("name"):
            mask_hints.append(str(entry.get("name")))
        etags = entry.get("tags") or []
        if isinstance(etags, (list, tuple)):
            mask_hints.extend([str(t) for t in etags if str(t).strip()])

    return inject_node_group_into_material(
        mat,
        ng,
        slot_role=slot_role,
        relation=relation,
        mask_hints=mask_hints,
        use_external_mapping=use_external_mapping,
        context=context,
    )
