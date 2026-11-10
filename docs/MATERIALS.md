# Material availability and library setup

**Due to copyright restrictions, we currently provide only the material and mask assets included in this repository. The complete material collection used in the paper is not distributed.**

**由于版权原因，目前仅上传本仓库中包含的部分材质及遮罩资源，暂不提供论文实验使用的完整材质库。**

Use your own appropriately licensed materials for retrieval and composition. The current subset is not the full benchmark corpus and cannot reproduce the paper's complete asset coverage or evaluation results. The GPL-3.0 code license does not apply to these assets; see [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

## Included resources

| Resource | Blender file | Preview | Existing sidecar metadata |
| --- | --- | --- | --- |
| Ambient occlusion mask | `masks/ao_mask.blend` | `ao_mask.jpg` | `ao_mask.json` |
| Cell mask | `masks/cell_mask.blend` | `cell_mask.jpg` | `cell_mask.json` |
| Crack mask | `masks/crack_mask.blend` | `crack_mask.jpg` | Not supplied |
| Edge mask | `masks/edge_mask.blend` | `edge_mask.jpg` | `edge_mask.json` |
| Generated mask | `masks/generated_mask.blend` | `generated_mask.jpg` | `generated_mask.json` |
| Normal mask | `masks/normal_mask.blend` | `normal_mask.jpg` | `normal_mask.json` |
| Peeling mask | `masks/peeling_mask.blend` | `peeling_mask.jpg` | `peeling_mask.json` |
| Splatter mask | `masks/splatter_mask.blend` | `splatter_mask.jpg` | `splatter_mask.json` |
| Animated Lava Veins | Nested `.blend` under `masks/assets/materials/` | Not supplied | No separate license supplied |

The eight mask files contain node groups matching their filenames. The nested lava asset is retained in its existing location and is not automatically used as a mask. Its material is currently unassigned to a catalog and has no semantic tags; it will not become a retrieval library merely by being present in this folder.

Existing mask metadata includes engine hints and original documentation links. These fields are preserved; they do not establish redistribution permission. Blender backup files (`.blend1`, `.blend2`, etc.) are excluded from uploads.

## Using your own material library

The current library scanner uses the catalog prefix **`MyMaterial`**. The catalog path must equal `MyMaterial` or begin with `MyMaterial/` (case-insensitive).

1. Create or open a `.blend` file containing node-based materials you have permission to use.
2. Mark each material as an asset. In Blender's Asset Browser, create a catalog named `MyMaterial` and optional subcatalogs such as `MyMaterial/Metal` or `MyMaterial/Stone`.
3. Assign your materials to these catalogs, add useful semantic tags, save the `.blend` file, and save the catalogs. The library root must contain Blender's `blender_assets.cats.txt` mapping catalog UUIDs to these paths.
4. In **Preferences → File Paths → Asset Libraries**, add that root directory.
5. Click **Scan Asset Libraries** in MatComposer. Rescan after adding assets or updating catalogs.

Example layout:

```text
MyMaterialLibrary/
├── blender_assets.cats.txt
├── metal.blend
└── stone.blend
```

Catalogs are Blender metadata, not simply filesystem directory names. Creating a folder named `MyMaterial` without assigning catalog IDs does not satisfy the scanner. The supplied `masks/blender_assets.cats.txt` should not be treated as a complete retrieval-library catalog.

Tags influence semantic retrieval. Optional auto-tagging modifies asset tags and saves the input file, so run it on a copy first; see [SCRIPTS.md](SCRIPTS.md).

## Generated data

The repository excludes `material_cache/`, precomputed previews, and embeddings from the author's full library. The add-on uses its Blender user-data cache first, with the checkout's `material_cache/` as a fallback for optional vector files and previews. Regenerate these for the assets you actually use.

The optional CLIP and GNN files are keyed by material name or `CatalogPath:MaterialName`; names, catalog paths, and preview subfolders must agree. Missing optional vectors do not supply missing assets.
