"""Capture/verify the actual installed CUDA wheel stack, without importing CUDA."""
import importlib.metadata as md
from pathlib import Path
import re
import sys
try:
    from packaging.requirements import Requirement
except ImportError:
    from pip._vendor.packaging.requirements import Requirement

EXPECTED = {"torch": "2.4.1+cu124", "torchvision": "0.19.1+cu124", "torchaudio": "2.4.1+cu124"}


def name(value):
    return re.sub(r"[-_.]+", "-", value).lower()


def protected(value):
    return value in EXPECTED or value.startswith("nvidia-") or value in ("triton", "pytorch-triton", "cupy", "cupy-cuda11x", "cupy-cuda12x", "cupy-cuda13x")


def snapshot():
    versions = {name(d.metadata["Name"]): d.version for d in md.distributions() if d.metadata["Name"] and protected(name(d.metadata["Name"]))}
    for package, version in EXPECTED.items():
        if versions.get(package) != version:
            raise ValueError(f"Expected {package}=={version}")
    # Validate the installed wheel's own requirements, including CUDA-specific
    # NVIDIA versions and Triton. Do not substitute PyPI's different CUDA build.
    for package in versions:
        for raw in md.requires(package) or []:
            req = Requirement(raw)
            if req.marker and not req.marker.evaluate({"extra": ""}):
                continue
            installed = md.version(req.name)
            if not req.specifier.contains(installed, prereleases=True):
                raise ValueError(f"Unsatisfied protected-stack requirement: {raw}")
    if "triton" not in versions or not any(p.startswith("nvidia-") for p in versions):
        raise ValueError("Expected Linux CUDA NVIDIA/Triton dependencies missing")
    cupy = [p for p in versions if p.startswith("cupy")]
    if cupy and cupy != ["cupy-cuda12x"]:
        raise ValueError("Conflicting CuPy distributions")
    return versions


def main():
    mode, filename = sys.argv[1:]
    path = Path(filename)
    current = snapshot()
    if mode == "capture":
        path.write_text("".join(f"{p}=={v}\n" for p, v in sorted(current.items())))
    elif mode == "check":
        expected = dict(line.split("==", 1) for line in path.read_text().splitlines())
        if current != expected:
            raise ValueError("Protected dependency set changed; stop before continuing")
    else:
        raise ValueError("Expected capture or check")


if __name__ == "__main__":
    main()
