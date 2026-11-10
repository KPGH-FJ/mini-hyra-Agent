"""Exercise real script exit statuses with small, fixed synthetic clauses."""
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROGRAM = """
import sys
sys.path.insert(0, 'tests')
import test_lifemodel_contract as suite
class Asset:
    def __init__(self, valid):
        self.valid = valid
def clause(asset):
    assert asset.valid, 'synthetic contract failure'
suite.CASES = [('synthetic clause', clause)]
suite.IMPLS = {'lm': lambda: Asset(LM_VALID), 'raw': lambda: Asset(False)}
sys.exit(suite.main())
"""


class ContractExitStatusTests(unittest.TestCase):
    def run_suite(self, *args, lm_valid=True):
        return subprocess.run(
            [sys.executable, "-B", "-c",
             PROGRAM.replace("LM_VALID", repr(lm_valid)), *args],
            cwd=ROOT, text=True, capture_output=True, timeout=10)

    def test_default_baseline_divergence_is_diagnostic(self):
        result = self.run_suite()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("raw: 0/1 conformant", result.stdout)
        self.assertIn("Diagnostic baselines (not exit-status gates): raw", result.stdout)
        self.assertIn("Exit-status gates: lm", result.stdout)

    def test_lifemodel_failure_is_nonzero(self):
        result = self.run_suite(lm_valid=False)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("lm: 0/1 conformant", result.stdout)

    def test_strict_selected_baseline_failure_is_nonzero(self):
        result = self.run_suite("--strict", "raw")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Exit-status gates: raw", result.stdout)

    def test_baseline_only_run_is_explicitly_diagnostic(self):
        result = self.run_suite("raw")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("Exit-status gates: none (diagnostic run)", result.stdout)

    def test_strict_default_checks_all_selected_implementations(self):
        result = self.run_suite("--strict")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Exit-status gates: lm, raw", result.stdout)

    def test_unknown_implementation_is_usage_error(self):
        result = self.run_suite("typo")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unknown implementation(s): typo", result.stderr)


if __name__ == "__main__":
    unittest.main()
