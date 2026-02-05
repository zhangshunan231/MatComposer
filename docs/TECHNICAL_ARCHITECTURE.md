# MatComposer Technical Architecture: Dual-Space Vector Retrieval

## Overview

MatComposer operates on a **Dual-Space Architecture** that separates material definition into two distinct but interacting vector spaces:
1.  **Semantic Space ($S$)**: Represents the *visual and conceptual* attributes of a material (e.g., "Rusty", "Metal", "Blue").
2.  **Structural Space ($K$)**: Represents the *topological and functional* composition of the material graph (e.g., "Base Material", "Overlay Mask", "Node Complexity").

This separation allows the system to perform "Directional Exploration"—navigating through material variations (Semantic) without breaking the underlying node graph validity (Structural).

---

## 1. Semantic Space ($S$)

The Semantic Space is a high-dimensional continuous vector space where materials are positioned based on their textual descriptions and tags.

### Definition
-   **Representation**: A vector $v \in \mathbb{R}^d$ (default $d=128$).
-   **Basis**: The space is constructed using a **Deterministic Stable Unit Hash** embedding strategy, rather than a heavy pre-trained Transformer model. This ensures:
    -   **Zero-Latency**: No inference required for vectorization.
    -   **Stability**: The same tag always yields the exact same vector across sessions.
    -   **Lightweight**: Runs purely on CPU with minimal memory footprint.

### Implementation Details
-   **Tokenization**: Text is split into tokens (lowercase, alphanumeric).
-   **Hashing**: Each token $t$ is mapped to a scalar $h(t) \in [-1, 1]$ via SHA-256.
-   **Projection**: The scalar is projected into $d$ dimensions using a sinusoidal positional encoding variant (or direct hash bucket distribution).
-   **Aggregation**: Vectors for a material's tags are summed and normalized ($L2$ norm).

### Semantic Vectors (The "5 Vectors")
While the mathematical embedding is generic, the *content* of the semantic space is guided by 5 specific "Taxonomy Vectors" enforced by the LLM (defined in `llm_handler.py`):
1.  **Material Categories** (Substrate identity)
2.  **Stylistic Attributes** (Artistic direction)
3.  **Surface States** (Weathering/Age)
4.  **Physical Perceptions** (Tactile/Optical properties)
5.  **Usage Scenarios** (Context)

### Retrieval Operations
The `utils/exploration_engine.py` implements vector arithmetic for retrieval:
-   **Local Exploration** (Find Similar):
    $$Score(A, B) = -Euclidean(S_A, S_B)$$
-   **Directional Exploration** (Find Next):
    Given a current state $S_{curr}$ and a previous state $S_{prev}$, we compute a direction $\vec{d} = S_{curr} - S_{prev}$. The system searches for candidate $C$ that maximizes projection onto $\vec{d}$ while minimizing distance to the projected target $T = S_{curr} + \vec{d}$.
    $$Score(C) = \frac{(S_C - S_{curr}) \cdot \vec{d}}{||\vec{d}||} - \alpha \cdot ||S_C - T||$$

---

## 2. Structural Space ($K$)

The Structural Space defines the "Skeleton" of the material. It serves two purposes: determining the topological role (Base/Overlay) and quantifying the **Information Density** (Computational Depth).

### 2.1 Definition & Composition
-   **Topology**: A directed acyclic graph (DAG) of Shader Nodes.
-   **Composition Model**: MatComposer simplifies the infinite graph space into a standardized **Slot-Based Architecture**:
    -   **Slot 0: Base** (The underlying material)
    -   **Slot 1: Overlay** (Coatings, rust, dust, paint)
    -   **Slot 2: Detail** (Micro-surface imperfections, scratches)

### 2.2 Complexity Quantification ($C_{norm}$)
The complexity of a material is derived mathematically from its node graph to gauge computational depth.

-   **The Metric**: Total functional node count ($N$), including BSDFs, Textures, Math, Mix, Ramps, etc.
-   **Normalization**: Logarithmic scale $0.0 - 1.0$ to map raw counts to a comparable index.
    
    $$ C_{norm} = \frac{\ln(1 + N)}{\ln(1 + N_{max})} $$
    
    (Where saturation limit $N_{max} = 220$)

