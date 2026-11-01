# Generation SYNTHETIC-3

**SYNTHETIC EXAMPLE — simulated measurements; no GPU generation.**

Status: success; host wall time: 180 seconds.

ComfyUI console execution seconds: not_observed.

Started (UTC): 2026-01-01T00:00:00+00:00

Effective resolution: [960, 480]; source frames (API): 113; interpolation: 2×; FPS (API): 32.

Expected duration: 7.03125 s; actual output duration: not_observed.

Input identifiers: not_observed

Sampled device VRAM peaks (MiB): {'GPU-SYNTHETIC': 32000}

| Node | Phase | Settings |
|---|---|---|
| 3 WanVideoModelLoader | HIGH | {"model": "Wan_HIGH.safetensors", "base_precision": "fp16", "block_swap_args": "unknown (connected output not observed)", "optional_torch_compile": "disabled (input disconnected)"} |
| 4 WanVideoSampler | HIGH | {"model": "unknown (connected output not observed)", "steps": 8, "start_step": 0, "end_step": 4, "scheduled_step_count": 4} |
| 9 WanVideoBlockSwap |  | {"blocks_to_swap": 20} |
| 13 WanVideoModelLoader | LOW | {"model": "Wan_LOW.safetensors", "optional_torch_compile": "disabled (input disconnected)"} |
| 14 WanVideoSampler | LOW | {"model": "unknown (connected output not observed)", "steps": 8, "start_step": 4, "end_step": 10000, "scheduled_step_count": 4} |

| Node | Phase | Stage | Approx wall seconds |
|---|---|---|---:|
| 3 | HIGH | model_loading | 5.000 |
| 4 | HIGH | sampler | 66.000 |
| 13 | LOW | model_loading | 9.000 |
| 14 | LOW | sampler | 63.000 |
| 8 | unknown | vae_decode | 18.000 |
| 6 | unknown | rife | 9.000 |
| 7 | unknown | video_creation | 5.400 |
| 15 | unknown | video_save | 3.600 |

Cached nodes: not_observed

Console evidence (approximate byte range): `{'path': '../synthetic-console.txt', 'start_byte': 216, 'end_byte': 304}`

Coverage: no gaps detected (not a guarantee of complete GPU observation)

host monotonic wall-clock between node-start events; includes transfers, async GPU work and overhead; not GPU kernel timing

Full filtered settings and runtime observations: `report.json`.

- VRAM peaks are sampled device-wide usage, not exact PyTorch allocations.
- Event duration ends at the execution result; ComfyUI console execution seconds, when observed, may also include executor cleanup.
- Model HIGH/LOW identity is in node model names and sampler model links; model work may be deferred into samplers.
- No full prompts, image data, environment or traceback payloads are stored here. See console byte range for original evidence.
- Actual output frame count/duration and dynamic values are not observed unless explicitly stated.
