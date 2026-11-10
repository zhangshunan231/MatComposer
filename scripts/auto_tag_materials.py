# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

import os
import json
import base64
import urllib.request
import urllib.error
import tempfile
import sys
import argparse
import math
import shutil

try:
    import bpy
except Exception:
    bpy = None

# ================= CONFIGURATION =================
# Read the API key from the environment; never put credentials in source files.
API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")

# Model to use
MODEL = "qwen-vl-plus"

# Skip materials that already have tags?
SKIP_EXISTING = True

# API Endpoint
API_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"

# Only process materials in this catalog (folder). Set to "" to process all.
# Example: "MyMaterial" or "MyMaterial/Metal"
TARGET_CATALOG = "MyMaterial"

# Only process a specific material by name (exact match). Set to "" to disable.
# Example: "Brick"
TARGET_MATERIAL_NAME = ""
# =================================================

CATEGORY_TAGS = {
    "metal",
    "stone",
    "wood",
    "fabric",
    "marble",
    "concrete",
    "cast iron",
    "iron",
    "steel",
    "plastic",
    "glass",
    "brick",
    "tile",
    "lava",
}

STYLE_TAGS = {
    "realistic",
    "stylized",
    "toon",
    "cartoon",
    "handpainted",
    "cyberpunk",
    "ancient",
    "modern",
    "futuristic",
}

SURFACE_TAGS = {
    "rust",
    "rusted",
    "rusty",
    "worn",
    "cracked",
    "scratch",
    "scratched",
    "moss",
    "mossy",
    "dust",
    "dusty",
    "dirty",
    "mud",
    "muddy",
    "wet",
    "dry",
    "snow",
    "snowy",
}

PHYSICAL_TAGS = {
    "rough",
    "smooth",
    "glossy",
    "matte",
    "metallic",
    "translucent",
    "glowing",
    "viscous",
}

USAGE_TAGS = {
    "floor",
    "wall",
    "roof",
    "ceiling",
    "terrain",
    "ground",
    "armor",
    "prop",
    "interior",
    "exterior",
}

TAG_ALIASES = {
    "mossy": "moss",
    "rusty": "rust",
    "snowy": "snow",
}

def _extract_script_argv(argv):
    try:
        idx = argv.index("--")
    except ValueError:
        exe = os.path.basename(str(argv[0] if argv else "")).lower()
        if exe.startswith("blender"):
            # Running as: blender ... -P script.py  (without `--`)
            # Keep script args empty; otherwise Blender's own flags break argparse.
            return []
        return list(argv[1:])
    return argv[idx + 1 :]

def _repo_root():
    try:
        return os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    except Exception:
        return os.path.abspath(os.getcwd())

def _safe_filename(name):
    bad = '<>:"/\\|?*'
    out = []
    for ch in str(name or ""):
        out.append("_" if ch in bad else ch)
    s = "".join(out).strip().strip(".")
    if not s:
        s = "material"
    return s[:180]


def _normalize_catalog_uuid(value):
    s = str(value or "").strip()
    if not s:
        return ""
    if s.startswith("AssetCatalogID(") and s.endswith(")"):
        s = s[len("AssetCatalogID(") : -1].strip()
    if s.startswith("UUID(") and s.endswith(")"):
        s = s[len("UUID(") : -1].strip()
    return s.strip().strip("{}").strip().strip("'\"").lower()


def _catalog_matches(target_catalog, actual_catalog):
    target = str(target_catalog or "").strip().strip("/").lower()
    actual = str(actual_catalog or "").strip().strip("/").lower()
    if not target:
        return True
    candidates = [actual]
    if actual.startswith("mymaterial") and not actual.startswith("mymaterials"):
        candidates.append("mymaterials" + actual[len("mymaterial") :])
    elif actual.startswith("mymaterials"):
        candidates.append("mymaterial" + actual[len("mymaterials") :])
    for c in candidates:
        if c == target or c.startswith(target + "/"):
            return True
    return False


def _has_asset_tags(asset_data):
    if not asset_data:
        return False
    try:
        tags = getattr(asset_data, "tags", None)
    except Exception:
        return False


def _preview_output_path(previews_dir, material_name):
    return os.path.join(previews_dir, _safe_filename(material_name) + ".png")
    if tags is None:
        return False
    try:
        for t in tags:
            if str(getattr(t, "name", "") or "").strip():
                return True
    except Exception:
        pass
    try:
        return len(tags) > 0
    except Exception:
        return False

