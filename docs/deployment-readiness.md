# Deployment readiness review of cf6e748

Status: ready for a **CPU image build**, conditional on that build passing.
Not yet certified for the retained venv or a real Pod. No image build, push,
publication, remote access, dependency install or cloud action was performed in
this review. Fixes are local repository changes to be included in the reviewed
build revision; do not build the uncorrected cf6e748 revision for deployment.

## Findings and fixes

- **Python path matches.** The operator confirms the old venv used
  `/usr/bin/python3.11`; the image installs that same path with matching headers
  and venv support. It preserves `/workspace/ComfyUI/venv` and its site-packages.
  CPython 3.11, x86_64 and matching paths are necessary, but the previous pod's
  OS/glibc and extension-library requirements are not available locally. Python
  documents venvs as generally [non-portable](https://docs.python.org/3.11/library/venv.html).
  Actual venv execution/full checks on the new image are still mandatory once.
- **No protected dependency replacement.** CUDA 12.4.1 devel matches the cu124
  family in the [PyTorch 2.4.1 table](https://docs.pytorch.org/get-started/previous-versions/).
  No Torch, NVIDIA wheel, Triton, SageAttention, CuPy or node is installed by the
  image/startup. The retained venv and protected snapshot remain authoritative.
  The development image supplies the compiler/NVRTC used by the existing backend.
  Host drivers come from RunPod, not from this Dockerfile. CUDA minor compatibility
  has [limitations for PTX/new features](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html):
  do not treat a minimum driver number alone as proof of Triton/SageAttention
  compatibility. Full verification and an authorized generation must test that.
- **Verified invalidation gap fixed.** The original record did not identify the
  image system-package set. A successful check on one system image could be reused
  after library changes when Python itself stayed identical. The build now captures
  the OS package manifest; quick checks fingerprint it, OS release and glibc.
  Launcher script hashes are included too. Schema changes reject old records.
- **Verified node-inventory gap fixed.** An additional custom-node directory was
  not covered by the original five-node revision hashes. Quick checks now compare
  the top-level inventory as well. Existing untracked file contents are still not
  hashed; manual changes require full verification as documented.
- **Stronger CPU build checks added.** The build and CI runtime probe now verify
  `/usr/bin/python3.11`, headers, standard Python extension imports, interpreter
  shared-library resolution, C++/OpenMP/NVRTC loading and CUDA compiler presence.
  Temporary venv/pip checks remain. These do not import/test the unavailable retained
  Torch environment or execute CUDA kernels.
- **No missing-volume launch in the quick path.** Autostart checks an exact
  non-ephemeral `/workspace` mount and enrolled marker before creating persistent
  logs. `start.sh --quick` repeats that check before launching the server, then
  requires a matching record, Python/headers, GPU-driver access and required model
  file metadata. The old process/port conflict check and supervised API/node/import
  checks still run. Failures stop dependent startup; no installs/downloads occur.
  A directory named `/workspace` alone is insufficient. The operator must verify
  the actual RunPod volume identity before enrolling its marker; this is not a
  cryptographic attestation of a cloud volume.

## Warning investigation

The retained `/tmp/wan-tests-final.log` from the implementation has performance
warnings emitted by deliberate failure fixtures: failed socketpair setup,
repeated mocked monitor exit, synthetic event-channel failure and simulated low
disk space. These verify fallback console logging and recovery behavior; they
are not evidence of a failed live ComfyUI service. Output truncation warnings are
from the tool display. A separate Codex UI warning cannot be identified without
its exact text. No real Pod logs were available or read.

The old sandbox test failures (`Operation not permitted` opening local sockets)
are also local test-runner restrictions, not CUDA/image failures. The full suite
must be run with loopback/socket fixtures permitted.

## Validation results

The full offline suite passed: **107 tests, 2 skipped**, exit 0. The two existing
optional checks need `WAN_IMPORT_TEST_PYTHON` and `WAN_WRAPPER_SOURCE`; they were
not supplied. Bash syntax checks and `git diff --check` passed. New tests cover
image probe success/failure, node inventory invalidation, system manifest identity,
and stopping startup after a failed quick check. These use fixtures/mocks, not
an executed Docker image. The CPU image probe itself still needs its first CI run.

## Exact build and publication procedure (future authorized actions)

1. Review these local fixes and commit them. Obtain separate approval to push
   that reviewed revision to GitHub. The workflow must be present on the default
   branch for its manual Actions button to appear. Nothing has been pushed here.
2. In GitHub **Actions → Build WAN Pod image (no publish) → Run workflow**, choose
   the branch containing the reviewed commit. The runner is CPU-only Ubuntu 22.04.
   It runs tests, builds linux/amd64, runs the CPU container checks, then saves an
   archive. No registry token is needed and there is no push step.
3. Require a green job. Record the **full commit SHA from that run**, not an old
   local HEAD. Download its `wan-cloud-toolkit-FULL_SHA` artifact, unzip it into an
   empty local directory and locate `wan-cloud-toolkit.tar.gz`. The CI image tag
   is `wan-cloud-toolkit:git-FULL_SHA`. GitHub documents standard runners with
   [14 GB SSD](https://docs.github.com/en/actions/reference/runners/github-hosted-runners);
   the CUDA development image plus archive need significant space. Inspect the
   job's `df -h` output. If capacity is insufficient, use a larger **CPU** runner
   or CPU workstation; do not rent a GPU or blindly remove runner/user files.
   GitHub Actions/retained artifacts may incur account charges, independently of
   RunPod GPU rental.
4. After separate publication approval, create/select the private GHCR package
   namespace. Use a publisher account authorized for the namespace and a classic
   PAT with `write:packages`; authorize organization SSO if required. Use a local
   Docker credential helper and interactive login so tokens never appear in a
   command or build log. See [GHCR authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
5. From the artifact directory, substitute the full reviewed SHA and lowercase
   namespace below. These commands publish; **do not execute them before approval**:

   ```bash
   set -Eeuo pipefail
   BUILD_SHA='FULL_SHA_FROM_SUCCESSFUL_ACTIONS_RUN'
   GHCR_OWNER='your-lowercase-github-user-or-org'
   GHCR_LOGIN='your-github-login'
   gunzip -c wan-cloud-toolkit.tar.gz | docker load
   docker image inspect "wan-cloud-toolkit:git-$BUILD_SHA" --format '{{.Id}}'
   docker login ghcr.io --username "$GHCR_LOGIN"
   image_ref="ghcr.io/$GHCR_OWNER/wan-cloud-toolkit:git-$BUILD_SHA"
   docker tag "wan-cloud-toolkit:git-$BUILD_SHA" "$image_ref"
   docker push "$image_ref"
   docker image inspect "$image_ref" --format '{{json .RepoDigests}}'
   ```

   Paste the PAT only at Docker's password prompt. Save the registry digest
   printed by push (or the matching RepoDigest); **do not** use the local image
   `.Id` as the registry manifest digest. Keep the package private, verify access,
   and never overwrite a released `git-FULL_SHA` tag. Deploy by registry digest.
6. In RunPod Settings' container registry authentication section, save a separate
   GHCR credential with `read:packages`, using an account with package access.
   Do not paste the publisher token into Pod environment variables. Create a
   **private Pod template** using the settings below. Creating a template is a
   separate future authorized cloud configuration action; this review does none.

| Template field | Exact setting |
| --- | --- |
| Image | `ghcr.io/OWNER/wan-cloud-toolkit@sha256:REGISTRY_DIGEST` |
| Registry credential | The saved read-only GHCR credential |
| Start command | Empty; retain image entrypoint |
| TCP ports | `22` |
| HTTP ports | `8888` |
| Volume mount path | `/workspace` |
| SSH | Enabled, with your registered public key |
| Visibility | Private |

Set these environment variables:

```text
COMFY_DIR=/workspace/ComfyUI
COMFY_PORT=8888
COMFY_LOG_DIR=/workspace/wan-cloud-logs
COMFY_START_TIMEOUT=300
COMFY_PERFORMANCE=1
WAN_AUTOSTART=0
WAN_VOLUME_ID=YOUR_EXISTING_VOLUME_MARKER
```

No marker yet? Keep autostart disabled, and enroll one **only after** the real
volume identity is confirmed in the first-deployment procedure. Save the old
working template unchanged. This NVIDIA-based image provides SSH terminal access;
it does not bundle code-server/Jupyter or the old template's browser IDE. Port
7777 stays reserved and unused. If that IDE is required, this image does not yet
replace it; do not claim the browser-terminal integration was tested.

At a later authorized Pod deployment, choose A6000/A100-compatible hardware and
select the **existing 100GB network volume in its current data center**. Do not
create a new volume. Template mount settings do not select/attach a volume.
Follow [first-deployment checks and rollback](runpod-image.md#first-deployment-separately-authorized-pod-work).
Full `verify.sh` checks Torch imports/driver visibility and SageAttention imports;
it does not execute a CuPy kernel or a SageAttention kernel. For first-image
validation, separately authorize the configured backend smoke test in the retained
venv, e.g. `venv/bin/python -c 'import cupy; assert cupy.arange(3).sum().item() == 3'`
from `/workspace/ComfyUI` when the configured backend is CuPy. Do not run the node
installer merely to obtain that test. A separately authorized generation is still
needed for SageAttention/Triton and the complete unchanged workflow. GPU-specific
JIT warmup/cache misses may still cost time on the first generation of a fresh Pod.

Once actual-venv full verification has passed on this image and the APIs/nodes
have been validated, set `WAN_AUTOSTART=1` for future deployments. Those should
need no package setup, but image pull, network-volume metadata access and real
ComfyUI imports still take time; a fixed startup-time guarantee is not established.
