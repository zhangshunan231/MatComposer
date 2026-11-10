# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

"""Clear asset tags in an explicitly opened Blender file; save only with --save."""
import argparse
import sys
try:
    import bpy
except ImportError:
    bpy = None


def clear_all_asset_tags():
    materials = [m for m in bpy.data.materials if getattr(m, "asset_data", None)]
    removed = 0
    for mat in materials:
        tags = mat.asset_data.tags
        removed += len(tags)
        for tag in list(tags):
            tags.remove(tag)
    print(f"Cleared {removed} tags from {len(materials)} materials")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--save", action="store_true", help="Save the opened .blend file")
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    args = parser.parse_args(argv)
    if bpy is None or not hasattr(bpy, "ops"):
        raise SystemExit("Run with: blender --background <file.blend> --python scripts/clear_asset_tags.py -- [--save]")
    if not bpy.data.filepath:
        raise SystemExit("Open an existing .blend file before clearing tags.")
    clear_all_asset_tags()
    if args.save:
        bpy.ops.wm.save_mainfile()
        print("File saved.")
    else:
        print("Changes were not saved. Pass --save to write them to the opened file.")


if __name__ == "__main__":
    main()
