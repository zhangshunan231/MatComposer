# 双空间检索策略 (Dual-Space Retrieval Strategy)

MatComposer 的核心检索机制采用**双空间策略**，旨在同时满足用户对材质**语义意图（Semantic Intent）**和**结构特征（Structural Features）**的需求。

该策略将“语义”定义为多模态的（包含文本和视觉），并在两个独立的宏观空间中分别计算，最后在评分阶段进行融合。

## 1. 语义空间 (Semantic Space)

语义空间用于捕捉材质的“意图”，即它是什么，看起来像什么，用于什么场景。MatComposer 通过**文本**和**视觉**两个维度来构建完整的语义理解。

### 1.1 文本语义 (Text Semantics)
这是基于自然语言理解的语义维度。

- **向量表示**：使用确定性的 Token-Hash Embedding 将材质名称、描述、标签转换为向量（默认 64 维），并做 L2 归一化（无需外部模型推理）。
- **标签加权**：
  - **Category / Type**: 4x 权重 (决定材质本质)
  - **State / Surface**: 3x 权重 (决定表面状态)
  - **Style / Usage**: 2x 权重 (决定风格)
- **作用**：确保检索结果在概念上符合用户的文本描述（如“生锈的金属”）。

代码参考：[`utils/exploration_engine.py`](../utils/exploration_engine.py)

### 1.2 视觉语义 (Visual Semantics - CLIP)
这是基于视觉感知的语义维度，使用 **CLIP (Contrastive Language-Image Pretraining)** 模型构建。

- **向量表示**：
  - **模型**：支持 `OpenCLIP` (ViT-B-32) 或 `HuggingFace Transformers`。
  - **来源**：材质的预览图 (Thumbnail Images)。
  - **存储**：向量存储在 `material_cache/clip_vectors.json`。
- **作用**：捕捉难以用文字描述的细微视觉特征（如纹理频率、对比度、色彩分布），弥补文本描述的盲区。

代码参考：[`scripts/clip_embed.py`](../scripts/clip_embed.py)

### 1.3 语义检索模式
语义空间检索以文本语义向量为主（候选召回/打分），CLIP 视觉向量在候选重排序阶段与其他信号融合。

#### A. 局部探索 (Local Exploration)
- **原理**：基于文本向量的欧几里得距离。
- **公式**：`Score_Local = -Distance_Text(Query, Candidate)`

#### B. 定向外推 (Directional Exploration)
- **原理**：利用用户的浏览历史（上一状态 `Prev` -> 当前状态 `Curr`）计算**方向向量**，预测用户的探索意图。
- **文本方向**：`Dir_Text = Text_Curr - Text_Prev`
- **文本定向得分**：
  `Score_Dir = Proj(ev - curr, Dir_Text) - 0.35 * Distance(ev, curr + Dir_Text) - LockPenalty`

