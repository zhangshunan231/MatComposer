# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

from __future__ import annotations

import argparse
import json
import os
import textwrap
from collections import Counter


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="Stats JSON from export_material_library_stats.py")
    ap.add_argument("--output-dir", default="", help="Output directory for plots")
    ap.add_argument("--top-n", type=int, default=5, help="Top N labels per semantic dimension")
    return ap.parse_args()


def _load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError("Input JSON must be an object")
    return data


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
    return "\n".join(textwrap.wrap(s, width=width)) or s


def _top_n_plus_others(counts: dict[str, int] | Counter[str], top_n: int = 5) -> tuple[list[str], list[int]]:
    normalized = {str(k): int(v) for k, v in dict(counts).items() if int(v) > 0}
    items = sorted(normalized.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    top_items = items[: max(1, int(top_n))]
    other_sum = sum(v for _k, v in items[len(top_items) :])
    labels = [k for k, _v in top_items]
    values = [v for _k, v in top_items]
    if other_sum > 0:
        labels.append("Others")
        values.append(other_sum)
    while labels and len(labels) < top_n + 1:
        labels.append("")
        values.append(0)
    return labels, values


def _top_n_only(counts: dict[str, int] | Counter[str], top_n: int = 5) -> tuple[list[str], list[int]]:
    normalized = {str(k): int(v) for k, v in dict(counts).items() if int(v) > 0}
    items = sorted(normalized.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    top_items = items[: max(1, int(top_n))]
    labels = [k for k, _v in top_items]
    values = [v for _k, v in top_items]
    while labels and len(labels) < top_n:
        labels.append("")
        values.append(0)
    return labels, values


def _ordered_top_n_plus_others(labels: list[str], values: list[int], top_n: int = 4) -> tuple[list[str], list[int]]:
    pairs = [(str(label), int(value)) for label, value in zip(labels, values)]
    non_zero_pairs = [(label, value) for label, value in pairs if value > 0]
    if not non_zero_pairs:
        return [], []

    top_pairs = sorted(non_zero_pairs, key=lambda kv: (-kv[1], kv[0].lower()))[: max(1, int(top_n))]
    top_set = {label for label, _value in top_pairs}

    ordered_labels: list[str] = []
    ordered_values: list[int] = []
    others_total = 0
    for label, value in pairs:
        if value <= 0:
            continue
        if label in top_set:
            ordered_labels.append(label)
            ordered_values.append(value)
        else:
            others_total += value

    while len(ordered_labels) < top_n:
        ordered_labels.append("")
        ordered_values.append(0)
    ordered_labels.append("Others")
    ordered_values.append(others_total)
    return ordered_labels, ordered_values


def _structural_material_values(data: dict, dim_key: str) -> list[float]:
    values: list[float] = []
    for item in data.get("materials") or []:
        structural = item.get("structural") or {}
        if dim_key not in structural:
            continue
        try:
            values.append(float(structural[dim_key]) * 100.0)
        except Exception:
            continue
    return values


def _adaptive_structural_bins(values: list[float], bin_count: int = 6) -> tuple[list[str], list[int]]:
    if not values:
        return [], []

    lo = min(values)
    hi = max(values)
    if abs(hi - lo) < 1e-6:
        center = round(lo, 1)
        return [f"{center:g}"], [len(values)]

    span = hi - lo
    raw_step = span / max(1, int(bin_count))
    if raw_step <= 2:
        step = 2
    elif raw_step <= 5:
        step = 5
    elif raw_step <= 10:
        step = 10
    else:
        step = 20

    start = step * int(lo // step)
    if start > lo:
        start -= step
    end = step * int(hi // step)
    if end < hi:
        end += step
    if end <= start:
        end = start + step

    edges = list(range(int(start), int(end) + step, step))
    if len(edges) < 2:
        edges = [int(start), int(start + step)]

    counts: Counter[str] = Counter()
    labels: list[str] = []
    for a, b in zip(edges[:-1], edges[1:]):
        label = f"{a}-{b}"
        labels.append(label)
        counts[label] = 0

    for value in values:
        placed = False
        for a, b in zip(edges[:-1], edges[1:]):
            if a <= value < b:
                counts[f"{a}-{b}"] += 1
                placed = True
                break
        if not placed:
            counts[f"{edges[-2]}-{edges[-1]}"] += 1

    return labels, [counts[label] for label in labels]


def _fixed_step_bins(values: list[float], step: int, start: int = 0, end: int | None = None) -> tuple[list[str], list[int]]:
    if not values:
        return [], []

    max_value = max(values)
    if end is None:
        end = step * int(max_value // step)
        if end < max_value:
            end += step
        end = max(step, end)
    if end <= start:
        end = start + step

    edges = list(range(int(start), int(end) + step, step))
    if len(edges) < 2:
        edges = [int(start), int(start + step)]

    counts: Counter[str] = Counter()
    labels: list[str] = []
    for a, b in zip(edges[:-1], edges[1:]):
        label = f"{a}-{b}"
        labels.append(label)
        counts[label] = 0

    for value in values:
        placed = False
        for a, b in zip(edges[:-1], edges[1:]):
            if a <= value < b:
                counts[f"{a}-{b}"] += 1
                placed = True
                break
        if not placed:
            counts[f"{edges[-2]}-{edges[-1]}"] += 1

    return labels, [counts[label] for label in labels]


def _plot_semantic(data: dict, out_path: str, top_n: int) -> None:
    plt = _ensure_matplotlib()
    semantic = data.get("style_semantics") or {}
    dims = [
        ("category", "Material Category", "#8ea3b9"),
        ("stylistic", "Stylistic Attribute", "#8d9b7d"),
        ("state", "Surface State", "#a27f83"),
        ("perception", "Physical Perception", "#a38b62"),
        ("usage", "Usage Scenario", "#7b9693"),
    ]

    fig, ax = plt.subplots(figsize=(15.5, 2.7), dpi=180)
    x_positions = []
    heights = []
    labels = []
    colors = []
    centers = []

    cursor = 0.0
    gap = 1.3
    for dim_key, dim_title, color in dims:
        counts = semantic.get(dim_key) or {}
        labels_top, values_top = _top_n_only(counts, top_n=max(1, int(top_n)))
        start = cursor
        for label, count in zip(labels_top, values_top):
            x_positions.append(cursor)
            heights.append(int(count) if count > 0 else 0)
            labels.append(_wrap_label(label, width=9) if label else "")
            colors.append(color)
            cursor += 1.0
        end = cursor - 1.0
        centers.append(((start + end) * 0.5, dim_title))
        cursor += gap

    ax.bar(x_positions, heights, color=colors, width=0.68, edgecolor="none", alpha=0.95)
    for x, h in zip(x_positions, heights):
        ax.text(x, h + max(1, int(max(heights or [1]) * 0.02)), str(h), ha="center", va="bottom", fontsize=7)

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, fontsize=7)
    ax.tick_params(axis="x", length=0, pad=2)
    ax.tick_params(axis="y", length=0, labelleft=False)
    for spine in ax.spines.values():
        spine.set_visible(False)
    ax.set_ylim(0, max(heights or [1]) * 1.18)
    ax.set_facecolor("white")
    fig.patch.set_facecolor("white")

    for center_x, title in centers:
        ax.text(center_x, -0.38, title, ha="center", va="top", fontsize=9, transform=ax.get_xaxis_transform())

    plt.subplots_adjust(left=0.02, right=0.995, top=0.88, bottom=0.46)
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def _plot_structural(data: dict, out_path: str) -> None:
    plt = _ensure_matplotlib()
    dims = [
        ("NodeCount", "#8ea3b9"),
        ("Depth", "#8d9b7d"),
        ("Branching", "#a27f83"),
        ("Path Dom.", "#a38b62"),
        ("ProcRatio", "#7b9693"),
    ]

    fig, axes = plt.subplots(1, len(dims), figsize=(14.5, 2.5), dpi=180, sharey=True)
    if len(dims) == 1:
        axes = [axes]

    max_y = 1
    for dim_key, _color in dims:
        values = _structural_material_values(data, dim_key)
        raw_labels, raw_vals = _adaptive_structural_bins(values)
        _labels, vals = _ordered_top_n_plus_others(raw_labels, raw_vals, top_n=4)
        for v in vals:
            max_y = max(max_y, int(v))
    max_y = int(max_y * 1.2) if max_y > 0 else 1

    for ax, (dim_key, color) in zip(axes, dims):
        values = _structural_material_values(data, dim_key)
        raw_labels, raw_vals = _adaptive_structural_bins(values)
        labels, vals = _ordered_top_n_plus_others(raw_labels, raw_vals, top_n=4)
        xs = list(range(len(labels)))
        ax.bar(xs, vals, color=color, width=0.68, edgecolor="none", alpha=0.95)
        for x, v in zip(xs, vals):
            if v > 0:
                ax.text(x, v + 0.4, str(v), ha="center", va="bottom", fontsize=6)
        ax.set_title(dim_key, fontsize=8, pad=4)
        ax.set_xticks(xs)
        ax.set_xticklabels([_wrap_label(b, width=7) if b else "" for b in labels], fontsize=6)
        ax.tick_params(axis="x", length=0, pad=1)
        ax.tick_params(axis="y", length=0, labelleft=False)
        ax.set_ylim(0, max_y)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_facecolor("white")

    fig.patch.set_facecolor("white")
    plt.subplots_adjust(left=0.02, right=0.995, top=0.82, bottom=0.28, wspace=0.15)
    fig.savefig(out_path, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def main() -> None:
    args = _parse_args()
    data = _load_json(os.path.abspath(args.input))
    out_dir = str(args.output_dir or "").strip()
    if not out_dir:
        out_dir = os.path.dirname(os.path.abspath(args.input))
    out_dir = os.path.abspath(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    semantic_png = os.path.join(out_dir, "material_library_semantic_stats.png")
    structural_png = os.path.join(out_dir, "material_library_structural_stats.png")

    _plot_semantic(data, semantic_png, args.top_n)
    _plot_structural(data, structural_png)

    print(f"Wrote: {semantic_png}")
    print(f"Wrote: {structural_png}")


if __name__ == "__main__":
    main()
