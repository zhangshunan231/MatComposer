# Installation and usage

## Environment

- Blender 4.4.x is the documented environment; registration and resource loading have been checked with Blender 4.4.3 on Windows.
- The add-on declares Blender 4.0 as its minimum. This is not a compatibility test of every Blender 4.x or 5.x version.
- Use Blender's bundled Python for the add-on and Blender-dependent scripts. Do not install `bpy` into a separate environment to install the add-on.
- A user-provided DashScope API key and network access are required for semantic initialization and optional automatic tagging.
- Retrieval requires a separately prepared material asset library. The included masks are composition resources, not the full retrieval corpus.

## Build and install

From the repository root, run:

```sh
python scripts/package_addon.py
```

This writes `dist/MatComposer-1.0.0.zip`, with `MatComposer/__init__.py` inside the archive. The package includes runtime code, included assets, guides, citation files, and license notices. It excludes repository history, caches, Blender backups, and local configuration. Preprocessing scripts are run from the source checkout.

In Blender 4.4, open **Edit → Preferences → Add-ons**, use the dropdown menu's **Install from Disk**, and select the ZIP. Enable **MatComposer**. When updating, close Blender or disable the previous version before replacing it, then restart Blender.

## Configure a material library

Follow [MATERIALS.md](MATERIALS.md#using-your-own-material-library) to mark your materials as assets, assign them to `MyMaterial` or its subcatalogs, and register the library folder. Click **Scan Asset Libraries** in MatComposer after changes. A catalog file with a matching catalog is required; unassigned assets are not enough.

## Configure API access

Enter your own key in the MatComposer panel's **API Key** field. Alternatively, set `DASHSCOPE_API_KEY` in the environment **before launching Blender**. The add-on reads that environment variable when it is imported. It uses the DashScope compatible chat-completions endpoint and Qwen-VL models configured in the source.

The API key is held in session memory through property callbacks and is not saved into `.blend` files. Legacy `api_key` scene properties are removed in memory on registration and file load; resave older files to remove those stored properties from disk. Do not put credentials into source code, screenshots, or shared logs. Copies and backups created by earlier versions may need separate cleanup.

## Author a material

1. Select a mesh object with an active node-based material.
2. Switch to the Shader Editor, press **N**, and open **MatComposer**.
3. Scan the asset libraries. Enter a description and optionally select a reference image.
4. Click **Semantic Init** to produce tags and a slot decomposition. This step makes an API request.
5. Click **Search Slots** to retrieve candidates. Choose materials for the planned slots.
6. For additional layers, choose a supplied mask and adjust available controls. Some masks depend on geometry or the rendering engine; see the metadata in `masks/`.
7. Use **Explore** with **Joint Exploration**, **Lock Semantics**, or **Lock Structure**. Slot locks preserve selected components during subsequent searches.
8. Use the assembly operator in **Exploration & Evolution** to build the resulting material. Inspect the assembled nodes and save your scene.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Panel is missing | Enable the add-on, use the Shader Editor, and open the N sidebar. |
| No search results | Register a library containing marked material assets; confirm catalog paths start with `MyMaterial`, then rescan. |
| API request fails | Confirm the key, service access, network connection, and selected model. |
| Candidate preview is missing | Use Refresh Previews, or generate previews as described in [SCRIPTS.md](SCRIPTS.md). |
| CLIP/GNN features are unavailable | These are optional; generate vector files for your own library and check that keys match material entries. |
| A mask behaves differently | Check its original metadata and test geometry/render-engine requirements. |

This setup does not supply the full paper corpus or claim full experiment reproduction. Network inference and arbitrary external material libraries require validation in your own environment.
