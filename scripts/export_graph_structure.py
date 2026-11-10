# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

from __future__ import annotations

import os
import sys
import json
import argparse
from typing import List, Dict, Any

try:
    import bpy
except ImportError:
    print("Error: The 'bpy' module is required to run this script.")
    print("Please either:")
    print("1. Run this script using Blender's Python: blender -b -P scripts/export_graph_structure.py")
    print("2. Or install 'bpy' in your Python environment: pip install bpy (Requires Python 3.10/3.11)")
    sys.exit(1)

if not hasattr(bpy, "types"):
    print("Error: Detected an incomplete/dummy 'bpy' module in current Python environment.")
    print("Please run this script with Blender:")
    print('  blender --background --python scripts/export_graph_structure.py -- --input <path> --output <path>')
    sys.exit(1)

def get_args():
    parser = argparse.ArgumentParser()
    # Blender passes arguments after "--"
    if "--" in sys.argv:
        argv = sys.argv[sys.argv.index("--") + 1:]
    else:
        # Standard python usage: python script.py --input ...
        argv = sys.argv[1:]

    parser.add_argument("--input", required=True, help="Input .blend file or directory")
    parser.add_argument("--output", required=True, help="Output JSON path")
    return parser.parse_args(argv)

def extract_node_graph(node_tree: bpy.types.NodeTree) -> Dict[str, Any]:
    nodes_data = []
    links_data = []

    # Map node names to indices for compact storage
    node_name_to_idx = {}

    # 1. Collect Nodes
    for i, node in enumerate(node_tree.nodes):
        node_name_to_idx[node.name] = i

        # Basic info
        n_info = {
            "id": i,
            "type": node.bl_idname,
            "name": node.name,
            "label": node.label,
        }

        # Specific parameters can be added here if needed for finer granularity
        # e.g., operation types for Math nodes
        if node.bl_idname == "ShaderNodeMath":
            n_info["operation"] = node.operation
        elif node.bl_idname == "ShaderNodeVectorMath":
            n_info["operation"] = node.operation
        elif node.bl_idname == "ShaderNodeMixRGB":
            n_info["blend_type"] = node.blend_type

        nodes_data.append(n_info)

    # 2. Collect Links
    for link in node_tree.links:
        if not link.is_valid:
            continue

        from_idx = node_name_to_idx.get(link.from_node.name)
        to_idx = node_name_to_idx.get(link.to_node.name)

        if from_idx is not None and to_idx is not None:
            links_data.append({
                "u": from_idx,
                "v": to_idx,
                "from_socket": link.from_socket.name,
                "to_socket": link.to_socket.name
            })

    return {
        "nodes": nodes_data,
        "links": links_data
    }

def process_blend_file(filepath: str, root_dir: str) -> List[Dict[str, Any]]:
    results = []

    # Normalize path
    filepath = os.path.abspath(filepath)

    # Calculate relative path for Group:Name key generation
    try:
        rel_path = os.path.relpath(filepath, root_dir)
    except ValueError:
        rel_path = os.path.basename(filepath)

    group_name = os.path.dirname(rel_path).replace(os.sep, "/")
    if group_name == ".":
        group_name = ""


    # Check if we are processing the current file
    is_current_file = (bpy.data.filepath == filepath)

    materials_to_process = []
    temp_loaded_materials = []

    if is_current_file:
        materials_to_process = [m for m in bpy.data.materials if m.use_nodes and m.node_tree]
    else:
        # Use libraries.load to inspect external file without opening it
        # This is safe to run inside an active Blender session
        try:
            with bpy.data.libraries.load(filepath) as (data_from, data_to):
                # Only load material names first to check existence
                # Actually, to access node tree, we MUST append the material
                # data_to.materials = data_from.materials loads them into current file
                data_to.materials = data_from.materials

            # Filter loaded materials
            for mat in data_to.materials:
                if mat and mat.use_nodes and mat.node_tree:
                    materials_to_process.append(mat)
                    temp_loaded_materials.append(mat)

        except Exception as e:
            print(f"Error loading library {filepath}: {e}")
            return []

    # Iterate over materials
    for mat in materials_to_process:
        if not mat: continue

        key = f"{group_name}:{mat.name}" if group_name else mat.name

        print(f"Processing material: {key}")

        try:
            graph_data = extract_node_graph(mat.node_tree)
            graph_data["key"] = key
            graph_data["file_path"] = filepath
            results.append(graph_data)
        except Exception as e:
            print(f"Error extracting graph for {mat.name}: {e}")

    # Cleanup temporary materials
    if temp_loaded_materials:
        for mat in temp_loaded_materials:
            bpy.data.materials.remove(mat, do_unlink=True, do_id_user=True, do_ui_user=True)

    return results

def main():
    args = get_args()
    input_path = os.path.abspath(args.input)
    output_path = os.path.abspath(args.output)
    if not os.path.exists(input_path):
        raise SystemExit(f"Input does not exist: {input_path}")

    data_out = []

    if os.path.isfile(input_path):
        root_dir = os.path.dirname(input_path)
        data_out.extend(process_blend_file(input_path, root_dir))
    elif os.path.isdir(input_path):
        root_dir = input_path
        for root, dirs, files in os.walk(input_path):
            for f in files:
                if f.lower().endswith(".blend"):
                    full_path = os.path.join(root, f)
                    data_out.extend(process_blend_file(full_path, root_dir))


    # Save output
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data_out, f, indent=2)

    print(f"Saved graph data to {output_path}")

if __name__ == "__main__":
    main()
