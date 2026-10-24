#!/usr/bin/env bash

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/../lib/common.sh"

COMFY_DIR="${COMFY_DIR:-/workspace/ComfyUI}"
CUSTOM_NODES="$COMFY_DIR/custom_nodes"
PYTHON="$COMFY_DIR/venv/bin/python"

banner

if [[ ! -d "$COMFY_DIR" ]]; then
    log_error "ComfyUI not found at $COMFY_DIR"
    exit 1
fi

if [[ ! -x "$PYTHON" ]]; then
    log_error "ComfyUI Python environment not found."
    exit 1
fi

# Inherited by every pip invocation, including any subprocess installers.
CONSTRAINTS_FILE="$COMFY_DIR/wan-cloud-constraints.txt"
if [[ ! -f "$CONSTRAINTS_FILE" ]]; then
    log_error "Missing Torch constraints; run install/comfyui.sh first."
    exit 1
fi
"$PYTHON" "$SCRIPT_DIR/../tools/protect_stack.py" check "$CONSTRAINTS_FILE"
use_wan_constraints "$CONSTRAINTS_FILE"

mkdir -p "$CUSTOM_NODES"

########################################
# Install exact custom-node revisions
########################################

install_node_repo() {
    local name="$1"
    local url="$2"
    local revision="$3"
    local dir="$CUSTOM_NODES/$name"

    if [[ -d "$dir/.git" ]]; then
        log_info "$name repository already exists."
    else
        log_info "Cloning $name..."
        git clone "$url" "$dir"
    fi

    git -C "$dir" fetch --all --tags

    log_info "Checking out $name revision $revision..."

    git -C "$dir" checkout --detach "$revision"

    log_success "$name pinned to $(git -C "$dir" rev-parse --short HEAD)."
}

########################################
# Versions matching supplied workflow
########################################

install_node_repo \
    "ComfyUI-WanVideoWrapper" \
    "https://github.com/kijai/ComfyUI-WanVideoWrapper.git" \
    "e926f7a0"

install_node_repo \
    "ComfyUI-KJNodes" \
    "https://github.com/kijai/ComfyUI-KJNodes.git" \
    "ffd4d1c908af896ed720d2edcd5cd151e5a06e70"

install_node_repo \
    "ComfyUI-Easy-Use" \
    "https://github.com/yolain/ComfyUI-Easy-Use.git" \
    "a1b402b"

install_node_repo \
    "ComfyUI-Custom-Scripts" \
    "https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git" \
    "aac13aa7ce35b07d43633c3bbe654a38c00d74f5"

install_node_repo \
    "ComfyUI-Frame-Interpolation" \
    "https://github.com/Fannovel16/ComfyUI-Frame-Interpolation.git" \
    "a969c01dbccd9e5510641be04eb51fe93f6bfc3d"

########################################
# Install Python requirements
########################################

install_requirements() {
    local name="$1"
    local requirements="$CUSTOM_NODES/$name/requirements.txt"

    if [[ -f "$requirements" ]]; then
        log_info "Installing requirements for $name..."

        "$PYTHON" -m pip install -r "$requirements"

        "$PYTHON" "$SCRIPT_DIR/../tools/protect_stack.py" check "$CONSTRAINTS_FILE"
        log_success "$name requirements installed."
    else
        log_info "$name has no requirements.txt; skipping."
    fi
}

# Establish the configured backend before any other custom-node requirements.
VFI_DIR="$CUSTOM_NODES/ComfyUI-Frame-Interpolation"
VFI_BACKEND="$("$PYTHON" - "$VFI_DIR/config.yaml" <<'PYTHON'
import sys, yaml
with open(sys.argv[1]) as f:
    print(yaml.safe_load(f)["ops_backend"])
PYTHON
)"
case "$VFI_BACKEND" in
    cupy)
        # CuPy 13.3 supports Python 3.11/CUDA 12.x; its metadata requires
        # numpy>=1.22,<2.3. Install under the existing Torch/CUDA constraints.
        "$PYTHON" -m pip install "cupy-cuda12x==13.3.0"
        ;;
    taichi) "$PYTHON" -m pip install taichi ;;
    *) log_error "Unsupported VFI backend: $VFI_BACKEND"; exit 1 ;;
