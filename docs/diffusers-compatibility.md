# WanVideoWrapper import compatibility evidence

## Scope

This fix preserves Torch **2.4.1+cu124**, torchvision **0.19.1+cu124**,
torchaudio **2.4.1+cu124**, and the installed NVIDIA/Triton/CuPy snapshot.
No GPU kernels, ComfyUI startup, model loading, or generation were tested.

The exact traceback from the affected pod was not supplied. The smoke test
recognizes `torch.accelerator` errors and now exercises all explicit diffusers
imports in the pinned wrapper, rather than just importing the top-level package.
This demonstrates compatibility under the original missing-API condition; it
does not establish which version or transitive import caused the pod's failure.

## Source and requirement audit

Audited [WanVideoWrapper e926f7a069e3efc25bdcc78e1bf65c39ac1a2cd4](https://github.com/kijai/ComfyUI-WanVideoWrapper/tree/e926f7a069e3efc25bdcc78e1bf65c39ac1a2cd4).
Its root requirements specify `diffusers>=0.33.0`, `peft>=0.17.0`, and
`accelerate>=1.2.1`. Easy-Use a1b402b requires diffusers without a version bound.
The pinned ComfyUI, KJNodes, Frame Interpolation installation requirements, and
Custom Scripts declare no newer diffusers minimum. Optional wrapper subprojects
not installed by the toolkit are outside the resolution scope.

`tools/wan_diffusers_imports.json` records all explicit diffusers `from` imports
found by AST analysis across the pinned wrapper Python source. These include
loader/PEFT mixins, Wan transformer classes, attention, scheduler classes and
utilities. The real smoke test forces lazy attributes to resolve. It does not
execute the complete wrapper, which also requires ComfyUI and other modules.

The [diffusers 0.33.1 wheel](https://pypi.org/project/diffusers/0.33.1/) has SHA-256
`027469e74f289338eb24127409f8d60d840b1b7ce4b27ffcd3134fd3b8431567`.
Source inspection found all manifest symbols and zero `torch.accelerator`
references. References in newer diffusers releases include guarded uses, so
their presence alone is not evidence of a broken import.

## Clean-environment results

An isolated CPython **3.11.17** venv was provisioned under `/tmp`, without system
site packages. Exact cu124 Torch wheels and dependencies were installed from
the official CUDA 12.4 index. No working ComfyUI installation was altered.

The first experiment installed diffusers 0.33.1 alongside unconstrained current
PEFT/Transformers/Accelerate dependencies. Transformers **5.20.2** disabled
model support because it requires Torch >=2.6, then the diffusers PEFT lazy import
failed with `NameError: name 'nn' is not defined`. Thus a diffusers-only pin is
not a reproducible repair for this toolkit.

The following set passed every import in the manifest with
`torch.__version__ == '2.4.1+cu124'` and **no `torch.accelerator` attribute**:

| Package | Tested pin | Relevant declared requirement |
| --- | --- | --- |
| diffusers | 0.33.1 | huggingface-hub >=0.27.0 |
| transformers | 4.51.3 | Hub >=0.30.0,<1.0; tokenizers >=0.21,<0.22 |
| peft | 0.17.0 | Torch >=1.13; Accelerate >=0.21; Hub >=0.25 |
| accelerate | 1.6.0 | Torch >=2.0; Hub >=0.21 |
| huggingface-hub | 0.36.2 | Satisfies the above intersection |
| tokenizers | 0.21.4 | Hub >=0.16.4,<1.0 |

All **16** original protected Torch/NVIDIA/Triton versions remained identical
before and after the experiment. CuPy 13.3.0 was also installed and its declared
requirements validated; no CuPy GPU operation was run. The isolated environment
passed `uv pip check` across 63 installed packages.

The complete root ComfyUI, WanVideoWrapper, KJNodes, Easy-Use, Frame Interpolation
`requirements-no-cupy.txt`, SageAttention 1.0.6, and CuPy 13.3.0 dependency set
resolved under these pins and the unchanged protected CUDA versions. Both PyPI
and the official cu124 index were used; PyPI alone lacks `+cu124` builds. This
was dependency resolution, not installation or import testing of every node.
No requirement for newer diffusers was found in that resolved set. Additional
packages in a user's pod can still conflict: the repair checks their active
declared diffusers requirements before making changes and runs `pip check`
afterward. Other Python dependencies remain outside this six-package lock.

## Reproduce without GPU operations

Use an isolated Python 3.11 venv and the official cu124 index to install the
exact existing Torch/vision/audio wheels. Install packaging, then capture that
venv's protected snapshot with `tools/protect_stack.py capture`. Install
`constraints/wan-python.txt`, SciPy, and einops with that snapshot passed as a
pip constraint. Do not substitute CPU wheels or mock `torch.accelerator` for the
real import regression. An actual cu124 wheel can be imported on a CPU host.

After preparing the isolated venv, run from the toolkit root:

```bash
WAN_IMPORT_TEST_PYTHON=/path/to/isolated/python3.11 \
  python3 -B -m unittest discover -s tests -v
```

The integration test disables GPU visibility, Hub downloads, and user site
packages, asserts Python 3.11 and the exact Torch version, asserts the absence
of `torch.accelerator`, and imports every manifest symbol. It never constructs
a model. Without the environment variable, this integration test is explicitly
skipped; the ordinary offline tests still run.

Set `WAN_WRAPPER_SOURCE` to a separately verified checkout of the full pinned
wrapper revision to enable the AST-to-manifest regression as well. Network
access is not performed by either regression. Installation must be authorized
separately; these tests never run bootstrap or download model files.
