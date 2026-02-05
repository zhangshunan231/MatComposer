import hashlib
import json
import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_EMBED_DIM = 64
MAX_SLOTS = 3


@dataclass(frozen=True)
class SlotSpec:
    role: str
    concept: str
    tags: Tuple[str, ...]
    relation: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "concept": self.concept,
            "tags": list(self.tags),
            "relation": self.relation,
        }


@dataclass(frozen=True)
class MaterialRepresentation:
    raw_text: str
    tags: Tuple[str, ...]
    slots: Tuple[SlotSpec, ...]
    s_vector: Tuple[float, ...]
    k_topology: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw_text": self.raw_text,
            "tags": list(self.tags),
            "slots": [s.to_dict() for s in self.slots],
            "S": list(self.s_vector),
            "K": self.k_topology,
        }


_token_re = re.compile(r"[A-Za-z0-9\u4e00-\u9fff]+", re.UNICODE)


def _tokenize(text: str) -> List[str]:
    if not text:
        return []
    return [t.lower() for t in _token_re.findall(text)]


def _stable_unit_hash(token: str) -> float:
    h = hashlib.sha256(token.encode("utf-8")).digest()
    x = int.from_bytes(h[:8], "big", signed=False)
    return (x / (2**64 - 1)) * 2.0 - 1.0


def embed_tokens(tokens: List[str], dim: int = DEFAULT_EMBED_DIM) -> List[float]:
    if dim <= 0:
        raise ValueError("dim must be positive")
    v = [0.0] * dim
    if not tokens:
        return v

    for tok in tokens:
        h = hashlib.sha256(tok.encode("utf-8")).digest()
        for i in range(0, 32, 2):
            idx = h[i] % dim
            sgn = 1.0 if (h[i + 1] & 1) == 0 else -1.0
            v[idx] += sgn * (0.5 + abs(_stable_unit_hash(tok)) * 0.5)
    return _l2_normalize(v)


def embed_text(text: str, dim: int = DEFAULT_EMBED_DIM) -> List[float]:
    return embed_tokens(_tokenize(text), dim=dim)


def _l2_normalize(v: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in v))
    if n <= 1e-12:
        return list(v)
    return [x / n for x in v]


