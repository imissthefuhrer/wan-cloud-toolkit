"""Exercise protection decisions with package metadata fixtures; no pip/GPU."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("protect_stack", Path(__file__).resolve().parents[1] / "tools/protect_stack.py")
stack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stack)


class Distribution:
    def __init__(self, name, version):
        self.metadata = {"Name": name}
        self.version = version


class Protection(unittest.TestCase):
    def setUp(self):
        self.versions = {**stack.EXPECTED, "nvidia-cuda-runtime-cu12": "12.4.127", "triton": "3.0.0"}
        self.requirements = {"torch": ['nvidia-cuda-runtime-cu12==12.4.127; platform_system == "Linux"', "triton==3.0.0"]}
        patches = [patch.object(stack.md, "distributions", side_effect=lambda: [Distribution(n, v) for n, v in self.versions.items()]),
                   patch.object(stack.md, "requires", side_effect=lambda n: self.requirements.get(n, [])),
                   patch.object(stack.md, "version", side_effect=lambda n: self.versions[n])]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_capture_and_check_preserve_full_cuda_versions(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "constraints")
            with patch.object(stack.sys, "argv", ["tool", "capture", target]):
                stack.main()
            self.assertIn("torch==2.4.1+cu124", Path(target).read_text())
            self.assertIn("nvidia-cuda-runtime-cu12==12.4.127", Path(target).read_text())
            with patch.object(stack.sys, "argv", ["tool", "check", target]):
                stack.main()
                self.versions["nvidia-nvjitlink-cu12"] = "12.4.127"
                with self.assertRaisesRegex(ValueError, "set changed"):
                    stack.main()

    def test_wrong_cuda_torch_build_is_rejected(self):
        self.versions["torch"] = "2.4.1+cu121"
        with self.assertRaisesRegex(ValueError, "Expected torch"):
            stack.snapshot()

    def test_incompatible_nvidia_version_is_rejected(self):
        self.versions["nvidia-cuda-runtime-cu12"] = "12.1.105"
        with self.assertRaisesRegex(ValueError, "Unsatisfied"):
            stack.snapshot()

    def test_conflicting_cupy_distributions_are_rejected(self):
        self.versions.update({"cupy-cuda12x": "13.3.0", "cupy": "13.3.0"})
        with self.assertRaisesRegex(ValueError, "Conflicting CuPy"):
            stack.snapshot()

    def test_cupy_numpy_requirement_is_checked(self):
        self.versions.update({"cupy-cuda12x": "13.3.0", "numpy": "2.3.0"})
        self.requirements["cupy-cuda12x"] = ["numpy>=1.22,<2.3"]
        with self.assertRaisesRegex(ValueError, "Unsatisfied"):
            stack.snapshot()
