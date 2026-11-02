# Reusable RunPod image and fast startup

This image bakes **system prerequisites**, not models or a new Python stack for
ComfyUI. The existing `/workspace/ComfyUI/venv`, nodes, models and outputs remain
on the **same existing 100GB network volume**. No bootstrap, apt, pip, download,
or environment reconstruction runs during startup. The image carries a release
of the launcher under `/opt/wan-cloud-toolkit`, outside the mount. The existing
`/workspace/wan-cloud-toolkit` checkout remains available for maintenance.

## Base and compatibility

The base is NVIDIA `nvidia/cuda:12.4.1-devel-ubuntu22.04` (linux/amd64).
The tag is published in NVIDIA's [supported image list](https://gitlab.com/nvidia/container-images/cuda/blob/master/doc/supported-tags.md).
Ubuntu 22.04 and CUDA 12.4 are supported in NVIDIA's
[12.4.1 guide](https://docs.nvidia.com/cuda/archive/12.4.1/cuda-installation-guide-linux/).
PyTorch's [version table](https://docs.pytorch.org/get-started/previous-versions/)
provides Torch 2.4.1/vision 0.19.1/audio 2.4.1 cu124 wheels. The development
variant supplies NVRTC/compiler libraries for the existing CuPy/Triton backend;
it does not install a different Python CUDA wheel stack or a host driver.
The existing protected wheel snapshot stays authoritative. SageAttention and
node revisions are untouched. Use A6000 or A100-class hardware; Blackwell is
rejected by the quick driver probe. This design/source review is **not** a tested
container/GPU compatibility claim.

Python 3.11, venv, ensurepip and matching development headers are installed from
the signed Deadsnakes PPA into `/usr`. Each image build executes a header check
and creates a temporary venv to test pip. Ubuntu/Deadsnakes package repositories
are not frozen; rebuilding a commit may produce different OS package revisions.
Retain and deploy the built image **by registry digest** for reproducible rentals.
Never overwrite a published version tag. For bit-identical rebuilds, an additional
approved apt snapshot/package lock would be needed.

A venv is not a portable archive. Before switching templates, record (without
secrets) the working pod's `/etc/os-release`, `readlink -f
/workspace/ComfyUI/venv/bin/python`, `venv/pyvenv.cfg`, `sys.base_prefix`, Python
version and active sysconfig include paths. This image expects CPython 3.11 for
x86_64 Linux with its base interpreter at `/usr/bin/python3.11`, using Ubuntu
22.04-compatible shared libraries. The quick check executes the actual venv,
requires Python 3.11, the expected venv prefix and matching active headers.
Broken symlinks, missing shared libraries, another Python version or bad headers
fail startup; no symlink is rewritten and no venv is replaced.

If the current venv uses a custom `/usr/local` Python or needs a newer glibc,
**do not switch that volume into unattended operation yet**. Keep the old
working template. Build a separately versioned image reproducing that exact
interpreter/layout and OS libraries, then run full verification there. Alternatively,
with separate explicit maintenance approval, construct a new side-by-side venv
from the protected pins and validate it before selecting it. Preserve the original
venv throughout. Do not copy `/usr/bin/python3.11` to masquerade as a custom
interpreter. A different image/Python binary requires a new full-verification record.

Unlike RunPod's PyTorch images, this NVIDIA base contains no RunPod `/start.sh`.
Our entrypoint explicitly starts key-only OpenSSH on 22, enrolls RunPod's
`PUBLIC_KEY`, and creates per-Pod host keys. SSH interactive terminal access is
available independently of ComfyUI. No private keys enter the image. This image
does **not** bundle the old template's Jupyter/code-server or browser IDE;
7777 remains reserved and is never bound or forwarded. Keep the old template if
that IDE is required until a separate approved image addition is validated.

## Build without a GPU

After review, build on a CPU workstation or manually run **Build WAN Pod image
(no publish)** in GitHub Actions. That workflow has no registry write permission,
no push step and no automatic push/PR trigger. It runs the offline tests, builds
linux/amd64, executes Python/header/venv/SSH/compiler checks inside the image,
and retains a compressed Docker archive for seven days. Allow runner disk space
for the CUDA development image and archive. This workflow has not been run as
part of the local offline tests.

```bash
docker build --platform linux/amd64 -t wan-cloud-toolkit:git-COMMIT_SHA .
docker run --rm --entrypoint bash wan-cloud-toolkit:git-COMMIT_SHA -c \
  'python3.11 tools/check_python_headers.py && python3.11 -m venv /tmp/probe && /tmp/probe/bin/python -m pip --version'
```

The context uses an allowlist: no Git metadata, credentials, models, outputs,
venvs, or SSH keys. Image builds do not run any toolkit installer. Existing
persistent dependencies are validated on the actual Pod, not by a CPU image build.

**Publishing requires separate authorization.** When authorized, authenticate to
a private registry using `docker login` interactively or a credential helper;
never put a PAT in Dockerfile, build args or commands/logs. Load the CI archive
with `gunzip -c wan-cloud-toolkit.tar.gz | docker load` if using CI. Then:

```bash
docker tag wan-cloud-toolkit:git-COMMIT_SHA REGISTRY/OWNER/wan-cloud-toolkit:git-COMMIT_SHA
docker push REGISTRY/OWNER/wan-cloud-toolkit:git-COMMIT_SHA
```

Record the returned `sha256` digest. Configure a read-only registry credential in
RunPod's registry authentication settings and select it on the private template.
Do not put registry credentials in template environment variables. Deploy
`REGISTRY/OWNER/wan-cloud-toolkit@sha256:DIGEST`, preserving the version tag for
humans. Save the old template configuration/image reference before proceeding.

## Private Pod template

Follow RunPod's [custom template instructions](https://docs.runpod.io/pods/templates/create-custom-template)
and [network-volume instructions](https://docs.runpod.io/storage/network-volumes).
No toolkit command creates/modifies templates, Pods or storage.

| Field | Value |
| --- | --- |
| Visibility | Private |
| Container image | Your authorized image's immutable registry digest |
| Container start command | Leave empty; use image ENTRYPOINT |
| TCP ports | 22 |
| HTTP ports | 8888 |
| Volume mount path | `/workspace` |
| Container disk | Allow space for CUDA image and temporary runtime caches; no model copy |
| Registry auth | Read-only credential selected in RunPod |
| SSH | Enable SSH, enroll your public key via RunPod `PUBLIC_KEY` |

Environment:

```text
COMFY_DIR=/workspace/ComfyUI
COMFY_PORT=8888
COMFY_LOG_DIR=/workspace/wan-cloud-logs
COMFY_START_TIMEOUT=300
COMFY_PERFORMANCE=1
WAN_AUTOSTART=0
WAN_VOLUME_ID=<operator-enrolled identifier for the existing volume>
```

At **deployment**, explicitly select the **existing** network volume in its data
center. Do not create another volume, use an ephemeral disk as a substitute, or
change the existing volume. Template mount paths alone do not select a volume.
Choose a compatible GPU per deployment; the template does not hard-code a GPU.
RunPod HTTP proxy exposure does not replace SSH TCP mapping, and Docker EXPOSE
does not configure either of them. The startup checks use local loopback and
cannot certify RunPod proxy settings.

## First deployment (separately authorized Pod work)

1. Preserve the old working template/digest and connection details. Follow the
   repository's remote preflight: current SSH destination, mount, actual volume
   ID, disk/inodes, GPU/driver/processes, existing Git edits, tmux and listeners.
   Use `WAN_AUTOSTART=0` for this first deployment so SSH is available without
   starting ComfyUI. Do not run bootstrap.
2. Confirm through the RunPod console that the existing network volume is attached
   at `/workspace`, then check `findmnt -T /workspace` and `df -h /workspace`.
   Only after confirming its identity, enroll a **new, nonsecret marker** once:
   `python3.11 -c 'import uuid; print(uuid.uuid4())' | (umask 077; set -C; cat > /workspace/.wan-volume-id)`.
   `set -C` refuses to overwrite an existing marker. Record its value as
   `WAN_VOLUME_ID` in this private template. The marker is an operator assertion,
   not an API proof of volume ownership; an exact non-ephemeral mount plus marker
   is required at every startup.
3. Inspect the venv compatibility described above. Export the template variables
   in your SSH terminal too (SSH does not necessarily inherit container env).
   Confirm prior model download verifier success; if provenance is uncertain,
   perform an explicitly authorized integrity validation using existing installers
   before recording the environment. Full verification checks model presence,
   **not hashes**; this new path does not invent integrity evidence.
4. In a named tmux session with the persistent private logging/status wrapper
   from `AGENTS.md`, run `/opt/wan-cloud-toolkit/install/verify.sh --record-fast`.
   This runs the existing full verification, then checks mount, GPU, Python and
   records `.wan-fast-verified.json` in ComfyUI. A failure prevents the record.
   This must be done once on the new image even if the old template worked.
5. Run `/opt/wan-cloud-toolkit/docker/autostart.sh` to start the named `wan-comfy`
   tmux session. It checks the mount before creating logs. Inspect the printed
   `fast-start-*/output.log`, status files, supervisor log and readiness journal.
   `tmux attach -t wan-comfy` shows the foreground supervisor; detach with Ctrl-b d.
   Duplicate session/process/port checks refuse another instance. A session can
   disappear on failure; inspect its persistent status, not just `tmux ls`.
6. Require valid `/system_stats` and all workflow node types in `/object_info`.
   Use the existing local `connect-comfyui.sh` with the **current** SSH host/port
   and key to perform tunnel/node checks before browser launch. Check the RunPod
   proxy URL separately if needed. No cloud port configuration is changed by code.
7. After validating the first deployment, set `WAN_AUTOSTART=1` in the private
   template for **future** rentals. Attach the same volume each time. Startup
   automatically runs the quick checks and existing supervised launcher in tmux.
   No apt, pip, bootstrap or model downloads occur. The new image does not enqueue
   generation; any GPU validation job still needs authorization.

Manual alternative: `./fast-start.sh` or `./start.sh --quick` inside tmux with the
same environment. `./install/verify.sh --quick` checks only; it does not start a
service. The launcher separately checks port/process availability before starting.

## Verification contract and maintenance

| Check | Routine quick path | Full verification / maintenance |
| --- | --- | --- |
| Storage | Exact `/workspace` mount; reject overlay/tmpfs/ramfs; match marker | Console volume identity, capacity/inodes and integrity provenance |
| Python | Execute existing 3.11 venv, prefix and active development headers | Venv provisioning/repair only when explicitly authorized |
| GPU | `nvidia-smi`, CUDA driver init/device count, reject Blackwell | Torch/CuPy operations and backend compatibility |
| Dependencies | Compare installed name/version metadata with full-check record | Existing imports, pip consistency, protected stack validation |
| Code/config | Compare pinned Git HEADs and tracked diffs for ComfyUI + five pinned nodes; hash small workflow, constraints, interpolation config, toolkit Python helpers | Inspect any added nodes, requirements or runtime config changes |
| Models | Required exact paths including configured RIFE path, nonempty regular files; compare resolved path, size and mtime | Download verifier's authoritative SHA-256/size validation |
| Port/process | Existing supervisor refuses duplicate ComfyUI/occupied port; reject 7777 | Operator checks RunPod HTTP/TCP configuration |
| Readiness | Existing API/node/import-failure checks after real startup | Authorized generation proves runtime behavior |

Quick checks do not recursively traverse models, read model bodies, import heavy
ML modules, run pip check, or execute GPU kernels. Git examines tracked source
files; installed distribution metadata is enumerated once. Model stat comparisons
can miss same-size corruption with preserved timestamps. Version metadata cannot
prove package file integrity. Untracked source changes, added custom nodes and
other ComfyUI user settings are not automatically fingerprinted. After **any**
installation, dependency, node, workflow/configuration change, or suspected disk
corruption, remove only the verification record (or leave it to fail), run the
appropriate authorized full/integrity checks and `verify.sh --record-fast` again.
Never edit a record to accept a change. The record is a performance cache, not a
security boundary or substitute for model provenance. Changing GPU alone does
not invalidate it; driver access is checked each time and startup imports still run.

Default `./start.sh` and `./start.sh --full` retain thorough verification;
`install/verify.sh` retains its original full behavior and `--basic` its original
model-optional behavior. The default readiness deadline is now **300 seconds**,
configurable with `COMFY_START_TIMEOUT` up to 600; no unlimited retries. Every ten
seconds the supervisor reports elapsed time, console idle time, phase and last
HTTP-check error, also saved in `<startup.log>.readiness.jsonl`. Console import
errors or early process exit fail startup. Missing nodes, invalid API responses,
still initializing and server-announced-but-HTTP-unresponsive phases are distinct
heuristics; they cannot prove a process is making forward progress. A timeout
stops only the newly owned process, retaining logs and exit status. Check external
RunPod port mapping separately when local readiness succeeds but proxy access fails.
Automatic performance reports remain enabled in `$COMFY_LOG_DIR/performance`.

## Rollback and validation limits

If image/venv compatibility or readiness fails, retain the logs and stop dependent
work. Do not repair dependencies automatically. Return to the saved working
RunPod template/image on the next authorized deployment, with the **same existing
network volume** and `WAN_AUTOSTART=0`; remove no models, outputs or environments.
The new image changed no generation settings or protected dependencies. The
verification record is ignored by the old thorough launcher. Use the original
maintenance/start procedure and current SSH tunnel details. Infrastructure actions
and any additional maintenance require explicit authorization.

Local tests use fixtures, mocks and loopback HTTP servers. They cannot prove the
image pulls/builds, the old venv works with its system libraries, SSH/RunPod terminal
integration, driver compatibility, API readiness on a real GPU, or video generation.
Run the CPU image-build checks first, then the first-deployment procedure on a
separately authorized real Pod. The operator reports successful seven-second runs
on A6000 48GB and A100 SXM 80GB with the existing stack; the **new image and fast
path have not yet had real-Pod validation**.

## Local validation for this implementation

`python3 -m unittest discover -s tests -v`: **102 tests, OK, 2 skipped**.
Loopback HTTP/socket fixtures needed execution outside the restrictive local
sandbox. The skipped tests require an explicitly configured Python 3.11 diffusers
test environment. Bash syntax checks passed for root, install, lib and docker
scripts; `git diff --check` passed. No Docker image build, publication, remote
command, model download, Pod deployment or GPU generation was performed.
