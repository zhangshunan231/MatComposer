# Auto-Tagging System Technical Documentation

## Overview
The MatComposer Auto-Tagging System is an automated pipeline designed to enrich material assets with semantic metadata. It utilizes a Visual Language Model (VLM) to analyze rendered previews of materials and generate precise, descriptive tags based on a predefined semantic taxonomy.

This system is implemented primarily in `scripts/auto_tag_materials.py` and operates as a standalone process that can self-launch within a Blender environment.

## System Architecture

The system operates in a closed loop:
1.  **Bootstrapping**: Self-correction of environment (Python -> Blender).
2.  **Discovery**: Identifying candidate materials based on catalog and existing metadata.
3.  **Visualization**: Generating ephemeral render previews.
4.  **Inference**: Querying the VLM (Qwen-VL-Plus) with visual and textual context.
5.  **Persistence**: Writing tags back to Blender's asset data system.

### Core Components

| Component | File | Role |
| :--- | :--- | :--- |
| **Orchestrator** | `scripts/auto_tag_materials.py` | Manages the entire lifecycle: environment check, rendering, API calls, and saving. |
| **Semantic Definition** | `llm_handler.py` | Defines the 5-vector semantic taxonomy used for prompt engineering. |
| **Library Manager** | `utils/library_manager.py` | (Reference) Defines the catalog structure and asset management logic. |

---

## Detailed Workflow

### 1. Environment Bootstrapping (Self-Launch)
The script is designed to be run from any Python environment (e.g., VS Code, Terminal). However, it requires the `bpy` (Blender Python) module to access material data and rendering engines.

-   **Detection**: The script checks if `bpy` is importable and functional (specifically checking `bpy.ops`).
-   **Self-Correction**: If a functional Blender environment is not found, the script uses `subprocess` to launch a specific Blender executable in **Background Mode** (`--background`).
-   **Payload**: It passes itself as a script to run inside Blender (`-P scripts/auto_tag_materials.py`).

### 2. Asset Discovery & Filtering
Once running inside Blender, the script scans the opened `.blend` file (e.g., `MyMaterials.blend`) for candidate materials.

**Filtering Logic**:
1.  **Node Materials Only**: Ignores materials that do not use nodes (`mat.use_nodes`).
2.  **Catalog Matching**:
    -   Parses `blender_assets.cats.txt` to map Catalog UUIDs to paths.
    -   Checks if the material belongs to the configured `TARGET_CATALOG` (default: "MyMaterial").
    -   *Normalization*: Paths are stripped of slashes and lowercased for robust comparison.
3.  **Name Matching**:
    -   Optional: If `TARGET_MATERIAL_NAME` is set, only that specific material is processed.
4.  **Skip Existing**:
    -   If `SKIP_EXISTING` is `True`, materials that already have tags are skipped to conserve API usage.

### 3. Visual Sampling (Rendering)
To allow the AI to "see" the material, the script creates a temporary studio setup:

-   **Scene**: A new scene is created (or objects replaced) with a standard UV Sphere.
-   **Lighting**: A calibrated two-point lighting setup (Key Light + Fill Light) to reveal surface details like roughness and normal maps.
-   **Engine**: `BLENDER_EEVEE_NEXT` is used for high-performance rendering (512x512 resolution).
-   **Output**: A temporary image file (`mat_preview_temp.png`) is generated for each material.

### 4. Semantic Inference (VLM)
The rendered image and the material's name are sent to the Alibaba Cloud Qwen-VL-Plus model.

**Prompt Engineering**:
The system prompt enforces a strict JSON output constrained by 5 Semantic Vectors (defined in `llm_handler.py`):
1.  **Material Categories**: (e.g., Metal, Stone, Wood)
2.  **Stylistic Attributes**: (e.g., Realistic, Stylized)
3.  **Surface States**: (e.g., Rusted, Worn, Wet)
4.  **Physical Perceptions**: (e.g., Rough, Glowing)
5.  **Usage Scenarios**: (e.g., Floor, Wall, Armor)

**Example Payload**:
```json
{
  "messages": [
    {"role": "system", "content": "...generate 5-10 tags..."},
    {
      "role": "user", 
      "content": [
        {"type": "text", "text": "Generate visual tags for this material: RustyIron_01."},
        {"type": "image_url", "image_url": "data:image/png;base64,..."}
      ]
    }
  ]
}
```

### 5. Tag Injection & Persistence
-   **Parsing**: The JSON response is parsed to extract the list of tags.
-   **Injection**: Tags are added to the material's `asset_data.tags` collection.
    -   *Deduplication*: New tags are checked against existing ones (case-insensitive) to avoid duplicates.
-   **Incremental Save**: The script saves the `.blend` file every **5 materials** processed. This prevents total data loss in case of a crash or interruption.

---

## Configuration

The behavior of the system is controlled by constants at the top of `scripts/auto_tag_materials.py`:

```python
# API Key for Alibaba Cloud Qwen
API_KEY = "sk-..." 

# Target Catalog (matches folder structure in Asset Browser)
TARGET_CATALOG = "MyMaterial"

# Target Specific Material (Leave empty for batch mode)
TARGET_MATERIAL_NAME = ""

# Skip materials that already have tags
SKIP_EXISTING = True

# Blender Executable Path (for self-launch)
BLENDER_EXE = r"D:\software\Blender\Blender4.4\blender.exe"
```

## Troubleshooting

### "Blender environment not detected"
-   Ensure `BLENDER_EXE` points to a valid Blender 4.x executable.
-   Ensure the script has permission to spawn subprocesses.

### "No tags generated"
-   Check the API Key validity.
-   Check internet connectivity (the script makes HTTPS requests).
-   Verify that the material has a valid node tree and can be rendered.

### Script Freezes
-   The script runs in the background, but large batch processes can take time.
-   Check the terminal output for progress logs (`[1/50] Processing: MaterialName...`).
-   If it hangs on "Rendering...", the scene setup might be too heavy or the GPU is unresponsive.
