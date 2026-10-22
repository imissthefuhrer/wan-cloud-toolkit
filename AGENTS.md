# Remote Wan 2.2 ComfyUI operations

## Scope and authorization

- This repository installs a pinned Wan 2.2 Remix I2V ComfyUI stack on an existing RunPod NVIDIA GPU pod. Read `README.md` and the relevant scripts before acting.
- Do not launch, start, stop, restart, terminate, resize, or otherwise modify RunPod instances or their infrastructure configuration. Report infrastructure blockers to the user.
- Do not execute `bootstrap.sh` yet. Preparation of this file does not authorize installation, model downloads, service startup, or generation. Wait for a subsequent instruction authorizing the operation.
- Do not change pinned dependencies, ComfyUI/custom-node revisions, model names or sources, or workflow settings without explicit approval. This includes runtime substitutions, dependency upgrades, backend changes, and edits to `workflows/Wan22-I2V-Remix.json`. Propose the exact change and reason first.
- Preserve user files and existing installations. Inspect remote Git status before installation or repair; do not overwrite local changes or delete models, outputs, or environments as a troubleshooting shortcut.

## Connection and secrets

- Once the user supplies connection details, execute remote commands over SSH using the supplied host, user, port, and local identity file. Do not guess connection details or provision infrastructure.
- Keep SSH host-key verification enabled. Resolve an unexpected host-key change with the user before reconnecting.
- Never display, copy into logs, commit, or transmit SSH private-key contents or authentication tokens. Reference the local key by path only; do not upload it to the pod.
- Do not dump environment variables, credential files, or shell history. Avoid shell tracing (`set -x`) and credentials in command arguments. Review logs for secrets and redact them before sharing.
- An SSH disconnect does not prove a remote task stopped. Reconnect and inspect tmux, logs, processes, and recorded status before retrying.

## Repository map and protected stack

- `bootstrap.sh`: system packages, Python, ComfyUI, optional Wan models, custom nodes/RIFE, then verification. Default bootstrap still downloads dependencies and the RIFE checkpoint; `--with-models` also downloads the large workflow assets.
- `install/comfyui.sh`: ComfyUI 0.3.45 at the pinned commit, Python 3.11 venv, Torch 2.4.1 / torchvision 0.19.1 / torchaudio 2.4.1 with CUDA 12.4 wheels, and `wan-cloud-constraints.txt`.
- `install/nodes.sh`: pinned custom nodes, SageAttention 1.0.6, configured interpolation backend, and RIFE 4.7. Preserve the Torch constraints for any approved dependency repair.
- `install/models.sh` and `lib/common.sh`: exact model filenames and downloads verified against Hugging Face LFS SHA-256 and size metadata. Preserve `.part` files for resumable downloads; do not bypass integrity checks.
- `install/verify.sh --basic`: installed stack checks without requiring workflow models. `install/verify.sh` additionally checks model presence; it does not validate every model checksum or perform generation.
- `start.sh`: basic verification followed by ComfyUI startup. `start.sh --full` requires workflow model presence first. Default target is `/workspace/ComfyUI`, default port is `8888`; export `COMFY_DIR` and `COMFY_PORT` explicitly when authorized values differ. Do not assume `config.env` is automatically sourced.
- RIFE lives under the interpolation node's configured `ckpts_path`, in `rife/rife47.pth` (normally `ckpts/rife/rife47.pth`), not `models/rife47.pth`.

## Preflight before costly work

Before any authorized installation, large download, service startup, or GPU generation:

1. Confirm the SSH destination, remote toolkit checkout, operation scope, intended workflow, and persistent storage paths. Inspect `git status --short` and the relevant scripts.
2. Inspect OS, privileges, `/workspace` mount (`findmnt -T /workspace`), free disk (`df -h /workspace`), and inodes (`df -i /workspace`). Budget from actual model sizes plus dependencies, temporary downloads, and outputs; stop if capacity or persistence is uncertain.
3. Query `nvidia-smi` for GPU model, driver, total/free VRAM, utilization, and existing processes. Confirm compatibility with the pinned CUDA 12.4/Torch stack; the README warns that this stack predates Blackwell. Do not interrupt other workloads or substitute dependencies to force compatibility.
4. Check required commands, including Bash, SSH access, tmux, Git, curl/wget, and Python/venv where already installed. For a fresh install, missing installer-provided tools are prerequisites to resolve within the authorized scope, not a reason to run a nonexistent venv.
5. Check HTTPS access to the package/model hosts used by the scripts without printing credentials or signed redirect URLs. Stop on authentication, network, or metadata failures.
6. Inspect existing tmux sessions, installation processes, ComfyUI processes, and listening ports (`tmux ls`, `ps`, `ss -ltnp`). A missing tmux server can be expected; distinguish that from an unexpected command failure. Do not start duplicate jobs or change RunPod port configuration.
7. For an existing installation, run `./install/verify.sh --basic`; before workflow execution, run full `./install/verify.sh`. Record outcomes. These checks inspect CUDA but do not generate video. On a fresh installation, record checks that cannot yet run and require them after installation.

