# Contributing

Please report a bug with the Blender version, operating system, reproduction steps, expected behavior, actual behavior, and relevant console output. Remove API keys and private paths before posting logs.

For code changes, keep the Blender add-on importable without optional preprocessing dependencies. Test registration and the affected workflow in Blender 4.4.x. Pure Python syntax can be checked with `python -m compileall -q __init__.py llm_handler.py operators.py ui.py utils scripts`.

Build an installation package with `python scripts/package_addon.py`. Generated packages, Python bytecode, local configuration, embeddings, preview caches, and Blender backups should remain untracked.

The credential-persistence regression check saves a temporary scene and reopens it in a fresh Blender process:

```sh
blender --background --factory-startup --python-exit-code 1 --python tests/blender_api_key_persistence.py
```

Submit source-code contributions under GPL-3.0-only. Do not attach third-party materials without redistribution permission; identify the source and license for any proposed asset contribution.

Enable this repository's credential checks after cloning:

```sh
git config core.hooksPath .githooks
```

The pre-commit hook scans staged content, and the pre-push hook scans reachable Git history. Run them manually with `python scripts/check_secrets.py --staged` or `python scripts/check_secrets.py --all-history`. Findings report file names without revealing credential values. Pattern matching is a safeguard, not a replacement for reviewing changes and keeping secrets in environment variables.