def euclidean(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vector size mismatch")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def dot(a: List[float], b: List[float]) -> float:
    if len(a) != len(b):
        raise ValueError("Vector size mismatch")
    return sum(x * y for x, y in zip(a, b))


def sub(a: List[float], b: List[float]) -> List[float]:
    if len(a) != len(b):
        raise ValueError("Vector size mismatch")
    return [x - y for x, y in zip(a, b)]


def add(a: List[float], b: List[float], scale_b: float = 1.0) -> List[float]:
    if len(a) != len(b):
        raise ValueError("Vector size mismatch")
    return [x + y * scale_b for x, y in zip(a, b)]


def vector_norm(a: List[float]) -> float:
    return math.sqrt(sum(x * x for x in a))


def clamp_slot_count(n: int) -> int:
    return max(1, min(MAX_SLOTS, int(n)))


def build_slots_fallback(text: str, tags: List[str]) -> List[SlotSpec]:
    tokens = _tokenize(text)
    slots: List[SlotSpec] = []

    overlay_keywords = {"rust", "rusty", "dirt", "dust", "grime", "wet", "water", "snow", "moss", "paint", "scratch"}
    is_overlay = any(t in overlay_keywords for t in tokens)

    if is_overlay and len(tags) >= 2:
        base_tags = tuple(tags[: max(1, len(tags) // 2)])
        overlay_tags = tuple(tags[len(base_tags) :]) or tuple(tags[:2])
        slots.append(SlotSpec(role="Base", concept=base_tags[0], tags=base_tags, relation="base"))
        slots.append(SlotSpec(role="Overlay", concept=overlay_tags[0], tags=overlay_tags, relation="overlay"))
        return slots[:MAX_SLOTS]

    primary = tags[0] if tags else (tokens[0] if tokens else "material")
    slots.append(SlotSpec(role="Base", concept=primary, tags=tuple(tags)[:8], relation="base"))
    return slots


def build_representation_from_semantic_json(
    raw_text: str,
    semantic_json: Dict[str, Any],
    dim: int = DEFAULT_EMBED_DIM,
    k_topology: Optional[Dict[str, Any]] = None,
) -> MaterialRepresentation:
    tags = semantic_json.get("tags") or semantic_json.get("visual_tags") or []
    if not isinstance(tags, list):
        tags = []
    tags = [str(t).strip().lower() for t in tags if str(t).strip()]
    tags = list(dict.fromkeys(tags))

    slots_data = semantic_json.get("slots") or []
    slots: List[SlotSpec] = []
    if isinstance(slots_data, list):
        for s in slots_data[:MAX_SLOTS]:
            if not isinstance(s, dict):
                continue
            role = str(s.get("role") or "").strip() or "Base"
            concept = str(s.get("concept") or s.get("label") or "").strip() or role
            stags = s.get("tags") or []
            if not isinstance(stags, list):
                stags = []
            stags = [str(t).strip().lower() for t in stags if str(t).strip()]
            stags = list(dict.fromkeys(stags))[:12]
            relation = str(s.get("relation") or "").strip() or "base"
            slots.append(SlotSpec(role=role, concept=concept, tags=tuple(stags), relation=relation))

    if not slots:
        slots = build_slots_fallback(raw_text, tags)

    base_tokens = tags + _tokenize(raw_text)
    if base_tokens:
        base_tokens = list(dict.fromkeys(base_tokens))
    s_vec = embed_tokens(base_tokens or _tokenize(raw_text), dim=dim)
    return MaterialRepresentation(
        raw_text=raw_text,
        tags=tuple(tags),
        slots=tuple(slots),
        s_vector=tuple(s_vec),
        k_topology=k_topology or {},
    )


def build_k_topology_from_node_tree(node_tree: Any) -> Dict[str, Any]:
    if not node_tree:
        return {}
    nodes = getattr(node_tree, "nodes", None)
    links = getattr(node_tree, "links", None)
    if nodes is None or links is None:
        return {}

    type_counts: Dict[str, int] = {}
    group_nodes = 0
    tex_pattern_nodes = 0  # Procedural generators (Noise, Voronoi, ...)
    tex_image_nodes = 0    # Bitmap/Image textures
    math_nodes = 0         # Math / transform / mix density
    
    # Keyword sets for classification
    # Note: These are based on Blender's internal bl_idname
    procedural_keywords = {
        "ShaderNodeTexNoise", "ShaderNodeTexVoronoi", "ShaderNodeTexWave", 
        "ShaderNodeTexMusgrave", "ShaderNodeTexBrick", "ShaderNodeTexChecker", 
        "ShaderNodeTexGradient", "ShaderNodeTexMagic", "ShaderNodeTexWhiteNoise",
        "ShaderNodeTexGabor",
    }
    image_keywords = {"ShaderNodeTexImage", "ShaderNodeTexEnvironment"}
    math_keywords = {
        "ShaderNodeMath",
        "ShaderNodeVectorMath",
        "ShaderNodeMapRange",
        "ShaderNodeMix",
        "ShaderNodeMixRGB",
        "ShaderNodeMixShader",
        "ShaderNodeSeparateXYZ",
        "ShaderNodeCombineXYZ",
        "ShaderNodeSeparateColor",
        "ShaderNodeCombineColor",
        "ShaderNodeClamp",
    }

    for n in nodes:
        ntype = getattr(n, "bl_idname", "") or getattr(n, "type", "")
        ntype = str(ntype)
        type_counts[ntype] = type_counts.get(ntype, 0) + 1
        
        if ntype == "ShaderNodeGroup" or ntype == "GROUP":
            group_nodes += 1
        
        up = ntype.upper()

        if ntype in image_keywords or "IMAGE" in up or "ENVIRONMENT" in up:
            tex_image_nodes += 1
        elif ntype in procedural_keywords:
            tex_pattern_nodes += 1
        elif ntype.startswith("ShaderNodeTex") and ntype not in image_keywords and ntype != "ShaderNodeTexCoord":
            tex_pattern_nodes += 1
            
        if ntype in math_keywords or any(k in up for k in ("MATH", "MIX", "MAPRANGE", "SEPARATE", "COMBINE", "CLAMP")):
            math_nodes += 1

    # Calculate Graph Depth (Longest Path in DAG)
    # 1. Build Adjacency List
    adj = {n.name: [] for n in nodes}
    for link in links:
        if not link.is_valid:
            continue
        from_name = link.from_node.name
        to_name = link.to_node.name
        if from_name in adj:
            adj[from_name].append(to_name)
    
    # 2. Compute Longest Path using Memoization
    memo = {}
    def get_depth(node_name):
        if node_name in memo:
            return memo[node_name]
        
        max_child_depth = 0
        if node_name in adj:
            for child in adj[node_name]:
                # Simple cycle detection prevention (max depth clamp)
                # In a valid Blender material, cycles shouldn't exist, but safety first
                max_child_depth = max(max_child_depth, get_depth(child))
        
        memo[node_name] = 1 + max_child_depth
        return memo[node_name]

    max_depth = 0
    # We can iterate all nodes, but to be faster we could start from roots. 
    # For robustness, just iterate all.
    # Limit recursion depth to avoid crashes on malformed graphs
    try:
        import sys
        sys.setrecursionlimit(2000)
        for n in nodes:
            d = get_depth(n.name)
            if d > max_depth:
                max_depth = d
    except Exception:
        max_depth = 1  # Fallback

    node_count = len(nodes)
    
    return {
        "node_count": node_count,
        "link_count": len(links),
        "group_node_count": group_nodes,
        "texture_pattern_count": tex_pattern_nodes,
        "texture_image_count": tex_image_nodes,
        "math_node_count": math_nodes,
        "max_depth": max_depth,
        "node_type_counts": type_counts,
    }


def get_structural_vector(rep: MaterialRepresentation) -> List[float]:
    """
    Extracts a 6-dimensional structural signature vector from the K-topology.
    Dimensions:
    1. Node Count (log-normalized)
    2. Structure Depth (log-normalized)
    3. Branching Factor (links per node, normalized)
    4-b) Main-path Dominance (Longest Path Nodes / Total Nodes)
    5. Procedural Generator Ratio (procedural generators / total nodes)
    6. Math-Transform Ratio (math/transform/mix nodes / total nodes)
    """
    k = rep.k_topology
    if not k:
        return [0.0] * 6
        
    node_count = float(k.get("node_count", 0))
    if node_count <= 0:
        return [0.0] * 6
        
    # 1. Node Count: Logarithmic normalization (0-200 nodes -> 0-1)
    node_count_norm = math.log1p(node_count) / math.log1p(200)
    node_count_norm = max(0.0, min(1.0, node_count_norm))

    # 2. Structure Depth
    max_depth = float(k.get("max_depth", 1))
    depth_norm = math.log1p(max_depth) / math.log1p(50)
    depth_norm = max(0.0, min(1.0, depth_norm))

    # 3. Branching Factor
    link_count = float(k.get("link_count", 0))
    # Average links per node. Usually 1.0-2.0.
    branching = (link_count / node_count) / 2.0 
    branching = max(0.0, min(1.0, branching))

    # 4-b) Main-path Dominance
    dominance = float(max_depth) / float(node_count)
    dominance = max(0.0, min(1.0, dominance))

    # 5. Procedural Generator Ratio
    proc_count = float(k.get("texture_pattern_count", 0))
    proc_ratio = proc_count / node_count
    proc_ratio = max(0.0, min(1.0, proc_ratio))

    # 6. Math-Transform Ratio
    math_count = float(k.get("math_node_count", 0))
    math_ratio = math_count / node_count
    math_ratio = max(0.0, min(1.0, math_ratio))
    
    return [
        node_count_norm,
        depth_norm,
        branching,
        dominance,
        proc_ratio,
        math_ratio,
    ]


def representation_to_json_str(rep: MaterialRepresentation) -> str:
    return json.dumps(rep.to_dict(), ensure_ascii=False)


def json_str_to_representation(s: str) -> Optional[MaterialRepresentation]:
    try:
        data = json.loads(s)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    raw_text = str(data.get("raw_text") or "")
    tags = data.get("tags") or []
    slots = data.get("slots") or []
    s_vec = data.get("S") or []
    k_topology = data.get("K") or {}

    if not isinstance(tags, list) or not isinstance(slots, list) or not isinstance(s_vec, list) or not isinstance(k_topology, dict):
        return None

    slot_specs: List[SlotSpec] = []
    for sd in slots[:MAX_SLOTS]:
        if not isinstance(sd, dict):
            continue
        role = str(sd.get("role") or "Base")
        concept = str(sd.get("concept") or role)
        stags = sd.get("tags") or []
        if not isinstance(stags, list):
            stags = []
        relation = str(sd.get("relation") or "base")
        slot_specs.append(SlotSpec(role=role, concept=concept, tags=tuple(str(t) for t in stags), relation=relation))

    try:
        vec = tuple(float(x) for x in s_vec)
    except Exception:
        return None

    return MaterialRepresentation(
        raw_text=raw_text,
        tags=tuple(str(t) for t in tags),
        slots=tuple(slot_specs),
        s_vector=vec,
        k_topology=k_topology,
    )