def _parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview-only", action="store_true", help="Only render previews; skip tag generation")
    ap.add_argument("--cache-dir", default="", help="Cache directory for previews (default: <repo>/material_cache)")
    ap.add_argument("--preview-subdir", default="MyMaterials", help="Preview subdirectory under <cache-dir>/previews")
    ap.add_argument("--skip-existing-preview", action="store_true", help="In preview-only mode, render only missing preview files")
    ap.add_argument("--target-catalog", nargs="?", const="", default=None, help="Only process this catalog path (omit value for all)")
    ap.add_argument("--target-material", nargs="?", const="", default=None, help="Only process this exact material name")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--skip-existing", dest="skip_existing", action="store_const", const=True, default=None, help="Skip already-tagged materials")
    g.add_argument("--no-skip-existing", dest="skip_existing", action="store_const", const=False, help="Do not skip already-tagged materials")
    argv = _extract_script_argv(sys.argv)
    return ap.parse_args(argv)

def load_catalog_map():
    """
    Parses blender_assets.cats.txt to map UUIDs to paths.
    """
    base_dir = os.path.dirname(bpy.data.filepath)
    cats_path = os.path.join(base_dir, "blender_assets.cats.txt")

    catalog_map = {}
    if not os.path.exists(cats_path):
        # Try looking one level up just in case
        cats_path_up = os.path.join(os.path.dirname(base_dir), "blender_assets.cats.txt")
        if os.path.exists(cats_path_up):
            cats_path = cats_path_up
        else:
            print(f"Warning: Catalog file not found at {cats_path}")
            return catalog_map

    try:
        with open(cats_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                parts = line.split(":")
                if len(parts) >= 3:
                    uuid = _normalize_catalog_uuid(parts[0])
                    path = parts[1]
                    if uuid:
                        catalog_map[uuid] = path
    except Exception as e:
        print(f"Error reading catalog file: {e}")

    return catalog_map

def normalize_tag_prefix(tag):
    t = str(tag or "").strip().lower()
    if not t:
        return ""
    if ":" in t:
        prefix, value = t.split(":", 1)
        prefix = prefix.strip().lower()
        value = value.strip().lower()
        if not value:
            return ""
        if value in TAG_ALIASES:
            value = TAG_ALIASES[value]
        if prefix:
            return f"{prefix}:{value}"
        return value
    if t in TAG_ALIASES:
        t = TAG_ALIASES[t]
    base = t
    if t in CATEGORY_TAGS:
        return "cat:" + base
    if t in STYLE_TAGS:
        return "style:" + base
    if t in SURFACE_TAGS:
        return "state:" + base
    if t in PHYSICAL_TAGS:
        return "feel:" + base
    if t in USAGE_TAGS:
        return "use:" + base
    return base

def setup_preview_scene():
    """
    Sets up a simple scene for rendering material previews.
    Returns the object to apply materials to.
    """
    # Clear existing objects
    bpy.ops.object.select_all(action='SELECT')
    bpy.ops.object.delete()

    # Create a UV Sphere
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1.0, location=(0, 0, 0))
    obj = bpy.context.active_object
    bpy.ops.object.shade_smooth()

    # Add a camera
    bpy.ops.object.camera_add(location=(0, -3.5, 0), rotation=(1.5708, 0, 0)) # 90 degrees X
    cam = bpy.context.active_object
    bpy.context.scene.camera = cam

    bpy.ops.object.light_add(
        type='AREA',
        location=(-1.4886, -2.0, 2.3582),
        rotation=(math.radians(28.09), math.radians(-16.897), math.radians(-8.8181)),
    )
    light = bpy.context.active_object
    light.data.energy = 300
    if hasattr(light.data, "shape"):
        light.data.shape = "SQUARE"
    if hasattr(light.data, "size"):
        light.data.size = 3.0
    if hasattr(light.data, "spread"):
        light.data.spread = math.pi
    if hasattr(light.data, "use_shadow"):
        light.data.use_shadow = True
    if hasattr(light.data, "use_multiple_importance_sampling"):
        light.data.use_multiple_importance_sampling = True
    if hasattr(light.data, "cycles") and hasattr(light.data.cycles, "max_bounces"):
        light.data.cycles.max_bounces = 1024
    if hasattr(light.data, "cycles") and hasattr(light.data.cycles, "use_shadow_caustics"):
        light.data.cycles.use_shadow_caustics = False

    # Set render settings
    scene = bpy.context.scene
    scene.render.engine = 'BLENDER_EEVEE_NEXT' # Use EEVEE for speed, fallback to CYCLES if needed

    # Try setting GPU device if using Cycles (though Eevee is preferred for speed)
    if scene.render.engine == 'CYCLES':
        scene.cycles.samples = 16 # Reduce samples further
        scene.cycles.device = 'GPU'
        # Enable CUDA/OptiX if available
        preferences = bpy.context.preferences
        cycles_preferences = preferences.addons['cycles'].preferences
        cycles_preferences.compute_device_type = 'CUDA' # Or 'OPTIX'
        cycles_preferences.get_devices()
        for device in cycles_preferences.devices:
            device.use = True

    scene.render.resolution_x = 512
    scene.render.resolution_y = 512

    return obj

