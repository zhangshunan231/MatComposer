import bpy
import os
import subprocess
import sys


BLENDER_EXE = r"D:\software\Blender\Blender4.4\blender.exe"
BLEND_FILE = r"D:\Asset\Blender\MyMatLib\MyMaterials.blend"


def clear_all_asset_tags():
    materials = [m for m in bpy.data.materials if getattr(m, "asset_data", None)]
    total = len(materials)
    removed = 0
    for mat in materials:
        tags = mat.asset_data.tags
        try:
            count = len(tags)
        except Exception:
            count = 0
        try:
            tags.clear()
        except Exception:
            for tag in list(tags):
                try:
                    tags.remove(tag)
                except Exception:
                    pass
        removed += count
    print(f"Cleared {removed} tags from {total} materials")


def main():
    valid_bpy = False
    try:
        if bpy is not None:
            _ = bpy.ops
            valid_bpy = True
    except Exception:
        valid_bpy = False

    if not valid_bpy:
        if not os.path.exists(BLENDER_EXE):
            print(f"Error: Blender executable not found at {BLENDER_EXE}")
            return
        if not os.path.exists(BLEND_FILE):
            print(f"Error: Blend file not found at {BLEND_FILE}")
            return
        cmd = [BLENDER_EXE, BLEND_FILE, "--background", "--factory-startup", "-P", __file__]
        print(f"Executing: {' '.join(cmd)}")
        try:
            subprocess.check_call(cmd)
        except subprocess.CalledProcessError as e:
            print(f"Blender process failed with exit code {e.returncode}")
        return

    clear_all_asset_tags()
    print("Saving file...")
    bpy.ops.wm.save_mainfile()
    print("File saved.")


if __name__ == "__main__":
    main()