-   **Interpretation**:
    -   **0.0 - 0.3**: Simple Materials (e.g., Single texture, basic PBR, < 10 nodes).
    -   **0.3 - 0.6**: Procedural Patterns (e.g., Voronoi + Bump + Ramp, 10-50 nodes).
    -   **0.6 - 0.9**: Heavy Procedural / Uber Shaders (Multi-layer mixing, > 50 nodes).
    -   **1.0+**: Extremely complex.

### 2.3 Structural Topology Analysis
Beyond simple node counts, the system performs a "Deep Inspection" (`build_k_topology_from_node_tree` in `utils/semantic_init.py`) to extract feature vectors:
1.  **Texture Density**: Ratio of bitmap vs. procedural textures.
2.  **Group Depth**: Usage of `ShaderNodeGroup` indicating modularity.
3.  **Link Density**: Ratio of links to nodes, implying data flow complexity.

### 2.4 Structural Constraints in Retrieval
When performing retrieval, the Structural Space acts as a **Constraint Filter** and **Ranking Axis**:

1.  **Role Locking**:
    -   If a slot (e.g., Overlay) is locked, the system penalizes candidates that deviate from the locked slot's semantic signature.
    -   $$Penalty = \beta \cdot ||S_{candidate\_locked\_part} - S_{locked\_target}||$$

2.  **Topology Preservation**:
    -   Ensures retrieved assets are compatible with the target slot (e.g., "Mask" assets for Overlay, PBR materials for Base).

3.  **Depth Matching**:
    -   Matches user intent to material complexity (e.g., "Simple plastic" $\rightarrow C_{norm} \approx 0.1$ vs "Detailed sci-fi hull" $\rightarrow C_{norm} \approx 0.7$).

4.  **Performance Optimization (LOD)**:
    -   Allows filtering by $C_{norm}$ (e.g., $< 0.4$) for background assets in heavy scenes.

### 2.5 Inspection Mechanism
To obtain these metrics efficiently, the system uses `bpy.data.libraries.load` in a temporary context to peek at asset libraries, inspect the node tree, and discard the data immediately, allowing rapid indexing of thousands of materials.

---

## 3. Dual-Space Interaction Flow

When a user executes a prompt (e.g., "Make the rust heavier and the metal darker"):

1.  **LLM Parsing (Bridge)**:
    -   The LLM analyzes the prompt and decomposes it into:
        -   **Semantic Delta**: "Darker", "Heavier Rust" -> Updates $S_{target}$.
        -   **Structural Operation**: "Update Overlay", "Update Base" -> Updates $K_{plan}$.

2.  **Vector Search ($S \cap K$)**:
    -   The system searches the Asset Library.
    -   It filters candidates based on $K$ (Must be valid for the target Slot & Complexity range).
    -   It ranks candidates based on $S$ (Closest match to "Darker Metal").

3.  **Composition**:
    -   The selected assets are retrieved.
    -   The `utils/composition_engine.py` assembles them according to the $K_{plan}$ (connecting Base Color, Normal, Roughness through Mix nodes using the Overlay mask).

---

## Code References

-   **Semantic Vector Math**: [`utils/semantic_init.py`](file:///d:\MyProjects\MatComposer\utils\semantic_init.py)
    -   `embed_text()`: Deterministic embedding.
    -   `build_k_topology_from_node_tree()`: Structural feature extraction.
-   **Retrieval Logic**: [`utils/exploration_engine.py`](file:///d:\MyProjects\MatComposer\utils\exploration_engine.py)
    -   `directional_exploration()`: The core algorithm combining direction + lock constraints.
-   **Structural Complexity**: [`utils/library_manager.py`](file:///d:\MyProjects\MatComposer\utils\library_manager.py)
    -   `ensure_entry_complexity()`: Main entry point for complexity calculation.
    -   `_normalize_complexity()`: Logarithmic normalization logic.
-   **Taxonomy Definitions**: [`llm_handler.py`](file:///d:\MyProjects\MatComposer\llm_handler.py)
    -   `SEMANTIC_SYSTEM_PROMPT`: Defines the 5 axes of the semantic space.