def render_preview(obj, material, temp_path):
    """
    Applies material to object and renders to temp_path.
    """
    # Assign material
    if obj.data.materials:
        obj.data.materials[0] = material
    else:
        obj.data.materials.append(material)

    # Render
    bpy.context.scene.render.filepath = temp_path
    bpy.ops.render.render(write_still=True)

def encode_image(image_path):
    """
    Encodes image to base64 data URL.
    """
    with open(image_path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:image/png;base64,{b64}"

def get_tags_from_vlm(image_data_url, material_name):
    """
    Calls Qwen-VL-Plus to generate tags.
    """
    system_prompt = """You are an expert material librarian. Analyze the provided material texture image and material name.
Generate a JSON object containing a list of 5-10 precise, descriptive visual tags.
The tags should cover the 5 semantic vectors, and each tag must be prefixed with its category:
1) Material Categories (Substrate identity) -> "cat:"
2) Stylistic Attributes (Artistic direction) -> "style:"
3) Surface States (Weathering/Age) -> "state:"
4) Physical Perceptions (Tactile/Optical properties) -> "feel:"
5) Usage Scenarios (Context) -> "use:"
Output strictly JSON.

Example:
{
  "tags": ["cat:metal", "style:brushed", "state:scratched", "feel:silver", "use:reflective", "use:industrial"]
}
"""

    user_content = [
        {"type": "text", "text": f"Generate visual tags for this material: {material_name}."},
        {"type": "image_url", "image_url": {"url": image_data_url}},
    ]

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content}
        ],
        "temperature": 0.2
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}"
    }

    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload).encode('utf-8'),
        headers=headers
    )

    try:
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            content = result['choices'][0]['message']['content']
            # Clean markdown
            if content.startswith("```json"):
                content = content[7:]
            if content.endswith("```"):
                content = content[:-3]
            data = json.loads(content)
            return data.get("tags", [])
    except Exception as e:
        print(f"Error calling API: {e}")
        return []

