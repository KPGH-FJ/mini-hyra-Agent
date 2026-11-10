"""Offline repository entry-point and research-index regression checks."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProjectConsistencyTests(unittest.TestCase):
    def test_report_catalog_and_status(self):
        spec = importlib.util.spec_from_file_location("check_project", ROOT / "scripts/check_project.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.check(ROOT), [])

    def test_module_cli_matches_documented_commands(self):
        result = subprocess.run([sys.executable, "-m", "hyra", "--help"], cwd=ROOT,
                                capture_output=True, text=True, check=True)
        for command in ("run", "status", "best", "eval", "serve"):
            self.assertIn(command, result.stdout)

    def test_public_memory_facade(self):
        sys.path.insert(0, str(ROOT))
        from lifemodel import LifeModel
        self.assertIsInstance(LifeModel().state(), dict)


if __name__ == "__main__":
    unittest.main()
