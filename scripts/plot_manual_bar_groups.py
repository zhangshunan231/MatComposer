# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

from __future__ import annotations

import argparse
import json
import os
import sys
import textwrap
from colorsys import rgb_to_hls, hls_to_rgb


DEFAULT_SEMANTIC_GROUPS = [
    {
        "title": "Material Category",
        "labels": ["Metal", "Stone", "Wood", "Brick", "Concrete"],
        "values": [78, 72, 39, 31, 24],
        "color": "#7690B8",
    },
    {
        "title": "Stylistic Attribute",
        "labels": ["Realistic", "Natural", "Sci-fi", "Toon", "Stylized"],
        "values": [128, 84, 39, 32, 19],
        "color": "#79A171",
    },
    {
        "title": "Surface State",
        "labels": ["Weathered", "Clean", "Rust", "Wet", "Aged"],
        "values": [72, 61, 33, 24, 18],
        "color": "#B8838B",
    },
    {
        "title": "Physical Perception",
        "labels": ["Rough", "Matte", "Glossy", "Glowing", "Translucent"],
        "values": [84, 63, 51, 14, 11],
        "color": "#6DA9AA",
    },
    {
        "title": "Usage Scenario",
        "labels": ["Floor", "Wall", "Terrain", "Prop", "Facade"],
        "values": [76, 57, 28, 19, 13],
        "color": "#CCA75E",
    },
]

DEFAULT_STRUCTURAL_GROUPS = [
    {
        "title": "NodeCount",
        "labels": ["20-30", "30-40", "40-50", "50-60", "Others"],
        "values": [34, 92, 141, 97, 52],
        "color": "#7690B8",
    },
    {
        "title": "Depth",
        "labels": ["30-40", "40-50", "50-60", "60-70", "Others"],
        "values": [48, 126, 132, 74, 36],
        "color": "#79A171",
    },
    {
        "title": "Branching",
        "labels": ["40-50", "50-60", "60-70", "70-80", "Others"],
        "values": [86, 154, 108, 42, 26],
        "color": "#B8838B",
    },
    {
        "title": "Path Dom.",
        "labels": ["30-40", "40-50", "50-60", "60-70", "Others"],
        "values": [44, 118, 136, 79, 39],
        "color": "#6DA9AA",
    },
    {
        "title": "ProcRatio",
        "labels": ["0-10", "10-20", "20-30", "30-40", "Others"],
        "values": [168, 129, 71, 31, 17],
        "color": "#CCA75E",
    },
]


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Plot grouped bar charts from manually provided data."
    )
    ap.add_argument(
        "--groups-json",
        default="",
        help=(
            "JSON array of semantic groups. "
            'Example: [{"title":"Category","labels":["Metal","Stone"],"values":[110,90]}]'
        ),
    )
    ap.add_argument(
        "--structural-groups-json",
        default="",
        help=(
            "JSON array of structural groups. "
            'Example: [{"title":"NodeCount","labels":["20-30","30-40"],"values":[22,73]}]'
        ),
    )
    ap.add_argument("--output", default="", help="Output PNG path for semantic plot")
    ap.add_argument("--structural-output", default="", help="Output PNG path for structural plot")
    ap.add_argument("--height", type=float, default=2.8, help="Figure height in inches")
    ap.add_argument("--width", type=float, default=15.5, help="Figure width in inches")
    ap.add_argument("--dpi", type=int, default=300, help="Figure DPI")
    ap.add_argument("--label-width", type=int, default=9, help="Wrapped label width")
    argv = sys.argv[1:]
    if not argv:
        default_output = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "material_cache", "semantic_stats.png")
        )
        default_structural_output = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "material_cache", "structural_stats.png")
        )
        return argparse.Namespace(
            groups_json=json.dumps(DEFAULT_SEMANTIC_GROUPS, ensure_ascii=False),
            structural_groups_json=json.dumps(DEFAULT_STRUCTURAL_GROUPS, ensure_ascii=False),
            output=default_output,
            structural_output=default_structural_output,
            height=2.8,
            width=15.5,
            dpi=180,
            label_width=9,
        )
    return ap.parse_args(argv)


def _ensure_matplotlib():
    try:
        import matplotlib.pyplot as plt
    except Exception as e:
        raise SystemExit(f"matplotlib is required: {e}")
    return plt


def _wrap_label(text: str, width: int = 10) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    return s


def _hex_to_rgb01(color: str) -> tuple[float, float, float]:
    s = str(color or "").strip().lstrip("#")
    if len(s) != 6:
        return (0.5, 0.5, 0.5)
    try:
        return (int(s[0:2], 16) / 255.0, int(s[2:4], 16) / 255.0, int(s[4:6], 16) / 255.0)
    except Exception:
        return (0.5, 0.5, 0.5)


def _rgb01_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = rgb
    return "#{:02x}{:02x}{:02x}".format(
        max(0, min(255, int(round(r * 255)))),
        max(0, min(255, int(round(g * 255)))),
        max(0, min(255, int(round(b * 255)))),
    )