def main():
    args = _parse_args()

    cache_dir = args.cache_dir.strip()
    if not cache_dir:
        cache_dir = os.path.join(_repo_root(), "material_cache")

    target_catalog = args.target_catalog
    if target_catalog is None:
        target_catalog = "" if args.preview_only else TARGET_CATALOG

    target_material = args.target_material
    if target_material is None:
        target_material = "" if args.preview_only else TARGET_MATERIAL_NAME

    skip_existing = args.skip_existing
    if skip_existing is None:
        skip_existing = False if args.preview_only else SKIP_EXISTING

    # Blender Configuration for Auto-Launch
    BLENDER_EXE = os.environ.get("BLENDER_EXE") or shutil.which("blender") or ""
    BLEND_FILE = os.environ.get("MATCOMPOSER_BLEND_FILE", "")

    # Check if we are in a functional Blender environment
    valid_bpy = False
    try:
        # Check if bpy exists and has 'ops' attribute accessible
        if bpy is not None:
            # Try accessing bpy.ops to ensure it's not a dummy
            _ = bpy.ops
            valid_bpy = True
    except Exception:
        valid_bpy = False

    if not valid_bpy:
        print("Blender environment not detected (or dummy bpy found). Launching Blender background process...")
        import subprocess

        if not os.path.exists(BLENDER_EXE):
            print("Set BLENDER_EXE or add Blender to PATH; alternatively run with blender --background <file.blend> --python this_script.py.")
            return
        if not os.path.exists(BLEND_FILE):
            print("Set MATCOMPOSER_BLEND_FILE to an existing .blend file, or run this script directly with Blender.")
            return

        # Add --background to run headless
        cmd = [BLENDER_EXE, "--background", "--factory-startup", BLEND_FILE, "-P", __file__]
        script_argv = _extract_script_argv(sys.argv)
        if script_argv:
            cmd += ["--"] + script_argv
        print(f"Executing: {' '.join(cmd)}")
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            print(f"Blender process failed with exit code {e.returncode}")
        return

    if (not args.preview_only) and (not API_KEY):
        print("ERROR: Missing API key.")
        return

    print("Setting up preview scene...")
    preview_obj = setup_preview_scene()

    # Load Catalog Map
    catalog_map = load_catalog_map()

    temp_dir = tempfile.gettempdir()
    temp_img = os.path.join(temp_dir, "mat_preview_temp.png")

    preview_subdir = str(args.preview_subdir or "MyMaterials").strip().strip("/\\") or "MyMaterials"
    previews_dir = os.path.join(cache_dir, "previews", preview_subdir)
    if args.preview_only:
        os.makedirs(previews_dir, exist_ok=True)

    materials = [m for m in bpy.data.materials if m.use_nodes] # Only node materials
    total = len(materials)

    print(f"Found {total} materials in file. Scanning for processing candidates...")

    materials_to_process = []
    skipped_tagged = 0
    skipped_preview = 0
    skipped_other = 0

    for mat in materials:
        # Check Material Name
        if target_material and mat.name != target_material:
            skipped_other += 1
            continue

        # Check Catalog
        if target_catalog:
            if not mat.asset_data:
                skipped_other += 1
                continue
            cat_id = _normalize_catalog_uuid(mat.asset_data.catalog_id)
            cat_path = catalog_map.get(cat_id, "")
            # Check if path matches or is subdirectory
            # Normalize for comparison: strip slashes, lowercase
            cat_path_norm = cat_path.strip().strip("/").lower()
            target_norm = target_catalog.strip().strip("/").lower()

            if not _catalog_matches(target_norm, cat_path_norm):
                skipped_other += 1
                continue

        # Check existing tags
        if skip_existing and _has_asset_tags(getattr(mat, "asset_data", None)):
            skipped_tagged += 1
            continue

        if args.preview_only and args.skip_existing_preview:
            out_path = _preview_output_path(previews_dir, mat.name)
            if os.path.exists(out_path):
                skipped_preview += 1
                continue

        materials_to_process.append(mat)

    print("-" * 40)
    print(f"Total Materials Found: {total}")
    print(f"Skipped (Already Tagged): {skipped_tagged}")
    if args.preview_only and args.skip_existing_preview:
        print(f"Skipped (Existing Preview): {skipped_preview}")
    if skipped_other > 0:
        print(f"Skipped (Name/Catalog Filter): {skipped_other}")
    print(f"Queue to Process: {len(materials_to_process)}")
    print("-" * 40)

    count = 0
    total_process = len(materials_to_process)

    for i, mat in enumerate(materials_to_process):
        print(f"[{i+1}/{total_process}] Processing: {mat.name}...")

        if (not args.preview_only) and (not mat.asset_data):
            mat.asset_mark()

        # Render
        if args.preview_only:
            out_path = _preview_output_path(previews_dir, mat.name)
            render_preview(preview_obj, mat, out_path)
            if not os.path.exists(out_path):
                print("  Render failed.")
            else:
                print(f"  Saved preview: {out_path}")
                count += 1
            continue

        render_preview(preview_obj, mat, temp_img)
        if not os.path.exists(temp_img):
            print("  Render failed.")
            continue

        # Call AI
        img_url = encode_image(temp_img)
        tags = get_tags_from_vlm(img_url, mat.name)

        if tags:
            print(f"  Generated Tags: {tags}")
            # Clear existing if needed? Or just append? Logic here assumes we append or set fresh if empty
            # If SKIP_EXISTING is True, we only get here if empty.
            if not mat.asset_data:
                mat.asset_mark()

            for tag in tags:
                norm = normalize_tag_prefix(tag)
                if not norm:
                    continue
                exists = False
                for t in mat.asset_data.tags:
                    if t.name.lower() == norm.lower():
                        exists = True
                        break
                if not exists:
                    mat.asset_data.tags.new(norm)
            count += 1

            # Save progress every 5 materials or if it's the target material
            if count % 5 == 0 or target_material:
                print(f"  Saving progress (Processed {count})...")
                bpy.ops.wm.save_mainfile()
        else:
            print("  No tags generated.")

    print(f"Done. Processed {count} materials.")

    # Save the file
    if not args.preview_only:
        print("Saving file...")
        bpy.ops.wm.save_mainfile()
        print("File saved.")

if __name__ == "__main__":
    main()
