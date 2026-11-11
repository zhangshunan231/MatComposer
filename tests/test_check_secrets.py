# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 MatComposer authors
"""Exercise staged and historical credential blocking in disposable repositories."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SCANNER = Path(__file__).resolve().parents[1] / "scripts" / "check_secrets.py"


class CredentialScanTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="matcomposer-secret-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Credential scan test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", str(self.root / "unused-hooks"))

    def git(self, *args):
        return subprocess.run(
            ["git", *args], cwd=self.root, check=True, capture_output=True
        )

    def stage(self, content):
        (self.root / "config.txt").write_bytes(content)
        self.git("add", "config.txt")

    def scan(self, option):
        return subprocess.run(
            [sys.executable, str(SCANNER), option], cwd=self.root, capture_output=True
        )

    def test_clean_index_passes(self):
        self.stage(b'API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")\n')
        self.assertEqual(self.scan("--staged").returncode, 0)

    def test_staged_key_blocked_without_value_disclosure(self):
        synthetic_key = b"sk-" + b"a" * 32
        self.stage(synthetic_key)
        result = self.scan("--staged")
        self.assertEqual(result.returncode, 1)
        self.assertIn(b"config.txt", result.stdout)
        self.assertNotIn(synthetic_key, result.stdout + result.stderr)

    def test_history_blocks_key_even_after_latest_file_is_clean(self):
        synthetic_key = b"sk-" + b"b" * 32
        self.stage(synthetic_key)
        self.git("commit", "-qm", "Synthetic historical fixture")
        self.stage(b"API_KEY is configured through the environment\n")
        self.git("commit", "-qm", "Clean current fixture")
        self.assertEqual(self.scan("--staged").returncode, 0)
        result = self.scan("--all-history")
        self.assertEqual(result.returncode, 1)
        self.assertNotIn(synthetic_key, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
