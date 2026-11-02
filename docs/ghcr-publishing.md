# Direct private GHCR publishing from a CPU runner

Workflow name: **Build, test and publish WAN Pod image to GHCR**

File: `.github/workflows/publish-image.yml`.

This is separate from **Build WAN Pod image (no publish)**; that existing workflow
is unchanged. The operator reports that its CPU build/container checks passed for
`83fb678`. The new publisher rebuilds the reviewed revision and runs those checks
again; it does not download that old 4.28GB archive or create another Docker archive.
The repository Dockerfile, generation workflow, dependencies and volume are unchanged.

## Run after separate push/publication approval

1. Review and push the new local commit to the existing repository's `main` branch
   only after authorization. The manual workflow must be on the default branch to
   expose the Actions **Run workflow** button. A push does not publish anything.
2. Open [Actions → Build, test and publish WAN Pod image to GHCR](https://github.com/imissthefuhrer/wan-cloud-toolkit/actions/workflows/publish-image.yml).
   Select **Run workflow**, branch **main**, CPU runner **ubuntu-22.04**, then
   **Run workflow**. Only the named repository's `main` branch can publish.
   Starting this workflow explicitly authorizes publication of that run's commit.
3. No PAT or repository secret is required. The job uses `GITHUB_TOKEN` with only
   `contents: read` and `packages: write`. Registry login is passed via stdin;
   checkout does not persist Git credentials, and Docker auth is isolated in the
   runner's temporary directory and logged out at the end. Never enable shell tracing.
4. The job runs offline regression tests, checks package visibility/tag availability,
   builds **linux/amd64** with the existing Dockerfile, then runs the Python 3.11,
   headers, shared-library/NVRTC, temporary venv/pip, SSH/compiler and architecture
   checks inside the image. Only after these pass does it push that same local image.
5. In the successful run's **Summary**, copy the complete image reference:

   ```text
   ghcr.io/imissthefuhrer/wan-cloud-toolkit@sha256:REGISTRY_DIGEST
   ```

   The same value appears in the digest step's log and the job's `image` output;
   the `digest` output contains the `sha256:...` value. It comes from Docker's
   registry `RepoDigests` after push, **not** the local image/config ID. Use this
   exact reference in the private RunPod template later. No Pod is launched by CI.

## Privacy and commit tags

The only tag is `git-<full 40-character commit SHA>` under
`ghcr.io/imissthefuhrer/wan-cloud-toolkit`. No `latest` or rolling branch tag is
created. The workflow checks all package-version pages and refuses an existing
commit tag, including on reruns. It checks again immediately before pushing, and
serializes this repository's publisher runs. GHCR tags themselves are mutable;
these guards prevent overwrites by this workflow, not by another authorized writer.
Digest-pinned deployment is the immutable reference. A rebuild is not bit-identical
because upstream apt repositories remain unfrozen, so do not retag an old commit.

GitHub documents that [new GHCR packages default to private](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
The workflow refuses an existing public/internal package and verifies private
visibility after pushing. It never changes visibility, deletes packages, or falls
back to public publication. The API token must be able to read package metadata;
authentication/network/API failures stop the job. A preflight 404 permits a first
publication; a private package inaccessible to this repository cannot be adopted
that way, because the push will lack access. If the package was created previously
outside this repository, link it and grant this repository Actions access in
package settings before running. Do not solve permission errors with a PAT or by
making the package public. Privacy changes made concurrently by an external admin
cannot be prevented by CI; retain private settings and restrict package access.

If the push succeeds but a later verification/report step fails, a rerun will
refuse the existing tag. Inspect package visibility and its existing digest via
GitHub/Docker read-only inspection; do not delete/re-push or bypass the guard.
No automatic cleanup is performed on a partially published package.

For RunPod to pull the private image, configure a separate read-only GHCR credential
(`read:packages` classic PAT for an account with package access) in RunPod later.
The ephemeral Actions `GITHUB_TOKEN` is only for the build job and cannot be reused
as the Pod's registry credential. This workflow does not configure RunPod auth.

## Disk space and build context

The publisher uses one local Docker image; there is no `docker save`, tar/gzip
archive, artifact upload, second build, or duplicated Buildx export. It reports
free disk before/after the build and requires at least **12 GiB free on `/`**
before starting. This is a guard, not a guaranteed capacity budget; base layers,
package growth, Docker cache and writable layers may require more. The standard
[GitHub CPU runner disk allocation is limited](https://docs.github.com/en/actions/reference/runners/github-hosted-runners).
If the guard or Docker build reports insufficient space, rerun with a larger
**x64 CPU runner label** in the manual `runner` input (configured for this repo),
or use an appropriate CPU workstation. No GPU is needed. Do not select an ARM/GPU
runner. The job neither deletes runner toolchains nor prunes unrelated Docker data.
Use an ephemeral runner without sensitive local files for this credential-bearing job.

The unchanged `.dockerignore` uses an allowlist and excludes models, credentials,
logs, outputs, Git metadata and persistent venvs. The build has no `/workspace`
volume mount, no token build args, and no model downloads. Large model/venv files
remain on the existing network volume. OS/Python tools are baked outside it.

## Local versus live validation

Offline tests cover visibility/tag guards (including pagination and API failures),
disk errors, digest selection/reporting, workflow ordering/manual-only permissions,
shell parsing, and preservation of the original no-publish workflow. They do not
publish or prove live GHCR permissions. The first separately authorized workflow
run must validate those permissions, private-package API behavior and digest reporting.
Real retained-venv/GPU validation remains required under the existing
[first-deployment procedure](runpod-image.md#first-deployment-separately-authorized-pod-work).

Local validation: `python3 -m unittest discover -s tests -v` completed **118 tests,
OK, 2 skipped** (the existing optional diffusers/source-audit checks). Workflow
YAML/permissions, embedded Bash blocks, repository Bash syntax and diff whitespace
checks passed. No Docker build, push, workflow dispatch or publication was performed.
