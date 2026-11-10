# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors

"""Build a clean Blender add-on ZIP from an explicit set of runtime files."""

import ast
from pathlib import Path
import re
from zipfile import ZIP_DEFLATED, ZipFile


def main():
    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "__init__.py").read_text(encoding="utf-8"))
    metadata = next(
        ast.literal_eval(node.value)
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "bl_info" for t in node.targets)
    )
    version = ".".join(str(part) for part in metadata["version"])
    paths = [root / name for name in (
        "__init__.py", "operators.py", "ui.py", "llm_handler.py", "LICENSE",
        "THIRD_PARTY_NOTICES.md", "README.md", "README.zh-CN.md",
        "CONTRIBUTING.md", "CITATION.cff", "citation.bib",
    )]
    paths.extend((root / "utils").glob("*.py"))
    paths.extend((root / "docs").glob("*.md"))
    paths.extend(
        p for p in (root / "masks").rglob("*")
        if p.is_file() and p.suffix.lower() in {".blend", ".jpg", ".png", ".json", ".txt"}
    )
    secret = re.compile(rb"(?:sk-[A-Za-z0-9_-]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
    for path in paths:
        if not path.is_file():
            raise SystemExit(f"Required package file is missing: {path.relative_to(root)}")
        if secret.search(path.read_bytes()):
            raise SystemExit(f"Possible credential in package input: {path.relative_to(root)}")
    output = root / "dist" / f"MatComposer-{version}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(set(paths)):
            archive.write(path, f"MatComposer/{path.relative_to(root).as_posix()}")
    print(f"Built {output} ({len(set(paths))} files)")


if __name__ == "__main__":
    main()
