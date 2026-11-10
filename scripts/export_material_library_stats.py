# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from typing import Any

try:
    import bpy
except ImportError:
    print("Error: bpy is required. Run this script with Blender.")
    sys.exit(1)


STRUCTURAL_BINS = [0, 20, 30, 40, 50, 60, 70, 80, 101]


def _repo_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _extract_script_argv(argv: list[str]) -> list[str]:
    if "--" in argv:
        return argv[argv.index("--") + 1 :]
    return list(argv[1:])


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Blend file or directory")
    ap.add_argument("--output", required=True, help="Output JSON path")
    return ap.parse_args(_extract_script_argv(sys.argv))


def _load_semantic_init():
    repo_root = _repo_root()
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from utils import semantic_init

    return semantic_init


def _collect_blend_files(input_path: str) -> list[str]:
    path = os.path.abspath(input_path)
    if os.path.isfile(path):
        return [path]
    out: list[str] = []
    for root, _dirs, files in os.walk(path):
        for fn in files:
            if fn.lower().endswith(".blend"):
                out.append(os.path.join(root, fn))
    out.sort()
    return out


def _tag_buckets(tags: list[str]) -> dict[str, list[str]]:
    buckets = {
        "category": [],
        "stylistic": [],
        "state": [],
        "perception": [],
        "usage": [],
    }
    prefix_map = {
        "cat": "category",
        "category": "category",
        "type": "category",
        "substrate": "category",
        "style": "stylistic",
        "look": "stylistic",
        "state": "state",
        "surface": "state",
        "feel": "perception",
        "phys": "perception",
        "physical": "perception",
        "use": "usage",
        "usage": "usage",
        "scene": "usage",
        "context": "usage",
    }
    seen = {k: set() for k in buckets}
    for raw in tags:
        s = str(raw or "").strip().lower()
        if ":" not in s:
            continue
        prefix, value = s.split(":", 1)
        key = prefix_map.get(prefix.strip().lower())
        value = value.strip().lower()
        if not key or not value or value in seen[key]:
            continue
        seen[key].add(value)
        buckets[key].append(value)
    return buckets


def _bucket_label(value_pct: float) -> str:
    value_pct = max(0.0, min(100.0, float(value_pct)))
    for start, end in zip(STRUCTURAL_BINS[:-1], STRUCTURAL_BINS[1:]):
        if start <= value_pct < end:
            end_label = 100 if end >= 101 else end
            return f"{start}-{end_label}"
    return "80-100"


def _summarize_topology(semantic_init: Any, node_tree: Any) -> dict[str, float]:
    topo = semantic_init.build_k_topology_from_node_tree(node_tree)
    rep = semantic_init.MaterialRepresentation(
        raw_text="",
        tags=(),
        slots=(),
        s_vector=(),
        k_topology=topo,
    )
    vec = semantic_init.get_structural_vector(rep)
    return {
        "NodeCount": float(vec[0]) if len(vec) > 0 else 0.0,
        "Depth": float(vec[1]) if len(vec) > 1 else 0.0,
        "Branching": float(vec[2]) if len(vec) > 2 else 0.0,
        "Path Dom.": float(vec[3]) if len(vec) > 3 else 0.0,
        "ProcRatio": float(vec[4]) if len(vec) > 4 else 0.0,
        "MathRatio": float(vec[5]) if len(vec) > 5 else 0.0,
    }


def _process_blend_file(filepath: str, semantic_init: Any) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    existing_names = {m.name for m in bpy.data.materials}
    data_to = None
    try:
        with bpy.data.libraries.load(filepath, link=False, assets_only=False) as (data_from, data_to):
            data_to.materials = list(getattr(data_from, "materials", []) or [])
        loaded_mats = list(getattr(data_to, "materials", []) or [])
        for mat in loaded_mats:
            if not mat or not getattr(mat, "use_nodes", False) or not getattr(mat, "node_tree", None):
                continue
            asset_tags: list[str] = []
            try:
                asset_tags = [str(t.name) for t in getattr(getattr(mat, "asset_data", None), "tags", [])]
            except Exception:
                asset_tags = []
            buckets = _tag_buckets(asset_tags)
            structural = _summarize_topology(semantic_init, mat.node_tree)
            results.append(
                {
                    "name": str(getattr(mat, "name", "") or ""),
                    "file_path": os.path.abspath(filepath),
                    "asset_tags": asset_tags,
                    "style_semantics": buckets,
                    "structural": structural,
                }
            )
    finally:
        loaded_mats = list(getattr(data_to, "materials", []) or []) if data_to else []
        for mat in loaded_mats:
            try:
                if mat and mat.name not in existing_names:
                    bpy.data.materials.remove(mat, do_unlink=True)
            except Exception:
                pass
    return results


def main() -> None:
    args = _parse_args()
    semantic_init = _load_semantic_init()

    blend_files = _collect_blend_files(args.input)
    if not blend_files:
        raise SystemExit(f"No blend files found under: {args.input}")

    semantic_counts = {
        "category": Counter(),
        "stylistic": Counter(),
        "state": Counter(),
        "perception": Counter(),
        "usage": Counter(),
    }
    structural_counts = {
        "NodeCount": Counter(),
        "Depth": Counter(),
        "Branching": Counter(),
        "Path Dom.": Counter(),
        "ProcRatio": Counter(),
        "MathRatio": Counter(),
    }
    materials: list[dict[str, Any]] = []

    for blend_file in blend_files:
        print(f"Scanning: {blend_file}")
        file_items = _process_blend_file(blend_file, semantic_init)
        materials.extend(file_items)
        for item in file_items:
            for dim, values in item["style_semantics"].items():
                semantic_counts[dim].update(values)
            for dim, value in item["structural"].items():
                structural_counts[dim].update([_bucket_label(float(value) * 100.0)])

    payload = {
        "source": os.path.abspath(args.input),
        "total_materials": len(materials),
        "style_semantics": {k: dict(v.most_common()) for k, v in semantic_counts.items()},
        "structural_distribution": {k: dict(v) for k, v in structural_counts.items()},
        "structural_bins": [f"{a}-{100 if b >= 101 else b}" for a, b in zip(STRUCTURAL_BINS[:-1], STRUCTURAL_BINS[1:])],
        "materials": materials,
    }

    out_path = os.path.abspath(args.output)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"Wrote: {out_path}")


if __name__ == "__main__":
    main()
