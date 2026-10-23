# WAN Cloud Toolkit

Installer and launcher for a pinned ComfyUI/Wan video workflow on a **RunPod NVIDIA GPU pod**. These scripts run inside the rented pod, with persistent storage mounted at `/workspace`.

## Pod requirements

- Ubuntu with root access or sudo. Ubuntu 22.04/24.04 are supported for automatic Python 3.11 provisioning.
- An NVIDIA GPU and driver compatible with the pinned PyTorch 2.4.1 CUDA 12.4 wheels. This stack predates Blackwell; choose compatible hardware rather than assuming every RunPod GPU is supported.
- Sufficient persistent disk and VRAM for the 14B workflow, its two diffusion models, text encoder, LoRAs, and dependencies. Check actual model sizes before renting storage.
- HTTPS access to Ubuntu package servers, GitHub, PyPI, `download.pytorch.org`, Hugging Face, and its redirected artifact hosts. If Python 3.11 is absent from the configured Ubuntu repositories, setup adds the signed Deadsnakes PPA on Ubuntu 22.04/24.04. A template-provided Python 3.11 with venv/ensurepip support is reused.

## Install and start

From the toolkit checkout on the pod:

```bash
./bootstrap.sh                 # Install UI, custom nodes, and RIFE checkpoint
./start.sh                     # Start UI; large Wan model files may be absent
```

To install and check the complete supplied workflow:

```bash
./bootstrap.sh --with-models
./start.sh --full
```

Or download the Wan models later:

```bash
./install/models.sh
./install/verify.sh            # Full installation and model presence checks
```

`./install/verify.sh --basic` checks the installation without requiring workflow model files. Neither verification mode runs a video generation; full verification checks model presence, while the download commands verify model SHA-256 and size against Hugging Face LFS metadata. Rerun the installers to validate previously downloaded files.

The default ComfyUI directory is `/workspace/ComfyUI`. Set **exported** `COMFY_DIR` to use another directory. `COMFY_PORT` defaults to `8888`; configure the same HTTP port in RunPod. If another service uses that port, choose an available one:

```bash
export COMFY_DIR=/workspace/ComfyUI
export COMFY_PORT=8188
./start.sh
```

Upload an input image and load `workflows/Wan22-I2V-Remix.json` in ComfyUI. The workflow's saved image filename is an example and must be replaced with your uploaded image.

## Installation behavior

- ComfyUI and custom-node Git revisions are pinned. Dependency installations inherit the Torch constraints, and the node installer finishes with `pip check`, exact Torch/CUDA version checks, and an interpolation-node import check.
- Frame Interpolation uses its `requirements-no-cupy.txt` and configured backend. The default CuPy backend uses `cupy-cuda12x`; the GPU check exercises a small CuPy operation. The pod must provide working CUDA runtime/compiler libraries for this backend.
- RIFE is stored under the node's configured `ckpts_path`, in its `rife` subdirectory (default `ckpts/rife/rife47.pth`). The former `models/rife47.pth` location is no longer used.
- Downloads remain in `.part` files until size and SHA-256 verification succeeds. Rerun a failed install to resume an interrupted transfer. Existing final files are also checked before being reused. Missing authoritative metadata causes a failure rather than accepting an unverified model.
- Third-party Python dependencies are not fully locked. A future incompatible dependency release can still make resolution fail; constraints prevent silently replacing the required Torch stack.

### Dependency and download safeguards

The installer requests exact `+cu124` Torch wheels and captures the installed
NVIDIA and Triton versions from that wheel environment into
`wan-cloud-constraints.txt`. The capture validates installed package requirements;
it does not copy CUDA 12.1 versions from the default PyPI Torch metadata.
ComfyUI and custom-node dependency installations inherit these constraints.
The configured CuPy backend uses `cupy-cuda12x==13.3.0` (Python 3.11 wheel,
CUDA 12.x, NumPy `>=1.22,<2.3`), then adds its exact installed version to the
snapshot. Conflicting CuPy distributions and changes to the protected package
set fail verification. No CUDA driver or system toolkit version is changed.
Other third-party dependencies remain unlocked and can still cause a resolver
or runtime failure; the installer must stop rather than loosen constraints.

Shared model metadata verification follows redirects using HEAD requests only,
requires final HTTP 200, and compares final Content-Length with authoritative
Hugging Face SHA-256/size metadata. Signed artifact URLs are not logged.
Custom nodes and basic compatibility verification now precede the large Wan
model downloads. RIFE is still downloaded by the node installer after its
dependency checks. System prerequisites now include tmux; persistent session
and log operation is documented in `AGENTS.md`.

## Local regression checks

These checks need Python 3, Bash, curl, and wget, but no GPU or model downloads:

```bash
python3 -m unittest discover -s tests -v
for script in *.sh install/*.sh lib/*.sh; do bash -n "$script" || exit; done
```

The tests exercise interrupted/resumed downloads, checksum failures, existing corrupt files, bootstrap verification modes, and startup failure handling using temporary fixtures and a local HTTP server. Full installation and generation must additionally be tested on the selected RunPod template and GPU.
