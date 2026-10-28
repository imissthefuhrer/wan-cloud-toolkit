"""Check headers for the active interpreter; no compilation or GPU operations."""
from pathlib import Path
import sys
import sysconfig


def check():
    if sys.version_info[:2] != (3, 11):
        raise RuntimeError("Python 3.11 is required for the ComfyUI environment")
    paths = sysconfig.get_paths()
    roots = {Path(p) for p in (paths.get("include"), paths.get("platinclude"),
                              sysconfig.get_config_var("INCLUDEPY"),
                              sysconfig.get_config_var("CONFINCLUDEPY")) if p}
    missing = [name for name in ("Python.h", "pyconfig.h")
               if not any((root / name).is_file() and (root / name).stat().st_size for root in roots)]
    if missing:
        raise RuntimeError(
            f"Missing active Python 3.11 development headers: {', '.join(missing)}. "
            f"Interpreter: {sys.executable}; searched: {', '.join(sorted(map(str, roots)))}. "
            "Install python3.11-dev (apt-get install -y python3.11-dev), then rerun this check "
            "with the ComfyUI venv Python. A template-provided /usr/local or custom Python "
            "needs matching headers at its sysconfig include paths; distro headers alone may not suffice. "
            "Do not replace the venv or CUDA stack to hide this error.")
    print("Python 3.11 development headers found at active sysconfig paths")


if __name__ == "__main__":
    try:
        check()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
