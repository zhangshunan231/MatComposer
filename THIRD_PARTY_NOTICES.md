# Third-party assets and license scope

## Project code

Copyright (C) 2026 MatComposer authors.

The project's Python source code, including the add-on and utility scripts, is licensed under GNU General Public License version 3 only (`GPL-3.0-only`). See [LICENSE](LICENSE) for the complete terms.

## Material and mask assets

Due to copyright restrictions, only the material and mask assets currently included in this repository are provided. The complete material collection used in the paper is not distributed.

The code license does not cover `.blend` assets, preview images, or third-party asset metadata. These retain their original copyright and license conditions. No additional permission to redistribute, sublicense, or use an asset commercially is granted by its inclusion here. Where an asset's license is not supplied, obtain permission or confirm the original terms with its rights holder before redistributing it.

The following source references are preserved from the existing metadata, rather than inferred from filenames:

| Asset metadata | Existing source reference |
| --- | --- |
| `masks/ao_mask.json` | https://sanctuslibrary.xyz/documentation/main/en/topic/ao-mask |
| Other supplied mask JSON files | Their `documentation_link` fields identify their original documentation |

The included `Animated Lava Veins` asset does not have a separate license file in the current project. Its author and license must not be inferred from the code license. The resource inventory is maintained in [docs/MATERIALS.md](docs/MATERIALS.md).

## External services and models

- The interactive add-on and auto-tagging script can call Alibaba Cloud DashScope / Qwen-VL with a user-provided API key. Requests may contain the entered description and selected reference image or rendered material preview. Service access and usage are subject to the provider's terms.
- Optional CLIP preprocessing uses separately installed model libraries and downloaded model weights. These are not bundled; their original licenses apply.
- Blender, PyTorch, Pillow, Transformers, OpenCLIP, and Matplotlib are external dependencies, not vendored source code in this repository.
