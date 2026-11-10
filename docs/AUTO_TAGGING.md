# Automatic material tagging

The `scripts/auto_tag_materials.py` utility renders previews, sends them with material names to DashScope / Qwen-VL, and stores semantic tags on Blender material assets. It runs with Blender Python and uses only the standard library beyond `bpy`.

## Run

Set `DASHSCOPE_API_KEY` in your environment, then invoke Blender on a copy of your material file:

```sh
blender --background /path/to/materials.blend --python scripts/auto_tag_materials.py -- --target-catalog MyMaterial
```

To render previews without network inference or saving tags:

```sh
blender --background /path/to/materials.blend --python scripts/auto_tag_materials.py -- --preview-only --preview-subdir MyMaterial
```

For automatic launch from ordinary Python, set `BLENDER_EXE` to the executable (or add Blender to PATH), and set `MATCOMPOSER_BLEND_FILE` to the input file. Do not put API keys in source code.

## Workflow

1. Parse arguments after Blender's `--`, or from normal Python arguments when self-launching.
2. Read catalog UUID/path mappings from `blender_assets.cats.txt` beside the opened file.
3. Filter node-based materials by catalog, optional exact material name, and existing tags.
4. Render a temporary sphere preview using Eevee.
5. Send the rendered image and material name to Qwen-VL with the semantic taxonomy.
6. Normalize generated tags into category, style, surface state, physical perception, and usage buckets, deduplicate tags, and add them to the asset metadata.
7. Save after every five successful tagged materials, after a targeted material, and at completion.

Tagging saves changes to the opened `.blend` file, including the script's preview scene setup. Work on a copy. Preview-only mode writes PNGs under `material_cache/previews/<preview-subdir>/` by default and does not save the `.blend` file.

## Configuration

The script reads `DASHSCOPE_API_KEY` from the environment. Its configured model is `qwen-vl-plus`, using the DashScope compatible chat-completions endpoint. Top-level constants define the taxonomy defaults, model, and API endpoint.

| Argument | Behavior |
| --- | --- |
| `--target-catalog PATH` | Restrict catalog and subcatalogs; default is `MyMaterial` for tagging. |
| `--target-catalog` | Process all catalogs. |
| `--target-material NAME` | Process one material by exact name. |
| `--skip-existing` / `--no-skip-existing` | Override whether tagged assets are skipped. |
| `--preview-only` | Render previews without tagging or API calls. |
| `--cache-dir DIR` | Override preview cache root. |
| `--preview-subdir PATH` | Match the material catalog path for embedding keys. |
| `--skip-existing-preview` | Render only missing previews in preview-only mode. |

A missing API key stops tagging before the render setup. If no materials are processed, check catalog assignments, the catalog file location, exact name filters, and existing-tag filtering. See [SCRIPTS.md](SCRIPTS.md) for optional embedding generation and [MATERIALS.md](MATERIALS.md) for runtime library requirements.
