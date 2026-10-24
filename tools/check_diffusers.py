"""Import-only dependency smoke check: no weights, model construction, or CUDA work."""
import argparse
import importlib
import importlib.metadata as metadata
import json
from pathlib import Path
import sys
import traceback

from comfy_health import import_failure

try:
    from packaging.requirements import Requirement
except ImportError:
    from pip._vendor.packaging.requirements import Requirement


def check_versions():
    path = Path(__file__).resolve().parents[1] / "constraints/wan-python.txt"
    for line in path.read_text().splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        req = Requirement(line)
        if metadata.version(req.name) not in req.specifier:
            raise RuntimeError(f"Incompatible {req.name}: expected {req.specifier}, found {metadata.version(req.name)}")
    check_declared_requirements(metadata.version("diffusers"))


def check_declared_requirements(version="0.33.1"):
    # Existing installations can contain extra packages not in this repository.
    # Refuse a downgrade that violates any active declared diffusers requirement.
    for distribution in metadata.distributions():
        for raw in distribution.requires or []:
            req = Requirement(raw)
            if req.name.lower().replace("_", "-") != "diffusers":
                continue
            if req.marker and not req.marker.evaluate({"extra": ""}):
                continue
            if version not in req.specifier:
                raise RuntimeError(f"{distribution.metadata['Name']} requires {raw}")


def check():
    # Includes imports in optional wrapper code paths. getattr forces lazy
    # loader/mixin/transformer imports; importing diffusers alone is insufficient.
    manifest = json.loads(Path(__file__).with_name("wan_diffusers_imports.json").read_text())
    for module, names in manifest["imports"].items():
        loaded = importlib.import_module(module)
        for name in names:
            getattr(loaded, name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--requirements-only", action="store_true", help="Check installed requirements against candidate diffusers 0.33.1 before repair")
    args = parser.parse_args()
    try:
        if args.requirements_only:
            check_declared_requirements()
            print("Installed package requirements permit diffusers==0.33.1")
            return 0
        check_versions()
        check()
        print(f"Diffusers import smoke check passed: diffusers={metadata.version('diffusers')}, torch={metadata.version('torch')}")
        return 0
    except Exception:
        text = traceback.format_exc()
        print(text, file=sys.stderr)
        print(import_failure(text) or "Diffusers dependency import failed; inspect traceback before starting ComfyUI", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
