# WAN Cloud Toolkit

Installer and launcher for a pinned ComfyUI/Wan video workflow on a **RunPod NVIDIA GPU pod**. These scripts run inside the rented pod, with persistent storage mounted at `/workspace`.

## A100 stabilization baseline

The first successful **4-second video on an NVIDIA A100 80GB** was reported by
the operator. This repository now targets ComfyUI **v0.3.46**, commit
`5d4cc3ba1b412b9acacd37fd23d59e0e1654f83c`, alongside the existing Python 3.11,
Torch 2.4.1+cu124, protected NVIDIA/Triton/CuPy stack, pinned custom nodes, and
SageAttention configuration. Do not replace these with latest releases.

The [v0.3.46 latent-format source](https://github.com/Comfy-Org/ComfyUI/blob/5d4cc3ba1b412b9acacd37fd23d59e0e1654f83c/comfy/latent_formats.py)
defines `Wan22`, which the pinned wrapper imports. The former v0.3.45 pin did
not define it. Both installation and verification now require the exact v0.3.46
commit; verification also imports `Wan22` from the installed checkout.

The default workflow disconnects `compile_args` from **both HIGH and LOW Wan
model loaders** and removes the unused `WanVideoTorchCompileSettings` node.
Apart from the duration update below, other links, dimensions, prompts, samplers, model names, LoRA
strengths, block swap, and attention settings are unchanged. This disables only
the wrapper's optional compilation path, not PyTorch or other components globally.
The A100 is compute capability 8.0; the pinned wrapper warns that FP8 E4M3
compilation below 8.9 may be unsupported. That is a **plausible explanation** for
the observed Inductor/Triton failure, not a proven diagnosis of the kernel error.
No model weights, dtypes, or CUDA dependencies were changed to work around it.

The current default uses **113 source frames** on `WanVideoImageToVideoEncode`
(node 156), replacing 65. RIFE remains **2×** and CreateVideo remains **32 FPS**:
the expected 225 interpolated frames yield approximately **7.03 seconds**.
Both model-loader compile inputs remain disconnected. This longer setting has
not yet been validated on a GPU and will require more generation time and may
use more memory than the previously reported 4-second run.

`python3.11-dev` is required even with optional compilation disabled: Python
extension helpers used by Torch/Triton or custom nodes can still need `Python.h`
and `pyconfig.h`. The apt installer supplies it, including when Python 3.11
already exists. Preflight checks the **active interpreter's sysconfig include
paths**, both before setup and from the ComfyUI venv. For a custom `/usr/local`
Python, Ubuntu's headers may not match; supply matching interpreter headers
instead of replacing the venv or changing Torch. These presence checks do not
prove that the compiler/toolchain works on the next template.

The successful pod's full environment and final workflow were not exported, so
this is a conservative reconstruction from the reported fixes. **One final GPU
validation is still required next session**; no new GPU generation was run here.

## Preserve and restore the existing network volume

These are instructions for a future, separately authorized session. No pod or
storage action is performed by the toolkit or local tests.

1. Before ending a paid session, stop submitting jobs, wait for outputs to finish,
   and preserve outputs, logs, workflow, and dependency snapshot on the actual
   network volume under `/workspace`. Verify the volume ID and mount, not just
   the presence of a directory named `/workspace`. Record the template, volume
   data center, GPU, and revision. Close ComfyUI cleanly and flush writes.
2. In the RunPod console, the operator may terminate **only the pod**, retaining
   the existing 100GB **network volume**. Never delete the network volume or
   request storage cleanup. A pod's local volume disk is different and is lost
   on termination; data outside the network mount also cannot be assumed safe.
   Network-volume storage billing continues independently of compute.
3. For the next authorized rental, select that same existing volume in its data
   center at pod creation and verify that it is mounted at `/workspace` before
   running installers. Do not initialize/format the mount or create another copy
   of the models. RunPod documents network volumes as independent of pod lifetime
   and attachable at deployment: [network-volume documentation](https://docs.runpod.io/storage/network-volumes).
4. Check `findmnt -T /workspace`, `df -h /workspace`, and `df -i /workspace`, then
   inspect `/workspace/ComfyUI`, model files, outputs, Git status, and the saved
   dependency snapshot. Keep one writer/installer per installation. The 100GB
   capacity is finite; retained corrupt downloads and outputs also consume space.
5. New pods may need OS packages and Python headers again because the container
   layer was ephemeral. After authorization, run `install/apt.sh` and
   `install/python.sh` if needed. Check that the existing venv interpreter still
   works with the new template; do not delete it or reinstall ComfyUI as a shortcut.
6. If the installation already matches v0.3.46 and the protected pins, use
   `install/verify.sh --basic`, then full `install/verify.sh`; skip bootstrap and
   downloads when unnecessary. If the old ComfyUI commit remains, review tracked
   edits and authorize the targeted `install/comfyui.sh` revision update. It
   reuses the existing checkout/venv and does not download workflow models.
   Preserve and review local changes rather than resetting or cleaning them.
7. A rerun of default bootstrap also reuses verified files; `--with-models` is
   only needed for missing or invalid assets. The download helper hashes existing
   files against authoritative metadata and resumes `.part` transfers. This
   requires metadata access and disk reads but does not redownload valid models.
   Models, URLs, checkpoint paths, and checksum enforcement are unchanged.
8. Load the updated repository workflow, not a stale browser-saved graph. Confirm
   both compile inputs are disconnected. Start `./start.sh --full` in tmux,
   inspect logs and registered nodes, then use the current pod's SSH details
   with the local connection helper. Ports remain 8888 for ComfyUI and 7777 for
   code-server. Generate only after the separate preflight/authorization step.

### Cleanup safety

No script formats or recursively removes `/workspace`, model folders, outputs,
or an existing venv. Installers now refuse tracked Git edits before checkout;
untracked user files remain in place, and Git refuses conflicting untracked
overwrites. There is no forced reset/clean or automatic deletion of user data.
Invalid/duplicate model transfers are moved to unique
`.wan-download-quarantine.*` directories beside the download, rather than
deleted. They are never accepted as valid models. Their manual cleanup requires
explicit operator review/approval and is not part of bootstrap or resume.
The only recursive shell cleanup removes the newly created temporary Python
venv probe directory owned by that invocation, not the installed environment.

### Minimum GPU validation next session

- Verify A100 identity, compute capability 8.0, driver, free VRAM/disk, mount,
  Python headers, exact ComfyUI/custom-node revisions, protected snapshot, pip
  consistency, and full model checks. Save actual versions and logs.
- Require successful `Wan22`/diffusers imports, startup without custom-node
  import failures, API registration of every workflow node, and browser readiness
  through the existing SSH tunnel.
- Run one authorized I2V job with the unchanged saved parameters and both compile
  inputs disconnected. Monitor GPU memory/utilization and generation logs; check
  the saved video for valid decoding, duration, frame count, and visual output.
  If it fails, preserve the traceback and workflow before proposing any further
  change. Export the successful workflow and environment snapshot to the volume.
- Local graph, shell, header-fixture, safety, download-fixture, and dependency
  import tests do **not** establish actual GPU generation or compiler compatibility.

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

The default ComfyUI directory is `/workspace/ComfyUI`. Set **exported** `COMFY_DIR` to use another directory. `COMFY_PORT` defaults to `8888`. Port **7777 is reserved for RunPod code-server** and is rejected by both launch and tunnel scripts. SSH tunneling needs no RunPod HTTP proxy change. If another service uses the server port, inspect it before choosing an explicitly approved alternative:

```bash
export COMFY_DIR=/workspace/ComfyUI
export COMFY_PORT=8888
./start.sh
```

### Connect from Linux Mint

Install/use Mint's `openssh-client`, `python3`, and `xdg-utils`. Copy the **current
pod's** SSH hostname, SSH port, username, and identity-file path from its connection
details. First verify the host fingerprint through a trusted channel and enroll
that host key with an ordinary SSH connection. The helper requires a known host
key and noninteractive key authentication; unlock an encrypted key with your SSH
agent first. Do not copy the private key to the pod.

After starting ComfyUI in a named tmux session on the pod, run this in the local
toolkit checkout, substituting the four current connection values:

```bash
./connect-comfyui.sh CURRENT_SSH_HOST CURRENT_SSH_PORT SSH_USER /path/to/identity
```

The helper uses `ssh -4 -N -T`, `ExitOnForwardFailure=yes`, and an explicit
`127.0.0.1:8888:127.0.0.1:8888` forward. It ignores SSH config forwarding rules
and retains strict host-key checking. It checks `/system_stats` and `/object_info`
through the tunnel, including every node type in the supplied workflow, before
running `xdg-open http://127.0.0.1:8888/`. Leave its terminal open; Ctrl-C closes
only its owned SSH process. It never opens or changes code-server.

If local port 8888 is occupied, the helper refuses to start and does not kill or
reuse the listener. Choose an explicit free local port, preserving server 8888:

```bash
./connect-comfyui.sh CURRENT_SSH_HOST CURRENT_SSH_PORT SSH_USER /path/to/identity --local-port 8889
```

Use `--remote-port` only when an approved server port differs from 8888.
`--timeout 60` controls the readiness deadline (maximum 600 seconds). On failure,
check the reported SSH log in `${XDG_STATE_HOME:-~/.local/state}/wan-cloud-toolkit`,
current SSH details, host-key enrollment, key-agent state, and remote startup log.
Private keys are referenced by path and are never read or logged by the helper.
SSH failure, timeout, missing nodes, or an occupied port prevents browser launch.
HTTP checks bypass proxy environment variables and stay on IPv4 loopback.

### Server readiness and import failures

`start.sh` refuses an occupied port or a detected existing ComfyUI process for
the same installation. It never kills an unrelated service. An import-only
diffusers smoke check runs before the existing environment verification. After
verification the launcher supervises its own ComfyUI process, streams output,
and retains a private startup log plus an exit/readiness status file under
`/workspace/wan-cloud-logs`. Keep running it inside tmux. Set `COMFY_LOG_DIR` to
another confirmed persistent location when necessary.

Startup succeeds only when the HTTP API responds and **all workflow node types**
are registered. `IMPORT FAILED`, custom-node import errors, and the specific
`module 'torch' has no attribute 'accelerator'` failure cause an explicit error.
An unhealthy process started by this launcher is terminated; existing processes
are left alone. `COMFY_START_TIMEOUT` defaults to 120 seconds and can be set up
to 600. A log line saying the server is listening alone is insufficient.

### Reproducible WanVideoWrapper dependency repair

`constraints/wan-python.txt` now pins the import-tested Python dependency set:
**diffusers 0.33.1, transformers 4.51.3, peft 0.17.0, accelerate 1.6.0,
huggingface-hub 0.36.2, and tokenizers 0.21.4**. New installations inherit these
constraints before ComfyUI/node requirements are resolved. The original
installed-wheel-derived Torch/NVIDIA/Triton/CuPy snapshot remains separate and
unchanged. Do not loosen it to satisfy a resolver error.

For an existing authorized installation, run `./install/compat.sh` in tmux with
persistent logging. This targeted repair requires the existing venv and a valid
protected snapshot. It checks installed packages for conflicting diffusers
requirements, combines the Python pins with the protected constraints, performs
a pip dry run, installs only the pinned Python compatibility set, and runs
protected-stack, pip consistency, and real diffusers import checks. It does not
check out Git revisions, download model files, or exercise CUDA. Stop on any
error; do not uninstall a conflicting package or upgrade Torch without approval.

The source audit and Python 3.11 test cover every explicit diffusers import in
pinned WanVideoWrapper source, including lazy loaders and Wan transformer classes.
`diffusers==0.33.1` alone was insufficient: an unconstrained install selected
Transformers 5.20.2, which requires Torch >=2.6 for model support. The tested
compatibility pins avoid that failure while keeping Torch 2.4.1+cu124.
See [dependency evidence and isolated regression procedure](docs/diffusers-compatibility.md).

These are CPU-side import and dependency checks, **not GPU compatibility proof**.
After repair, supervised startup must still load the actual wrapper and register
all workflow nodes before any separately authorized generation.

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
