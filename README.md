# MatComposer

**Structural-Semantic Retrieval and Iterative Exploration for Procedural Material Graph Authoring**

[Paper](https://doi.org/10.1145/3830398.3830601) · [中文说明](README.zh-CN.md) · [Installation](docs/INSTALLATION.md) · [Material availability](docs/MATERIALS.md) · [BibTeX](citation.bib)

**Shunan Zhang, Yi Xiao, Guangpeng Wei, Yang Zhou, Zeyu Liu**

UIST 2026 — Proceedings of the 39th Annual ACM Symposium on User Interface Software and Technology

MatComposer is a Blender add-on for authoring procedural materials through retrieval, slot-based composition, and iterative exploration. It combines semantic descriptions with shader-graph structure to help users find, assemble, and refine materials.

## Features

- **Semantic initialization:** turn a text description and an optional reference image into tags and a Base / Overlay / Detail plan using Qwen-VL through DashScope.
- **Structural-semantic retrieval:** search a registered Blender material library using semantic tags and graph features, with optional offline CLIP and GNN embeddings.
- **Iterative exploration:** explore jointly, lock semantics while varying structure, or lock structure while varying semantics.
- **Graph composition:** assemble selected materials using procedural masks, slot locking, and optional external UV mapping.

## Material availability

**Due to copyright restrictions, we currently provide only the material and mask assets included in this repository. The full material collection used in the paper is not distributed.** Please use your own appropriately licensed material library for retrieval and composition. The included subset does not reproduce the paper's full asset coverage or evaluation results.

The code is licensed under **GPL-3.0-only**. Material files, masks, previews, and third-party asset metadata are **not covered by the code license**. Their original rights and license terms remain applicable; inclusion does not grant additional redistribution rights. See [material availability and setup](docs/MATERIALS.md) and [third-party notices](THIRD_PARTY_NOTICES.md).

## Quick start

1. Use **Blender 4.4.x** for the documented setup. The add-on declares Blender 4.0 as its minimum; other versions have not been verified here.
2. Clone the repository and build an installable add-on ZIP:

   ```sh
   git clone git@github.com:zhangshunan231/MatComposer.git
   cd MatComposer
   python scripts/package_addon.py
   ```

   Repository access is required while the project remains private.
3. In Blender, open **Edit → Preferences → Add-ons → Install from Disk**, select `dist/MatComposer-1.0.0.zip`, and enable **MatComposer**.
4. Register your material library under **Preferences → File Paths → Asset Libraries**. Materials must be marked as assets and assigned to the `MyMaterial` catalog or one of its subcatalogs. See the [library setup guide](docs/MATERIALS.md#using-your-own-material-library).
5. Select a mesh with an active material. Open the **Shader Editor**, press **N**, and select **MatComposer**.
6. Enter your own DashScope API key, click **Scan Asset Libraries**, and enter a description, for example `weathered metal with a rusty overlay`.
7. Run **Semantic Init**, then **Search Slots**. Choose candidates and masks, use **Explore** to refine them, and assemble the selected slots from **Exploration & Evolution**.

No pip dependencies are required for the interactive add-on beyond Blender's bundled Python. An API key and network access are required for semantic initialization. Offline embedding and plotting scripts have separate optional dependencies; see [scripts and preprocessing](docs/SCRIPTS.md).

## Repository layout

```text
MatComposer/
├── __init__.py                # Add-on metadata, properties, registration
├── operators.py               # Search, exploration, and assembly operators
├── ui.py                      # Shader Editor panels
├── llm_handler.py             # DashScope client and semantic prompts
├── utils/                     # Library indexing, graph features, composition
├── masks/                     # Included masks, previews, and asset subset
├── scripts/                   # Preprocessing, statistics, packaging
├── docs/                      # Installation and technical documentation
├── CITATION.cff
├── citation.bib
└── LICENSE                    # GPL-3.0 for project source code
```

Generated indexes, embeddings, and previews in `material_cache/` are excluded from version control. Rebuild them for your own library; see [scripts and preprocessing](docs/SCRIPTS.md).

## Documentation

- [Installation and usage](docs/INSTALLATION.md)
- [Material availability, inventory, and library setup](docs/MATERIALS.md)
- [Preprocessing and utility scripts](docs/SCRIPTS.md)
- [Technical architecture](docs/TECHNICAL_ARCHITECTURE.md)
- [Dual-space retrieval notes](docs/DUAL_SPACE_RETRIEVAL.md)
- [Auto-tagging](docs/AUTO_TAGGING.md)

The technical notes include research variants and design discussion. The setup guides describe the current add-on; optional research variants should not be read as guarantees of implemented behavior.

## Citation

```bibtex
@inproceedings{zhang2026matcomposer,
  author = {Zhang, Shunan and Xiao, Yi and Wei, Guangpeng and Zhou, Yang and Liu, Zeyu},
  title = {{MatComposer}: Structural-Semantic Retrieval and Iterative Exploration for Procedural Material Graph Authoring},
  booktitle = {Proceedings of the 39th Annual ACM Symposium on User Interface Software and Technology},
  year = {2026},
  pages = {1--19},
  publisher = {Association for Computing Machinery},
  doi = {10.1145/3830398.3830601},
  url = {https://doi.org/10.1145/3830398.3830601}
}
```

## License and contributions

Copyright (C) 2026 MatComposer authors. Project source code is licensed under [GNU GPL version 3](LICENSE), with asset exclusions described in [third-party notices](THIRD_PARTY_NOTICES.md). The software is provided without warranty under that license.

For bug reports, include your Blender version, operating system, reproduction steps, and relevant console output. Remove credentials and avoid attaching materials you do not have permission to share. See [CONTRIBUTING.md](CONTRIBUTING.md).