def _gradient_colors(base_color: str, count: int) -> list[str]:
    if count <= 1:
        return [base_color]
    r, g, b = _hex_to_rgb01(base_color)
    h, l, s = rgb_to_hls(r, g, b)
    start_l = min(0.96, max(0.78, l + 0.28))
    end_l = max(0.20, min(0.36, l - 0.16))
    colors: list[str] = []
    for idx in range(count):
        t = idx / max(1, count - 1)
        curr_l = start_l + (end_l - start_l) * t
        curr_s = max(0.22, min(0.72, s * (0.88 + 0.24 * (1.0 - t))))
        colors.append(_rgb01_to_hex(hls_to_rgb(h, curr_l, curr_s)))
    return colors


def _load_groups(raw: str) -> list[dict]:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise SystemExit(f"Invalid JSON for --groups-json: {e}")
    if not isinstance(data, list) or not data:
        raise SystemExit("--groups-json must be a non-empty JSON array")

    out: list[dict] = []
    default_colors = [
        "#8ea3b9",
        "#8d9b7d",
        "#a27f83",
        "#a38b62",
        "#7b9693",
        "#7d7b9c",
    ]
    for idx, item in enumerate(data):
        if not isinstance(item, dict):
            raise SystemExit(f"Group #{idx + 1} must be an object")
        title = str(item.get("title", "")).strip() or f"Group {idx + 1}"
        labels = item.get("labels")
        values = item.get("values")
        if not isinstance(labels, list) or not isinstance(values, list):
            raise SystemExit(f'Group "{title}" must contain list fields "labels" and "values"')
        if len(labels) != len(values) or not labels:
            raise SystemExit(f'Group "{title}" must have equal non-zero lengths for labels and values')
        try:
            values = [int(v) for v in values]
        except Exception:
            raise SystemExit(f'Group "{title}" contains non-integer values')
        color = str(item.get("color") or default_colors[idx % len(default_colors)])
        out.append({"title": title, "labels": [str(x) for x in labels], "values": values, "color": color})
    return out


def _plot_groups(groups: list[dict], out_path: str, width: float, height: float, dpi: int, label_width: int) -> None:
    plt = _ensure_matplotlib()

    fig, ax = plt.subplots(figsize=(width, height), dpi=dpi)
    x_positions = []
    heights = []
    labels = []
    colors = []
    centers = []

    cursor = 0.0
    gap = 1.3
    for group in groups:
        start = cursor
        group_colors = _gradient_colors(group["color"], len(group["labels"]))
        for label, value, bar_color in zip(group["labels"], group["values"], group_colors):
            x_positions.append(cursor)
            heights.append(int(value))
            labels.append(_wrap_label(label, width=label_width))
            colors.append(bar_color)
            cursor += 1.0
        end = cursor - 1.0
        centers.append(((start + end) * 0.5, group["title"]))
        cursor += gap

    max_height = max(heights or [1])
    ax.axhline(0, color="#727272", linewidth=0.9, zorder=0)
    ax.bar(x_positions, heights, color=colors, width=0.68, edgecolor="none", alpha=0.95)
    for x, h in zip(x_positions, heights):
        ax.text(x, h + max(1, int(max_height * 0.02)), str(h), ha="center", va="bottom", fontsize=8.5)

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, fontsize=9, rotation=30, ha="center")
    ax.tick_params(axis="x", length=0, pad=2)
    ax.tick_params(axis="y", length=0, labelleft=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_ylim(0, max_height * 1.18)
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    for center_x, title in centers:
        ax.text(center_x, -0.4, title, ha="center", va="top", fontsize=11, transform=ax.get_xaxis_transform())

    plt.subplots_adjust(left=0.02, right=0.995, top=0.88, bottom=0.46)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def main() -> None:
    args = _parse_args()
    semantic_groups = _load_groups(args.groups_json or json.dumps(DEFAULT_SEMANTIC_GROUPS, ensure_ascii=False))
    structural_groups = _load_groups(
        args.structural_groups_json or json.dumps(DEFAULT_STRUCTURAL_GROUPS, ensure_ascii=False)
    )
    semantic_output = os.path.abspath(
        args.output or os.path.join(os.path.dirname(__file__), "..", "material_cache", "manual_semantic_stats.png")
    )
    structural_output = os.path.abspath(
        args.structural_output
        or os.path.join(os.path.dirname(__file__), "..", "material_cache", "manual_structural_stats.png")
    )
    _plot_groups(
        groups=semantic_groups,
        out_path=semantic_output,
        width=float(args.width),
        height=float(args.height),
        dpi=int(args.dpi),
        label_width=int(args.label_width),
    )
    _plot_groups(
        groups=structural_groups,
        out_path=structural_output,
        width=float(args.width),
        height=float(args.height),
        dpi=int(args.dpi),
        label_width=int(args.label_width),
    )
    print(f"Wrote: {semantic_output}")
    print(f"Wrote: {structural_output}")


if __name__ == "__main__":
    main()