esac
# Preserve the original Torch/NVIDIA/Triton snapshot while adding CuPy.
"$PYTHON" "$SCRIPT_DIR/../tools/protect_stack.py" capture "$CONSTRAINTS_FILE.next"
"$PYTHON" - "$CONSTRAINTS_FILE" "$CONSTRAINTS_FILE.next" <<'PYTHON'
import sys
from pathlib import Path
old = set(Path(sys.argv[1]).read_text().splitlines())
new = set(Path(sys.argv[2]).read_text().splitlines())
if not old <= new:
    raise SystemExit("Backend installation changed the protected stack")
PYTHON
mv -- "$CONSTRAINTS_FILE.next" "$CONSTRAINTS_FILE"
use_wan_constraints "$CONSTRAINTS_FILE"

install_requirements "ComfyUI-WanVideoWrapper"
install_requirements "ComfyUI-KJNodes"
install_requirements "ComfyUI-Easy-Use"
install_requirements "ComfyUI-Custom-Scripts"
# Avoid the pinned node's unchecked install.py shell calls.
"$PYTHON" -m pip install -r "$VFI_DIR/requirements-no-cupy.txt"
"$PYTHON" "$SCRIPT_DIR/../tools/protect_stack.py" check "$CONSTRAINTS_FILE"
if [[ "$VFI_BACKEND" == cupy ]]; then
    "$PYTHON" -c 'import cupy; assert cupy.arange(3).sum().item() == 3'
fi

########################################
# SageAttention
########################################

log_info "Installing SageAttention..."

"$PYTHON" -m pip install \
    "sageattention==1.0.6"

if "$PYTHON" -c "from sageattention import sageattn" >/dev/null 2>&1; then
    log_success "SageAttention installed and import verified."
else
    log_error "SageAttention installation failed."
    exit 1
fi

########################################
# RIFE 4.7 model
########################################

# Honor the node's configured checkpoint root (default: ckpts/rife).
RIFE_MODEL="$("$PYTHON" - "$VFI_DIR" <<'PYTHON'
import os, sys, yaml
root = sys.argv[1]
with open(os.path.join(root, "config.yaml")) as f:
    config = yaml.safe_load(f)
print(os.path.abspath(os.path.join(root, config["ckpts_path"], "rife", "rife47.pth")))
PYTHON
)"

"$PYTHON" "$SCRIPT_DIR/../tools/protect_stack.py" check "$CONSTRAINTS_FILE"
"$PYTHON" -m pip check
"$PYTHON" "$SCRIPT_DIR/../tools/check_diffusers.py"
# Verify the exact stack again after every custom-node dependency was installed.
"$PYTHON" - <<'PYTHON'
import torch, torchvision, torchaudio
assert torch.__version__ == "2.4.1+cu124", torch.__version__
assert torchvision.__version__ == "0.19.1+cu124", torchvision.__version__
assert torchaudio.__version__ == "2.4.1+cu124", torchaudio.__version__
assert torch.version.cuda == "12.4", torch.version.cuda
assert torch.cuda.is_available(), "CUDA unavailable"
PYTHON
# Import the actual interpolation node with ComfyUI on sys.path.
(cd "$COMFY_DIR" && "$PYTHON" - "$VFI_DIR" <<'PYTHON'
import importlib.util, sys
spec = importlib.util.spec_from_file_location("wan_vfi_check", sys.argv[1] + "/__init__.py",
                                            submodule_search_locations=[sys.argv[1]])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
assert "RIFE VFI" in module.NODE_CLASS_MAPPINGS
PYTHON
)

download_model \
    "https://huggingface.co/marduk191/rife/resolve/main/rife47.pth" \
    "$RIFE_MODEL"

########################################
# Summary
########################################

echo
log_success "Custom node installation complete."

echo
echo "Pinned custom nodes:"

for node in \
    ComfyUI-WanVideoWrapper \
    ComfyUI-KJNodes \
    ComfyUI-Easy-Use \
    ComfyUI-Custom-Scripts \
    ComfyUI-Frame-Interpolation
do

    printf "  %-35s %s\n" \
        "$node" \
        "$(git -C "$CUSTOM_NODES/$node" rev-parse --short HEAD)"

done

echo
echo "RIFE model:"
ls -lh "$RIFE_MODEL"