代码参考：[`utils/exploration_engine.py`](../utils/exploration_engine.py)，[`operators.py: _clip_directional_score`](../operators.py#L259)

---

## 2. 结构空间 (K-Space)

结构空间用于描述材质的节点图复杂度及拓扑特征，确保推荐的材质在“物理结构”上是合适的。

### 2.1 维度定义 (Dimensions)
结构空间的统计结构向量（K-Vector）当前采用 6 维：
1. **NodeCount**: 节点数量（对数归一化）。
2. **Depth**: 节点树深度（对数归一化）。
3. **Branching**: 分支系数（links per node 归一化）。
4. **Dominance**: 主干占比（最长路径节点占比，`L/N`）。
5. **ProcRatio**: 程序化生成节点占比（procedural generators / all nodes）。
6. **MathRatio**: 运算与变换节点占比（math/transform/mix / all nodes）。

### 2.2 结构惩罚 (Structural Penalty)
- **公式**：`Penalty = WeightedEuclideanDistance(Candidate_K, Target_K)`
- **应用**：如果一个材质在语义上很匹配，但结构过于复杂或简单（与目标 Slot 不匹配），它会被降权。

代码参考：[`utils/exploration_engine.py: calculate_structural_penalty`](../utils/exploration_engine.py)

---

### 2.3 特征提取机制 (Feature Extraction)

结构空间包含两类互补表示：
1. **统计结构向量 (K-Vector, 6D)**：通过统计特征工程对节点图进行压缩，鲁棒且高效，但会丢失具体连接模式。
2. **图嵌入向量 (GNN Vector, 64/128D)**：通过图神经网络将整个 NodeGraph 映射为稠密向量，保留更多拓扑信息，能区分“统计特征相近但连接方式不同”的材质。

工程上两者并行存在：K-Vector 适合作为稳定约束/可解释维度；GNN Vector 适合作为拓扑相似性的补充度量。

### 2.4 图结构嵌入 (GNN Embedding)

从学术研究与工程效果的角度看，单纯依赖低维统计特征会在“图连接形态”上产生信息损失（例如深窄链式图 vs 宽浅分支图可能出现相近统计值）。

#### 2.4.1 表示定义
- **节点特征 (Node Features)**：
  - 节点类型（Shader/Texture/Math 等）
  - 可选：关键参数（例如 Math/VectorMath 的 operation，Mix 的 blend_type）
- **边特征 (Edge Features)**：
  - 数据流连接关系（from_socket -> to_socket）
- **图嵌入 (Graph Embedding)**：
  - 将整个 NodeGraph 映射为一个 64维 或 128维 的稠密向量
  - `Vec_Graph = GNN(NodeGraph)`

#### 2.4.2 存储与加载
- **离线生成**：由脚本生成向量文件
- **存储位置**：`material_cache/gnn_vectors.json`
- **匹配方式**：沿用与 CLIP 相同的 key（通常为 `CatalogPath:MaterialName` 或 `MaterialName`），运行时挂载到条目上用于检索融合

---

## 3. 结构空间 (K-Space) 的演进：从约束到探索

针对“结构空间是否应该支持探索”这一问题，答案是**肯定的**。当前实现中，结构既作为**约束（Constraint/Penalty）**，也通过定向打分参与**探索（Exploration）**，但在权重和 UI 上仍以约束为主。

### 3.1 现状：静态约束 (Static Constraint)
在基础检索流程里，K-Space 主要用于过滤“不合适”的材质（作为语义检索后的结构约束）。
- **逻辑**：设定一个目标复杂度（Target K），计算候选者与目标的距离。
- **公式**：`Score -= Weight * Distance(K_Candidate, K_Target)`
- **局限**：它假设用户只想要一个固定的复杂度，而忽略了用户可能想要“逐渐增加细节”或“寻找更优化的实现”的动态需求。

### 3.2 进阶：结构定向探索 (Structural Directional Exploration)
类似于语义空间的定向外推，我们可以在结构空间计算**演化向量**。

- **结构动量 (Structural Momentum)**：
  `Dir_Struct = K_Curr - K_Prev`
  如果用户从一个简单材质跳转到一个稍复杂的材质，系统应预测用户想要**更复杂**的材质。
  
- **应用场景**：
  1.  **细节增强 (Detail Enhancement)**：保持语义不变（如都是“木纹”），但在 K-Space 中沿着 `Complexity` 增加的方向探索。
  2.  **性能优化 (Optimization)**：保持视觉相似，但在 K-Space 中沿着 `Complexity` 减少的方向寻找“廉价”替代品。
 3.  **结构变化 (Graph Variation)**：在 K-Space 中沿着 `Dominance/ProcRatio/MathRatio` 的方向探索，寻找结构形态不同但语义接近的变体。

### 3.3 探索模式与空间锁定 (Exploration Modes & Space Locking)
为了给予用户更精细的控制权，系统引入了三种探索模式，允许用户锁定某一空间而探索另一空间。

#### A. 联合探索 (JOINT - Default)
同时探索语义和结构的变化趋势。
- **场景**：用户在寻找灵感，既希望风格变化，也希望结构复杂度随之演进。
- **公式**：
  `Final = Base(SemDir) + 0.25 * ClipDir + 0.45 * StructDir + 0.45 * GNNDIR`

#### B. 锁定语义 (LOCK_SEMANTICS)
**风格锁定，只探索结构**。
- **机制**：
  1. **语义部分**：使用 `Local Exploration`，寻找与当前材质（Curr）在语义上最接近的邻居（即保持风格/材质类型不变）。
  2. **结构部分**：使用 `Directional Exploration`，沿着结构动量方向寻找。
- **公式**：
  `Final = Base(LocalSem) + 1.2 * StructDir + 1.2 * GNNDIR`
- **效果**：例如，锁定“生锈金属”的语义，但寻找结构更复杂/更简单的变体。

#### C. 锁定结构 (LOCK_STRUCTURE)
**结构锁定，只探索语义**。
- **机制**：
  1. **语义部分**：使用 `Directional Exploration`，沿着语义动量方向寻找新的风格。
  2. **结构部分**：使用 `Constraint`，强力惩罚与当前结构（Curr）差异大的材质。
- **公式**：
  `Final = Base(SemDir) - 0.55 * Distance(K_Curr, K_Cand) - 0.55 * Distance(GNN_Curr, GNN_Cand)`
- **效果**：例如，保持当前复杂的节点连接方式，但将材质风格从“金属”推向“塑料”。

---

## 4. 融合策略 (Fusion Strategy)

最终的推荐列表是通过动态权重的融合公式得出的，具体取决于当前的**探索模式**。

**核心逻辑**：
1. **Directionality (方向性)**：预测用户意图 (`Prev -> Curr`).
2. **Locality (局部性)**：保持当前特征 (`Curr`).
3. **Constraint (约束)**：防止偏离目标。

这种动态融合策略使得 MatComposer 既能进行发散性的创意探索（Joint），也能进行收敛性的工程优化（Locking）。

论文内容：

\paragraph{Semantic space.}
MatComposer models semantic intent with a text channel and a visual channel. 
Text semantics use a deterministic token-hash embedding $S^{\text{text}}$ constructed from weighted keywords and tags, enabling fast retrieval without online model inference. 
Visual semantics use a precomputed CLIP embedding $S^{\text{clip}}$ extracted from the thumbnail to capture subtle appearance cues that are hard to express in words.

During iterative exploration, the deployed interactive system does not maintain a long-lived text query vector updated over the entire history. Instead, each step uses the current selection $S^{\text{text}}_{\text{curr}}$ together with the previous selection $S^{\text{text}}_{\text{prev}}$ to define a local preference direction in semantic space (see the directional scoring below).

For completeness, in the paper we also consider an extended variant with implicit relevance feedback of the form
\begin{equation}
	S^{\text{text}}_c \leftarrow \alpha S^{\text{text}}_c + \frac{\beta}{|P|}\sum_{p\in P} S^{\text{text}}_p - \frac{\gamma}{|N|}\sum_{n\in N} S^{\text{text}}_n,
\end{equation}
where $P$ are accepted candidates and $N$ are weak negatives such as skipped items. This update is optional and not required by the current Blender add-on implementation, which relies purely on the local $(\text{prev}, \text{curr})$ direction.

For local neighborhood search, we score candidates by text proximity:
\begin{equation}
	Score_{\text{local}}(c,i) = -\|S^{\text{text}}_c - S^{\text{text}}_i\|_2 .
\end{equation}

For directional exploration, we infer a preference direction from two consecutive selections in both channels. 
Let the previous and current selections be indexed by $\text{prev}$ and $\text{curr}$. We define
\begin{equation}
	\vec d_{\text{text}} = S^{\text{text}}_{\text{curr}} - S^{\text{text}}_{\text{prev}}, 
	\qquad
	\vec d_{\text{clip}} = S^{\text{clip}}_{\text{curr}} - S^{\text{clip}}_{\text{prev}},
\end{equation}
and compute a text directional score using a projection term and a target proximity term:
\begin{equation}
	Score^{\text{text}}_{\text{dir}}(i) =
	\frac{(S^{\text{text}}_i - S^{\text{text}}_{\text{curr}})\cdot \vec d_{\text{text}}}{\|\vec d_{\text{text}}\|}
	- \eta \, \big\|S^{\text{text}}_i - (S^{\text{text}}_{\text{curr}}+\vec d_{\text{text}})\big\|_2
	- Penalty_{\text{lock}}(i),
\end{equation}
where $\eta$ is a fixed proximity weight in our implementation. We compute an analogous CLIP directional score
$Score^{\text{clip}}_{\text{dir}}(i)$ using $\vec d_{\text{clip}}$.

Finally, we fuse the text and CLIP directional signals with the structural direction signals from $K$ and the optional graph embedding $G$:
\begin{equation}
	Score_{\text{dir}}(i)=
	Score^{\text{text}}_{\text{dir}}(i)
	+\lambda_{\text{clip}}\, Score^{\text{clip}}_{\text{dir}}(i)
	+\lambda_{K}\, Score^{K}_{\text{dir}}(i)
	+\lambda_{G}\, Score^{G}_{\text{dir}}(i),
\end{equation}
where the fusion weights depend on the exploration mode. In the default joint mode, we set a small but nonzero contribution for CLIP direction and stronger contributions for structural directions to encourage both stylistic and structural evolution across iterations.

\paragraph{Structural space.}
Similar to the semantic space, MatComposer models structure with two complementary components. The first is an interpretable \emph{$K$-space}, where each material graph is encoded as a compact structural signature derived from graph statistics computed on the flattened node graph (after ungrouping) to ensure comparability across assets. $K$ captures coarse yet actionable properties related to editability and recomposition cost (e.g., overall complexity, dependency depth, and signal reuse), and is used as a stable control surface for gating, constraint satisfaction, and distance-based retrieval.

The second component is an optional \emph{topology-aware GNN embedding} $G$, introduced because graphs with similar summary statistics can still differ substantially in wiring patterns (e.g., reuse of intermediate masks, fan-out of coordinate signals, or long-range coupling across layers). We construct a dataflow graph whose vertices are shader nodes and whose edges follow socket-level connections; in the reference implementation the adjacency is symmetrized before message passing. Each node is featurized by a discrete type index derived from its operation category, which is mapped to a learnable embedding vector. The GNN performs message passing for a small number of layers, producing node embeddings that are pooled by taking the mean over nodes into a graph-level vector in a 64D or 128D space. All $G$ embeddings are computed offline and cached per material; at runtime, MatComposer only performs nearest-neighbor lookup and distance evaluation in this embedding space.

Structural information is used not only for filtering infeasible candidates (e.g., enforcing slot validity and an appropriate complexity band), but also throughout retrieval and ranking. Given a target structural profile $(K_{\text{target}}, G_{\text{target}})$, we compute structure-aware penalties:
\begin{equation}
	Penalty_{K}(i)=\|K_i - K_{\text{target}}\|_{W},
\end{equation}
\begin{equation}
	Penalty_{G}(i)=d_{\text{cos}}(G_i, G_{\text{target}}),
\end{equation}
where $\|\cdot\|_{W}$ denotes a weighted Euclidean distance and $d_{\text{cos}}$ is the cosine distance used in the implementation when enforcing structural locking. In practice, $K$ provides fast and interpretable control for steering complexity, while $G$ refines retrieval by distinguishing candidates that match the target statistics but differ in connectivity patterns, reducing the chance of returning graphs that are superficially similar yet costly to edit or brittle to recomposition.


\paragraph{Composition support (locking \& final scoring).}
To preserve parts of a composite during iterative edits, MatComposer supports role locking. If a slot is locked, the search penalizes candidates whose locked-part semantic signature deviates from the locked target:
\begin{equation}
	Penalty_{\text{lock}}(i)=\mu \cdot \|S_{\text{cand,locked}}-S_{\text{locked}}\|_2.
\end{equation}
At a high level, the final score combines the mode-specific semantic score with locking and structural penalties:
\begin{equation}
	Score(i)=Score_{S}(i)-Penalty_{\text{lock}}(i)-\lambda_{K}Penalty_{K}(i)-\lambda_{G}Penalty_{G}(i),
\end{equation}
where $Score_S$ is either $Score_{\text{local}}$ or $Score_{\text{dir}}$ depending on the current exploration step, and the effective weights $(\lambda_{\text{clip}}, \lambda_K, \lambda_G)$ follow the mode-dependent fusion rules described earlier (JOINT / LOCK\_SEMANTICS / LOCK\_STRUCTURE). This joint ranking returns results that are both perceptually relevant and composition-ready for subsequent slot-based graph assembly.
