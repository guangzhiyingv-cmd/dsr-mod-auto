"""Reject hidden script imports and documentation links outside the skill."""

from pathlib import Path
import tempfile
import unittest

from check_independence import audit_tree


class IndependenceTests(unittest.TestCase):
    def fixture(self, root):
        (root / "scripts").mkdir()
        (root / "references").mkdir()
        (root / "SKILL.md").write_text("[Guide](references/guide.md)", encoding="utf-8")
        (root / "README.md").write_text("Fixture", encoding="utf-8")
        (root / "references/guide.md").write_text("Guide", encoding="utf-8")

    def test_bundled_and_declared_external_imports(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "scripts/core.py").write_text("import json\nimport bpy\n", encoding="utf-8")
            (root / "scripts/main.py").write_text("from core import value\n", encoding="utf-8")
            self.assertTrue(audit_tree(root)["passed"])

    def test_hidden_workspace_code_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "scripts/main.py").write_text("import historical_character_script\n", encoding="utf-8")
            self.assertFalse(audit_tree(root)["passed"])

    def test_missing_local_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            (root / "README.md").write_text("[Missing](references/missing.md)", encoding="utf-8")
            self.assertFalse(audit_tree(root)["passed"])


if __name__ == "__main__":
    unittest.main()
