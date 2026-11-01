# Automatic generation diagnostics

`./start.sh --full` automatically records generations from the ordinary ComfyUI
browser. Basic `./start.sh` enables the same recorder. No separate terminal,
history export, monitoring command, new package, or driver is required. This
feature does not enqueue jobs or change the workflow, models, dependencies,
ports, attention, offloading, block swap, or compilation settings.

Reports live in `/workspace/wan-cloud-logs/performance/`, or
`$COMFY_LOG_DIR/performance/` when that existing exported setting is overridden.
Each execution gets a unique UTC timestamp/prompt-ID directory containing:

- `report.json`: filtered API settings, observations, timings, coverage and result.
- `report.md`: readable summary with HIGH/LOW settings and stage timings.
- `samples.jsonl`: UTC and monotonic timestamps, GPU/system samples.
- `events.jsonl`: small, filtered execution journal used for crash recovery.

A session queue journal records observed queued IDs and timestamps. The normal
private `comfy-start-*.log` and status file remain in the parent log directory.
Each report points to the original console file and approximate byte offsets;
WanVideoWrapper sampling and CUDA memory output stay there without being copied
into every report. Preserve that console file alongside the reports.

Directories are mode 0700; report, journal and sample files are 0600. No prompt
text, seeds, image pixels, credentials, environment dumps, arbitrary error
payloads, full workflow, model weights or video files are saved by the recorder.
PNG/JPEG dimensions and SHA-256 are read from input files where accessible;
hashing is limited to 64 MiB. Input identifiers describe the file observed at
recording time; they cannot establish the identity of an older cached tensor.
Nested/custom input locations and unsupported image headers may be unobserved.
The existing console log may contain whatever third-party nodes print; treat it
as private as before.

## Compare saved generations offline

```bash
python3 tools/performance.py compare
python3 tools/performance.py compare /path/to/saved/performance --limit 20
```

The table includes status, host execution seconds, observed effective resolution,
source frames, connected sampler step counts, sampled device VRAM peaks, and
per-node HIGH/LOW/stage durations. Keep prompt IDs when comparing outputs.
`report.json` adds precision, model names, block swap, caching connections,
offloading and compile input state. Runtime sampling observations include their
console offsets; progress observations retain each node's latest step/max pair.

Try the **synthetic** three-run fixture without GPU access:

```bash
python3 tools/performance.py compare docs/examples/performance --limit 3
```

[Example Markdown report](examples/performance/SYNTHETIC-1/report.md) and
[JSON report](examples/performance/SYNTHETIC-1/report.json) contain simulated
values, unrelated to the historical A6000 execution times. Regenerate only these
documentation fixtures with `python3 tests/make_performance_examples.py`.

## What measurements mean

