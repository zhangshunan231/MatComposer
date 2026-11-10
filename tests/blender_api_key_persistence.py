# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors
"""Run with blender --background --factory-startup --python-exit-code 1 --python this_file.py."""

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import bpy


def main():
    os.environ["DASHSCOPE_API_KEY"] = ""
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location(
        "MatComposer", root / "__init__.py", submodule_search_locations=[str(root)]
    )
    addon = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = addon
    spec.loader.exec_module(addon)
    addon.register()
    try:
        args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
        if args:
            bpy.ops.wm.open_mainfile(filepath=args[0])
            props = bpy.context.scene.mat_composer
            assert props.api_key == "", "API key leaked across Blender processes"
            assert "api_key" not in props, "API key serialized as an ID property"
            print("PASS: fresh process reads no saved API key")
            return
        props = bpy.context.scene.mat_composer
        props.api_key = "test-session-value"
        assert props.api_key == "test-session-value"
        assert "api_key" not in props
        with tempfile.TemporaryDirectory(prefix="matcomposer-key-test-") as directory:
            scene = str(Path(directory) / "scene.blend")
            bpy.ops.wm.save_as_mainfile(filepath=scene)
            subprocess.run([
                bpy.app.binary_path, "--background", "--factory-startup",
                "--python-exit-code", "1", "--python", str(Path(__file__).resolve()),
                "--", scene,
            ], check=True, env=os.environ.copy())
            props["api_key"] = "test-legacy-value"
            bpy.ops.wm.save_as_mainfile(filepath=scene)
            bpy.ops.wm.open_mainfile(filepath=scene)
            assert "api_key" not in bpy.context.scene.mat_composer
            print("PASS: file-load handler removes legacy stored API keys")
    finally:
        addon.unregister()


if __name__ == "__main__":
    main()
