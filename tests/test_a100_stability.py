"""A100 stabilization regressions; no GPU, package installs, or network access."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
COMMIT = "5d4cc3ba1b412b9acacd37fd23d59e0e1654f83c"
spec = importlib.util.spec_from_file_location("headers", ROOT / "tools/check_python_headers.py")
headers = importlib.util.module_from_spec(spec)
spec.loader.exec_module(headers)


class Workflow(unittest.TestCase):
    def setUp(self):
        self.workflow = json.loads((ROOT / "workflows/Wan22-I2V-Remix.json").read_text())

    def test_both_loaders_have_no_compile_input(self):
        loaders = [n for n in self.workflow["nodes"] if n["type"] == "WanVideoModelLoader"]
        self.assertEqual({n["id"] for n in loaders}, {131, 132})
        for node in loaders:
            inputs = {i["name"]: i for i in node["inputs"]}
            self.assertIsNone(inputs["compile_args"]["link"])
            self.assertIsNotNone(inputs["block_swap_args"]["link"])
            self.assertIsNotNone(inputs["lora"]["link"])
        self.assertFalse(any(n["type"] == "WanVideoTorchCompileSettings" for n in self.workflow["nodes"]))
        self.assertFalse(any(link[5] == "WANCOMPILEARGS" for link in self.workflow["links"]))

    def test_all_link_references_agree_in_both_directions(self):
        nodes = {n["id"]: n for n in self.workflow["nodes"]}
        links = {link[0]: link for link in self.workflow["links"]}
        self.assertEqual(len(nodes), len(self.workflow["nodes"]))
        self.assertEqual(len(links), len(self.workflow["links"]))
        for lid, src, slot, dst, input_slot, _ in links.values():
            self.assertEqual(nodes[dst]["inputs"][input_slot]["link"], lid)
            self.assertEqual(nodes[src]["outputs"][slot]["links"].count(lid), 1)
        for nid, node in nodes.items():
            for slot, item in enumerate(node.get("inputs", [])):
                if item.get("link") is not None:
                    self.assertEqual(links[item["link"]][3:5], [nid, slot])
            for slot, item in enumerate(node.get("outputs", [])):
                for lid in item.get("links") or []:
                    self.assertEqual(links[lid][1:3], [nid, slot])

    def test_every_other_workflow_setting_is_preserved(self):
        # Baseline bb732a5 with ONLY node 127 and links 263/266 removed, and
        # the two compile_args inputs set to null. Normalize the separately
        # tested duration change back to 65; preserve every other field.
        next(n for n in self.workflow["nodes"] if n["id"] == 156)["widgets_values"][2] = 65
        digest = hashlib.sha256(json.dumps(self.workflow, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(digest, "167dc94bdc8fbe2ab1daa6d260b092c038672d05e709496ce8ca178d333c723b")

    def test_seven_second_duration_preserves_interpolation_and_fps(self):
        nodes = {n["id"]: n for n in self.workflow["nodes"]}
        self.assertEqual(nodes[156]["type"], "WanVideoImageToVideoEncode")
        frames = nodes[156]["widgets_values"][2]
        multiplier = nodes[115]["widgets_values"][2]
        fps = nodes[116]["widgets_values"][0]
        self.assertEqual((frames, multiplier, fps), (113, 2, 32))
        self.assertEqual((frames - 1) % 4, 0)
        # RIFE inserts one frame between each pair at 2x and keeps the last.
        output_frames = (frames - 1) * multiplier + 1
        self.assertEqual(output_frames, 225)
        self.assertAlmostEqual(output_frames / fps, 7.03125)


class Headers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name)
        patches = [patch.object(headers.sys, "version_info", (3, 11, 9)),
                   patch.object(headers.sysconfig, "get_paths", return_value={"include": str(self.path)}),
                   patch.object(headers.sysconfig, "get_config_var", return_value=None)]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_matching_active_headers_pass(self):
        for name in ("Python.h", "pyconfig.h"):
            (self.path / name).write_text("/* header fixture */")
        headers.check()

    def test_missing_headers_give_actionable_error(self):
        with self.assertRaisesRegex(RuntimeError, "python3.11-dev.*sysconfig include paths"):
            headers.check()

    def test_python_h_alone_is_insufficient(self):
        (self.path / "Python.h").write_text("/* header fixture */")
        with self.assertRaisesRegex(RuntimeError, "pyconfig.h"):
            headers.check()

    def test_another_interpreters_headers_are_not_accepted(self):
        for name in ("Python.h", "pyconfig.h"):
            (self.path / name).write_text("/* header fixture */")
        with patch.object(headers.sys, "version_info", (3, 12, 0)):
            with self.assertRaisesRegex(RuntimeError, "Python 3.11"):
                headers.check()


class Installation(unittest.TestCase):
    def test_comfy_pin_and_wan22_verification(self):
        for file in ("install/comfyui.sh", "install/verify.sh"):
            text = (ROOT / file).read_text()
            self.assertIn(COMMIT, text)
            self.assertIn("0.3.46", text)
            self.assertNotIn("9a470e073e2742d4edd6e7ea1ce28d861a77d9c4", text)
            self.assertNotIn("0.3.45", text)
        self.assertIn("from comfy.latent_formats import Wan22", (ROOT / "install/verify.sh").read_text())

    def test_header_checks_cover_system_and_active_venv(self):
        for file in ("install/python.sh", "install/comfyui.sh", "install/verify.sh"):
            self.assertIn("tools/check_python_headers.py", (ROOT / file).read_text())
        text = (ROOT / "install/apt.sh").read_text()
        self.assertIn("for package in python3.11 python3.11-venv python3.11-dev;", text)
        self.assertIn("apt-get install -y python3.11 python3.11-venv python3.11-dev", text)

    def test_dev_package_installed_even_when_python_already_works(self):
        # Execute only the prerequisite decision block with shell command mocks.
        block = (ROOT / "install/apt.sh").read_text().split("# Ubuntu's default python3", 1)[1]
        block = block[block.index("if ! command"):block.index('log_success "System packages complete."')]
        prefix = '''set -euo pipefail
APT_PREFIX=(record)
python3.11() { return 0; }
dpkg-query() { if [[ "$PRESENT" == yes ]]; then printf 'install ok installed'; else return 1; fi; }
apt-cache() { printf 'Candidate: 1\\n'; }
record() { printf '%s\\n' "$*"; }
'''
        missing = subprocess.run(["bash", "-c", prefix + block], env={**os.environ, "PRESENT": "no"}, capture_output=True, text=True)
        self.assertEqual(missing.returncode, 0, missing.stderr)
        self.assertIn("apt-get install -y python3.11 python3.11-venv python3.11-dev", missing.stdout)
        present = subprocess.run(["bash", "-c", prefix + block], env={**os.environ, "PRESENT": "yes"}, capture_output=True, text=True)
        self.assertEqual(present.returncode, 0, present.stderr)
        self.assertEqual(present.stdout, "")

    def test_protected_pins_unchanged(self):
        text = (ROOT / "install/comfyui.sh").read_text()
        for key, value in (("PYTORCH_VERSION", "2.4.1"), ("TORCHVISION_VERSION", "0.19.1"), ("TORCHAUDIO_VERSION", "2.4.1")):
            self.assertIn(f'{key}="{value}"', text)
        self.assertIn("https://download.pytorch.org/whl/cu124", text)
        nodes = (ROOT / "install/nodes.sh").read_text()
        for revision in ("e926f7a0", "ffd4d1c908af896ed720d2edcd5cd151e5a06e70", "a1b402b", "aac13aa7ce35b07d43633c3bbe654a38c00d74f5", "a969c01dbccd9e5510641be04eb51fe93f6bfc3d"):
            self.assertIn(revision, nodes)
        self.assertIn('"sageattention==1.0.6"', nodes)
        self.assertIn('"cupy-cuda12x==13.3.0"', nodes)

    def test_dirty_checkout_is_refused_and_untracked_data_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            def git(*args):
                subprocess.run(["git", "-C", tmp, *args], check=True, capture_output=True)
            git("init")
            (directory / "tracked.txt").write_text("original")
            git("add", "tracked.txt")
            git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "commit", "-m", "fixture")
            for name in ("models/sentinel", "output/sentinel", "venv/sentinel"):
                p = directory / name
                p.parent.mkdir(exist_ok=True)
                p.write_text("preserve")
            command = ["bash", "-c", 'set -euo pipefail; source "$1"; require_clean_checkout "$2"', "test", str(ROOT / "lib/common.sh"), tmp]
            for _ in range(2):
                self.assertEqual(subprocess.run(command, capture_output=True).returncode, 0)
            (directory / "tracked.txt").write_text("user edit")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Tracked local changes", result.stdout)
            self.assertEqual((directory / "tracked.txt").read_text(), "user edit")
            for p in directory.glob("*/sentinel"):
                self.assertEqual(p.read_text(), "preserve")

    def test_checkout_guards_precede_fetch(self):
        for file, variable in (("install/comfyui.sh", "COMFY_DIR"), ("install/nodes.sh", "dir")):
            text = (ROOT / file).read_text()
            self.assertLess(text.index(f'require_clean_checkout "${variable}"'), text.index(f'git -C "${variable}" fetch'))