Do not enqueue generation until preflight passes, model integrity has been established by the download verifier, required nodes load, and the user has authorized the GPU operation.

## Persistent execution and exit status

- Run long installations/downloads and ComfyUI in named tmux sessions on the remote pod, with timestamped logs on confirmed persistent storage (for example `/workspace/wan-cloud-logs`). Restrict log permissions with `umask 077`.
- Use a separate session and log for installation, verification, and startup. Keep a status file beside each log. Do not infer completion from tmux creation, a detached session, or the last visible success message.
- Use `set -Eeuo pipefail` in remote task wrappers. Check every command and SSH exit status; stop dependent work on any unexpected nonzero result. Never hide failures with `|| true`.
- If output is piped through `tee`, preserve both task and logging failures. The following is a wrapper pattern to prepare and run **only after authorization**, inside tmux from the remote toolkit checkout. Replace the command with the single authorized operation; the example performs basic verification, not installation:

```bash
set -Eeuo pipefail
umask 077
mkdir -p /workspace/wan-cloud-logs
run_dir=$(mktemp -d /workspace/wan-cloud-logs/verify-XXXXXXXX)
printf 'Log directory: %s\n' "$run_dir"
set +e
./install/verify.sh --basic 2>&1 | tee "$run_dir/output.log"
codes=("${PIPESTATUS[@]}")
set -e
printf 'command=%s tee=%s\n' "${codes[0]}" "${codes[1]}" > "$run_dir/status"
if (( codes[0] != 0 )); then exit "${codes[0]}"; fi
if (( codes[1] != 0 )); then exit "${codes[1]}"; fi
```

- Record the tmux session name and log directory. Attach using `tmux attach -t SESSION`; detach with Ctrl-b then d. If no status file exists, treat completion as unknown and inspect the process and logs.
- After failure, preserve evidence, identify the failed step and exit code, and diagnose before any authorized retry. Do not continue to startup or generation after failed verification.

## Monitoring and troubleshooting

- While work runs, inspect logs regularly with `tail`, check processes and disk usage, and sample `nvidia-smi` for utilization, VRAM, temperature, and competing processes. Retain timestamped monitoring output in persistent logs. Keep monitoring under observation and stop dependent operations on errors.
- Track bootstrap step numbers, download progress, checksum results, dependency resolver output, and verification results. Slow downloads or low GPU usage during package installation alone do not imply failure.
- Download failure: check free space, access permissions, connectivity, and authoritative metadata. Once the cause is resolved and retry is authorized, rerun the relevant installer to resume and validate; never rename an unchecked `.part` file into a final model.
- Dependency/import failure: inspect the first relevant traceback, venv Python version, `pip check`, pinned revisions, and Torch/CUDA versions. Use the ComfyUI venv, not global pip. Seek approval for any pin change.
- CUDA/CuPy failure: inspect driver visibility, Torch CUDA availability, and CUDA runtime/compiler libraries needed by the configured interpolation backend. Report hardware/template blockers; do not change backend or instance configuration.
- Model/node failure: compare paths and names against `install/models.sh`, `install/verify.sh`, and the saved workflow; check the configured RIFE checkpoint path and custom-node import logs. Do not substitute similarly named assets or edit workflow settings.
- Startup failure: retain the complete startup log and process exit status. Inspect verification output, tracebacks, custom-node import failures, binding errors, and port conflicts. Do not kill an unrelated process or silently choose another port.
- After authorized startup, confirm the ComfyUI process stays alive, expected nodes load, the intended port listens, and an HTTP request succeeds (for example `curl --fail --max-time 10 "http://127.0.0.1:${COMFY_PORT:-8888}/system_stats"`). Check the user-provided external URL separately if available; do not modify RunPod networking to make it work. HTTP readiness does not prove generation works.
- Before any authorized generation, repeat GPU/free-space checks and full verification. Do not alter resolution, frame count, sampling, model selection, or other workflow settings to work around out-of-memory errors without approval.

## Reporting and local validation

- Report changed files, remote commands performed, exit codes, verification results, session/log locations, and unresolved blockers. Distinguish installation success, model presence/integrity, HTTP readiness, and actual generation success.
- For documentation-only changes, review the diff; do not run bootstrap, download models, or use a GPU to validate prose.
- When authorized code changes warrant regression checks, use the README's local unit tests and Bash syntax checks. Those do not replace remote verification on the selected template/GPU.