The child runner leaves ComfyUI files intact. A narrow import hook wraps
`PromptServer.send_sync` after the normal `server` import, calls the original
method, and copies allowlisted execution messages into a nonblocking local Unix
datagram socket. Browser event routing is preserved. This is needed because
[pinned ComfyUI execution events](https://github.com/Comfy-Org/ComfyUI/blob/5d4cc3ba1b412b9acacd37fd23d59e0e1654f83c/execution.py)
are often addressed to the submitting browser; an unrelated WebSocket listener
cannot rely on seeing them. The [documented message meanings](https://docs.comfy.org/development/comfyui-server/comms_messages)
include start, cached, node-start, success, error and interruption. `executed`
means UI output, rather than completion of every node, and is not used as a
universal node-end signal.

The companion process records data, tails bounded console chunks and samples
hardware. It queries loopback `/queue` every five seconds (two MiB response cap,
128 pending IDs per snapshot) and only `/history/PROMPT_ID` for a known active job missing a
terminal event. It never downloads the complete history. Queue discovery can
recover a job already running when monitoring starts, with incomplete coverage
marked. Very short queued states between snapshots may be missed. HTTP requests
ignore proxy settings and have one-second timeouts. GPU queries have two-second
timeouts and fall back when optional driver fields are unsupported.

Interpret comparisons with these limits:

- Prompt duration uses host monotonic event timestamps through the execution result.
  The separate ComfyUI console execution summary, when observed, can include
  additional executor cleanup. Terminal events are journaled immediately; the
  report waits up to two seconds for console flushing/that summary. Stage durations span
  consecutive node-start events, including host work, transfers, scheduling and
  asynchronous GPU activity. They are **approximate wall-clock**, never CUDA
  kernel times. No per-node CUDA synchronization or expensive profiling is added.
- Loader nodes may configure models and defer actual weight movement/loading to
  samplers. HIGH/LOW labels come from connected model filenames, not node order.
  Cached node IDs are retained; absent stages are unobserved/cached, not zero-cost
  model loading. Dynamic/repeated node execution may make intervals less exact.
- Submitted API inputs supersede browser widget displays. Known scalar constants
  are resolved through links with cycle protection. Unknown computations remain
  unknown. Width/height in API settings are requested values; **effective**
  resolution is populated only by recognized WanVideoWrapper runtime sampling
  output. Current pinned sampling log formats are covered by offline tests.
- The HIGH/LOW scheduled step count is `min(steps, end_step) - start_step`, bounded
  at zero when all inputs are known. Runtime console/progress values are separate
  evidence; custom schedulers can differ. No arbitrary node output is guessed.
- Frame interpolation and FPS come from API inputs; expected frame count and
  duration are estimates for the workflow's RIFE convention. Actual encoded
  output duration/frame count is explicitly unobserved; no video probing is added.
- GPU samples include all visible devices, not solely this process: utilization,
  used/total VRAM in MiB, temperature, power/limit, graphics/memory clocks,
  PCIe link generation and throttle-reason mask when supported. Optional PCIe
  TX/RX throughput uses the installed driver's NVML library (KiB/s). Unsupported
  metrics are null, absent, or marked unobserved. Sampled VRAM maxima can miss
  short peaks and include other GPU processes; they are **not PyTorch allocator
  peaks**. Wrapper allocator statistics remain in the referenced console log.
- Linux RAM used/available and ComfyUI RSS are sampled via `/proc`, in KiB.
  Event delivery, console flushing, sampling and queue polling are asynchronous;
  offsets and correlations are approximate. Coverage warnings must be considered.

## Persistence, failures and storage

Reports use unique directories and never erase previous generations. Journals and
samples append; final Markdown and JSON use private temporary files plus atomic
replacement within the new generation's directory (JSON is the completion marker).
Only filtered settings/events are retained in memory; console reads are bounded
at 256 KiB per pass, graphs at 2048 nodes, event datagrams at 60 KiB, stored stage
intervals at 4096 and sampling observations at 128. Excess graph size is marked.
The collector performs disk and image work outside the ComfyUI process.

If the monitor exits, the launcher tries at most three restarts, replays the
unfinished journal and restores sampled peaks. Already completed prompt IDs from
that supervisor session are deduplicated. A clean ComfyUI exit with no terminal
event produces an incomplete report; an abrupt supervisor/pod termination leaves
append-only evidence. The next toolkit launch finalizes old unfinished journals
as incomplete, without inventing an execution duration across host restarts.
For offline inspection after an abrupt termination, run:

```bash
python3 tools/performance.py recover /path/to/saved/performance
```

This writes missing reports from unfinished journals; completed reports remain
untouched. A truncated final journal/sample line is tolerated. Writes are flushed
on close, but sudden storage/power loss can still lose the latest buffered data.
No software can recover observations that never reached persistent storage.

A failed/full socket drops diagnostics rather than blocking generation and emits
a warning. A recorder failure preserves the original ComfyUI console and journals.
Monitoring cannot guarantee a complete record after disk exhaustion or repeated
monitor failure. Below 100 MiB free, new performance samples pause with a warning;
compact report/event writes are still attempted. No retention cleanup is automatic.
Samples typically consume a few MiB per hour at the default interval, plus small
reports/journals; console/video/model storage remains the larger capacity concern.
Review capacity on the existing 100GB network volume during normal session
preflight. Moving/deleting old records is a separate operator decision.

Files survive pod termination **only when the configured log directory is on the
retained network volume**. Verify the `/workspace` mount before the next authorized
session, retain the same volume and attach it on a later pod. Container-local or
pod-local disk paths do not provide this persistence. The monitor does not alter
RunPod infrastructure, attach volumes, upload backups, or verify mount identity.

## Configuration and missing reports

Export settings before starting; `config.env` is not automatically sourced:

```bash
export COMFY_LOG_DIR=/workspace/wan-cloud-logs  # Existing override, unchanged
export COMFY_PERFORMANCE_INTERVAL=10          # Seconds; default 5, allowed 2–300
./start.sh --full
```

To disable optional diagnostics, set `export COMFY_PERFORMANCE=0` before launch.
Normal console logging, verification and readiness checks remain enabled. Invalid
interval settings warn and disable diagnostics for that launch rather than block
ComfyUI. No generation configuration is changed by either option.

For a missing report, inspect the automatic report directory and reported
`performance/monitor-*.log`, normal console log, startup status, and any
`events.jsonl`. A running job has a journal/sample file and gets final reports
on completion. Check for disabled diagnostics, permissions, full disk, unsupported
API/event behavior, collector restarts, and queue/history coverage warnings.
Use offline recovery on a copied or inactive report directory after a crash.
Do not rerun generation simply to obtain a report. Existing historic runs without
saved evidence cannot be reconstructed by this implementation.

## Next separately authorized GPU session

1. Complete repository preflight: persistent volume/mount, capacity, GPU/driver,
   pinned stack/model integrity and full verification. Keep the workflow unchanged.
2. Start `./start.sh --full` in tmux; require normal API/node readiness and the
   automatic performance directory/monitor-log announcement.
3. Submit an authorized browser job. Confirm its prompt-ID directory gains events
   and five-second samples; verify real GPU metrics and sampling log recognition.
4. After completion, check JSON/Markdown status, effective resolution, connected
   HIGH/LOW step counts, model/block-swap settings, stages and sample timestamps
   against the real console and saved video's properties.
5. On subsequent authorized runs, compare at least three jobs. Include a cached
   run and an operator interruption if appropriate; verify those are distinguished.
6. Close the service cleanly, preserve the network volume, and inspect/compare
   those same reports offline next session. Real GPU behavior and compatibility of
   the event tap with the complete pinned installation still need this validation.

Local regression tests simulate events, APIs, NVIDIA output and a child ComfyUI
process. They do **not** establish real GPU generation performance or compatibility.

## Local validation record

Validated locally on 2026-11-01 with Python 3.11.17:

```text
python3.11 -m unittest discover -s tests -q
Ran 92 tests — OK (skipped=2)
```

The 25 diagnostics tests cover successful/failed/interrupted jobs, sequential
runs, queue/history fixtures, missing metrics, monitor restarts and repeated
failures, terminal-event recovery after write failure, partial journals, dynamic
sampling dimensions, connected steps, private atomic writes, low disk space,
console preservation, offline comparison, and runner/collector subprocess wiring.
The two existing opt-in tests need `WAN_IMPORT_TEST_PYTHON` and
`WAN_WRAPPER_SOURCE`; neither was configured for this local implementation task.
Bash syntax checks for root/install/lib scripts and `git diff --check` also passed.
Tests used local HTTP/Unix socket fixtures with sandbox socket permission; no
remote commands, installations, model downloads, real ComfyUI service or GPU jobs
were performed.
