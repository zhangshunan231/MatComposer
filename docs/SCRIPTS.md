# Scripts and preprocessing

Run commands from the repository root. Examples use a POSIX-style shell; in PowerShell, invoke a quoted Blender executable with `&` and replace the sample file paths with your own.

## Dependencies

| Workflow | Environment / optional packages |
| --- | --- |
| Interactive add-on | Blender bundled Python and standard library |
| Graph export, auto-tagging, statistics export, tag cleanup | Blender bundled Python (`bpy`) |
| CLIP image embeddings | Separate Python environment: `torch`, `Pillow`, and either `open_clip_torch` or `transformers` |
| GNN embeddings | Separate Python environment: `torch` |
| Statistics plots | Separate Python environment: `matplotlib` |
| ZIP packaging | Python 3.10+ standard library |

Install only the packages needed for your workflow. Preprocessing packages are not required inside Blender for normal interactive use. Model weights are downloaded by their respective libraries when needed and are not bundled here.

## Build the installable add-on

```sh
python scripts/package_addon.py
```

The output is `dist/MatComposer-1.0.0.zip`. Preprocessing scripts stay in the source checkout. The package excludes `.git`, credentials, caches, and Blender backup files.

## Render previews or generate tags

Use a copy of your material file. Auto-tagging writes tags back and saves the `.blend` file periodically. Preview-only mode does not call the API or save tags.

```sh
blender --background /path/to/materials.blend --python scripts/auto_tag_materials.py -- --preview-only --preview-subdir MyMaterial
```

Set `DASHSCOPE_API_KEY` before running automatic tagging:

```sh
blender --background /path/to/materials.blend --python scripts/auto_tag_materials.py -- --target-catalog MyMaterial
```

The default tagger catalog is `MyMaterial`; `--target-catalog` without a value processes all catalogs. Additional filters include `--target-material NAME`, `--skip-existing`, and `--no-skip-existing`. Preview options include `--cache-dir`, `--preview-subdir`, and `--skip-existing-preview`.

For optional self-launch from ordinary Python, set `BLENDER_EXE` (or put Blender on PATH) and `MATCOMPOSER_BLEND_FILE`. No machine-specific executable or input paths are embedded in the script. See [AUTO_TAGGING.md](AUTO_TAGGING.md).

## CLIP vectors

For a preview directory organized by catalog, run:

```sh
python scripts/clip_embed.py --input material_cache/previews --backend open_clip --max 100000 --out material_cache/clip_vectors.json
```

The default `--max` is **1**, so raise it explicitly for a full library. The OpenCLIP backend defaults to `ViT-B-32` with OpenAI weights. The alternative backend is `--backend transformers` with `--hf-model openai/clip-vit-base-patch32`.

An image such as `previews/MyMaterial/Metal/Iron.png` produces the key `MyMaterial/Metal:Iron`. Keep preview directory paths and material names aligned with the scanner. The runtime can also match plain material names, but duplicate names can be ambiguous.

## Graph export and GNN vectors

```sh
blender --background --python scripts/export_graph_structure.py -- --input /path/to/library --output material_cache/graph_data.json
python scripts/gnn_embed.py --input material_cache/graph_data.json --output material_cache/gnn_vectors.json --epochs 100 --dim 64
```

The graph exporter reads material node trees and stores nodes and socket connections. Its keys use relative filesystem directories and material names; align those keys with catalog paths or provide unique material names. It does not automatically flatten every nested node group. The GNN script trains a graph autoencoder on the supplied graphs and exports vectors; no paper-trained checkpoint is included. It does not currently expose a seed or save a reusable model checkpoint, so independently generated embeddings are not guaranteed to match prior runs.

The runtime looks for `clip_vectors.json` and `gnn_vectors.json` in its Blender user-data cache first, then the add-on's `material_cache/`. The path can be inspected from Blender's Python Console with `bpy.utils.user_resource('DATAFILES', path='MatComposer')`. On Windows the usual location is under `%APPDATA%/Blender Foundation/Blender/<version>/datafiles/MatComposer/material_cache/`.

## Export and plot material-library statistics

```sh
blender --background --python scripts/export_material_library_stats.py -- --input /path/to/library --output material_cache/material_library_stats.json
python scripts/plot_material_library_stats.py --input material_cache/material_library_stats.json --output-dir material_cache
```

`plot_manual_bar_groups.py` plots manually specified groups and contains default hand-entered values. It does **not** measure your library and should not be used as evidence of automatically reproduced statistics. Supply `--groups-json` and `--structural-groups-json` for your own data.

## Clear tags

```sh
blender --background /path/to/copy.blend --python scripts/clear_asset_tags.py
blender --background /path/to/copy.blend --python scripts/clear_asset_tags.py -- --save
```

The first command reports changes in memory and does not write them. The second removes all material asset tags from the explicitly opened file and saves it. Keep a backup before using `--save`.
