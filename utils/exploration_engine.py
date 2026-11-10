# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .semantic_init import (
    DEFAULT_EMBED_DIM,
    MaterialRepresentation,
    add,
    dot,
    embed_text,
    euclidean,
    sub,
    vector_norm,
)


@dataclass(frozen=True)
class ExplorationCandidate:
    entry_id: str
    name: str
    asset_type: str
    score: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.entry_id,
            "name": self.name,
            "asset_type": self.asset_type,
            "score": self.score,
        }


def _entry_text(entry: Dict[str, Any]) -> str:
    name = str(entry.get("name") or "")
    desc = str(entry.get("description") or "")
    tags = entry.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    def _expand_tag(t: Any) -> str:
        s = str(t or "").strip()
        if not s:
            return ""
        if ":" not in s:
            return s
        prefix, value = s.split(":", 1)
        prefix = prefix.strip().lower()
        value = value.strip()
        if not value:
            return ""
        w = 1
        if prefix in ("cat", "category", "type", "substrate"):
            # Category/substrate should dominate retrieval because it defines
            # the material family more strongly than state/style modifiers.
            w = 8
        elif prefix in ("state", "surface"):
            w = 3
        elif prefix in ("style", "look"):
            w = 2
        elif prefix in ("feel", "phys", "physical"):
            w = 2
        elif prefix in ("use", "usage", "scene", "context"):
            w = 2
        return " ".join([value] * w)

    expanded = []
    for t in tags:
        out = _expand_tag(t)
        if out:
            expanded.append(out)
    tags_str = " ".join(expanded)
    return f"{name} {desc} {tags_str}".strip()


def entry_text(entry: Dict[str, Any]) -> str:
    return _entry_text(entry)


def representation_from_entry(entry: Dict[str, Any], dim: int = DEFAULT_EMBED_DIM) -> MaterialRepresentation:
    text = _entry_text(entry)
    rep = MaterialRepresentation(
        raw_text=text,
        tags=tuple(),
        slots=tuple(),
        s_vector=tuple(_entry_vec(entry, dim=dim)),
        k_topology={},
    )
    return rep


def _entry_vec(entry: Dict[str, Any], dim: int = DEFAULT_EMBED_DIM) -> List[float]:
    text = _entry_text(entry)
    cached = entry.get("_mc_sem_vec")
    if isinstance(cached, list) and cached and all(isinstance(x, (int, float)) for x in cached):
        cached_src = entry.get("_mc_sem_vec_src")
        cached_dim = entry.get("_mc_sem_vec_dim")
        if len(cached) == dim and cached_src == text and cached_dim == dim:
            return [float(x) for x in cached]
    v = embed_text(text, dim=dim)
    entry["_mc_sem_vec"] = v
    entry["_mc_sem_vec_src"] = text
    entry["_mc_sem_vec_dim"] = dim
    return v


def entry_vector(entry: Dict[str, Any], dim: int = DEFAULT_EMBED_DIM) -> List[float]:
    return _entry_vec(entry, dim=dim)


def local_exploration(
    query: MaterialRepresentation,
    entries: Iterable[Dict[str, Any]],
    top_k: int = 8,
    dim: int = DEFAULT_EMBED_DIM,
    allowed_asset_types: Optional[Tuple[str, ...]] = None,
) -> List[ExplorationCandidate]:
    qv = list(query.s_vector)
    scored: List[ExplorationCandidate] = []
    for e in entries:
        asset_type = str(e.get("asset_type") or "MATERIAL")
        if allowed_asset_types and asset_type not in allowed_asset_types:
            continue
        v = _entry_vec(e, dim=dim)
        d = euclidean(qv, v)
        score = -d
        scored.append(
            ExplorationCandidate(
                entry_id=str(e.get("id") or ""),
                name=str(e.get("name") or ""),
                asset_type=asset_type,
                score=score,
            )
        )
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[: max(1, int(top_k))]


def directional_exploration(
    prev: MaterialRepresentation,
    curr: MaterialRepresentation,
    entries: Iterable[Dict[str, Any]],
    top_k: int = 8,
    dim: int = DEFAULT_EMBED_DIM,
    locked_roles: Optional[Tuple[str, ...]] = None,
    allowed_asset_types: Optional[Tuple[str, ...]] = None,
) -> List[ExplorationCandidate]:
    pv = list(prev.s_vector)
    cv = list(curr.s_vector)
    direction = sub(cv, pv)
    dir_n = vector_norm(direction)
    if dir_n <= 1e-8:
        return local_exploration(curr, entries, top_k=top_k, dim=dim, allowed_asset_types=allowed_asset_types)

    target = add(cv, direction, scale_b=1.0)

    lock_tags: List[str] = []
    if locked_roles:
        for s in curr.slots:
            if s.role in locked_roles:
                lock_tags.extend(list(s.tags))
    lock_vec = embed_text(" ".join(lock_tags), dim=dim) if lock_tags else None

    scored: List[ExplorationCandidate] = []
    for e in entries:
        asset_type = str(e.get("asset_type") or "MATERIAL")
        if allowed_asset_types and asset_type not in allowed_asset_types:
            continue
        ev = _entry_vec(e, dim=dim)

        proj = dot(sub(ev, cv), direction) / (dir_n + 1e-8)
        dist_to_target = euclidean(ev, target)

        lock_penalty = 0.0
        if lock_vec is not None:
            ev_lock = embed_text(_entry_text(e), dim=dim)
            lock_penalty = euclidean(ev_lock, lock_vec) * 0.75

        score = proj - 0.35 * dist_to_target - lock_penalty
        scored.append(
            ExplorationCandidate(
                entry_id=str(e.get("id") or ""),
                name=str(e.get("name") or ""),
                asset_type=asset_type,
                score=score,
            )
        )
    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[: max(1, int(top_k))]


def pick_top_n_ids(candidates: List[ExplorationCandidate], n: int = 4) -> List[str]:
    n = max(1, int(n))
    out: List[str] = []
    for c in candidates:
        if c.entry_id and c.entry_id not in out:
            out.append(c.entry_id)
        if len(out) >= n:
            break
    return out


def calculate_structural_penalty(
    entry_k_vec: List[float],
    target_k_vec: List[float],
    weights: Optional[List[float]] = None
) -> float:
    """
    Calculate weighted structural distance (penalty).
    k_vec dims: [NodeCount, Depth, Branching, Dominance, ProcRatio, MathRatio]
    """
    if not entry_k_vec or not target_k_vec:
        return 0.0

    # Ensure lengths match (pad with 0)
    dims = max(len(entry_k_vec), len(target_k_vec))
    e_vec = list(entry_k_vec) + [0.0] * (dims - len(entry_k_vec))
    t_vec = list(target_k_vec) + [0.0] * (dims - len(target_k_vec))

    if weights is None:
        # Default: Only consider Complexity (index 0) if weights not provided
        weights = [1.0] + [0.0] * (dims - 1)
    else:
        weights = list(weights) + [0.0] * (dims - len(weights))

    dist_sq = 0.0
    for i in range(dims):
        w = weights[i]
        if w <= 0:
            continue
        diff = e_vec[i] - t_vec[i]
        dist_sq += w * (diff * diff)

    return math.sqrt(dist_sq)
