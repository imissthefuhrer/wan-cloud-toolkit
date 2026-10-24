"""Offline unit tests plus opt-in real Python 3.11 import/source regressions."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import check_diffusers as smoke


class Compatibility(unittest.TestCase):
    def setUp(self):
        self.versions = {}
        for line in (ROOT / "constraints/wan-python.txt").read_text().splitlines():
            if line and not line.startswith("#"):
                key, value = line.split("==")
                self.versions[key] = value
        self.distributions = []
        patches = [patch.object(smoke.metadata, "version", side_effect=lambda n: self.versions[n]),
                   patch.object(smoke.metadata, "distributions", side_effect=lambda: self.distributions)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_tested_versions_pass(self):
        smoke.check_versions()

    def test_newer_transformers_is_rejected_before_import(self):
        self.versions["transformers"] = "5.20.2"
        with self.assertRaisesRegex(RuntimeError, "transformers"):
            smoke.check_versions()

    def test_other_package_requiring_newer_diffusers_is_rejected(self):
        self.distributions = [Mock(requires=["diffusers>=0.34.0"], metadata={"Name": "other-node"})]
        with self.assertRaisesRegex(RuntimeError, "other-node requires"):
            smoke.check_versions()

    def test_pinned_wrapper_requirement_accepts_diffusers(self):
        self.distributions = [Mock(requires=["diffusers>=0.33.0"], metadata={"Name": "wrapper-fixture"})]
        smoke.check_versions()

    def test_combined_constraints_preserve_protected_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            protected = Path(tmp) / "protected.txt"
            original = "torch==2.4.1+cu124\nnvidia-cuda-runtime-cu12==12.4.99\n"
            protected.write_text(original)
            result = subprocess.run(["bash", "-c", 'set -euo pipefail; source "$1"; use_wan_constraints "$2"; cat "$PIP_CONSTRAINT"',
                                     "test", str(ROOT / "lib/common.sh"), str(protected)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(protected.read_text(), original)
            self.assertIn(original, result.stdout)
            self.assertIn("diffusers==0.33.1", result.stdout)
            self.assertIn("transformers==4.51.3", result.stdout)


class RealImports(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("WAN_IMPORT_TEST_PYTHON"), "Set WAN_IMPORT_TEST_PYTHON to a prepared clean Python 3.11 venv")
    def test_actual_wrapper_diffusers_imports_without_torch_accelerator(self):
        code = '''import sys, torch
assert sys.version_info[:2] == (3, 11), sys.version
assert torch.__version__ == "2.4.1+cu124", torch.__version__
assert not hasattr(torch, "accelerator"), "Test must exercise the original missing-API condition"
sys.path.insert(0, sys.argv[1])
import check_diffusers
check_diffusers.check_versions()
check_diffusers.check()
print("PASS: all pinned-wrapper diffusers imports on Python 3.11/Torch 2.4.1+cu124 without torch.accelerator")
'''
        env = {**os.environ, "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "CUDA_VISIBLE_DEVICES": "", "PYTHONNOUSERSITE": "1"}
        result = subprocess.run([os.environ["WAN_IMPORT_TEST_PYTHON"], "-B", "-s", "-c", code, str(ROOT / "tools")],
                                env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: all pinned-wrapper", result.stdout)

    @unittest.skipUnless(os.environ.get("WAN_WRAPPER_SOURCE"), "Set WAN_WRAPPER_SOURCE to audited pinned source")
    def test_manifest_matches_pinned_source(self):
        found = {}
        for path in Path(os.environ["WAN_WRAPPER_SOURCE"]).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.ImportFrom) and node.module and (node.module == "diffusers" or node.module.startswith("diffusers.")):
                    found.setdefault(node.module, set()).update(n.name for n in node.names)
        manifest = json.loads((ROOT / "tools/wan_diffusers_imports.json").read_text())
        self.assertEqual(manifest["revision"], "e926f7a069e3efc25bdcc78e1bf65c39ac1a2cd4")
        self.assertEqual({m: sorted(names) for m, names in found.items()}, manifest["imports"])


class RepairControlFlow(unittest.TestCase):
    def run_repair(self, fail_match):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "venv/bin").mkdir(parents=True)
        python = root / "venv/bin/python"
        python.write_text('''#!/bin/bash
printf '%s\\n' "$*" >> "$CALL_LOG"
if [[ -n "$FAIL_MATCH" && "$*" == *"$FAIL_MATCH"* ]]; then exit 9; fi
exit 0
''')
        python.chmod(0o755)
        (root / "wan-cloud-constraints.txt").write_text("torch==2.4.1+cu124\n")
        log = root / "calls"
        result = subprocess.run(["bash", str(ROOT / "install/compat.sh")],
                                env={**os.environ, "COMFY_DIR": str(root), "CALL_LOG": str(log), "FAIL_MATCH": fail_match},
                                capture_output=True, text=True)
        return result, log.read_text().splitlines()

    def test_protected_mismatch_stops_before_pip(self):
        result, calls = self.run_repair("protect_stack.py")
        self.assertEqual(result.returncode, 9)
        self.assertEqual(len(calls), 1)

    def test_conflicting_diffusers_requirement_stops_before_pip(self):
        result, calls = self.run_repair("--requirements-only")
        self.assertEqual(result.returncode, 9)
        self.assertFalse(any("-m pip" in call for call in calls))

    def test_dry_run_failure_stops_before_install(self):
        result, calls = self.run_repair("--dry-run")
        self.assertEqual(result.returncode, 9)
        self.assertFalse(any("-m pip install -c" in call for call in calls))

    def test_success_checks_snapshot_before_and_after_install(self):
        result, calls = self.run_repair("")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("protect_stack.py", calls[0])
        self.assertIn("--dry-run", calls[2])
        self.assertIn("-m pip install -c", calls[3])
        self.assertIn("protect_stack.py", calls[4])
        self.assertEqual(calls[5], "-m pip check")
        self.assertTrue(calls[6].endswith("tools/check_diffusers.py"))
