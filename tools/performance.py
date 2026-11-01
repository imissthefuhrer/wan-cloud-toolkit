"""Private, dependency-free generation diagnostics and offline comparison."""
import argparse
import csv
import ctypes
import struct
import urllib.request
import urllib.error
import urllib.parse
import hashlib
import heapq
import itertools
import json
import os
from pathlib import Path
import re
import select
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

EVENTS = {'execution_start', 'execution_cached', 'executing', 'execution_success',
          'execution_error', 'execution_interrupted', 'progress'}
# Deliberately exclude text, seeds, arbitrary strings, URLs and extra_data.
KEYS = set('width height num_frames multiplier fps steps start_step end_step force_offload offload_device use_teacache teacache_args slg_args flowedit_args feta_args blocks_to_swap base_precision quantization load_device attention_mode rms_norm_function force_offload tiled_vae offload_img_emb offload_txt_emb use_non_blocking vace_blocks_to_swap prefetch_blocks block_swap_args compile_args cache_args context_options model vae_name model_name ckpt_name image value int float shift cfg scheduler denoise tiled tile_x tile_y tile_stride_x tile_stride_y'.split())
STRING_KEYS = set('base_precision quantization load_device attention_mode rms_norm_function model vae_name model_name ckpt_name image scheduler'.split())


def stamp():
    return datetime.now(timezone.utc).isoformat()


def warn(message):
    print('Performance diagnostics warning: ' + message, file=sys.stderr, flush=True)


def private_append(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'a') as stream:
        stream.write(text)


def atomic(path, value):
    """Only replace our current snapshot; never touch another generation."""
    fd, name = tempfile.mkstemp(prefix='.report-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def safe_graph(graph):
    result = {}
    for nid, node in itertools.islice(graph.items(), 2048):
        kind = node.get('class_type', '')
        inputs = {}
        for key, value in node.get('inputs', {}).items():
            if key not in KEYS:
                continue
            if isinstance(value, (int, float, bool)) or value is None:
                inputs[key] = value
            elif isinstance(value, list) and len(value) == 2 and isinstance(value[0], str) and isinstance(value[1], int):
                inputs[key] = value
            elif isinstance(value, str) and key in STRING_KEYS:
                inputs[key] = Path(value).name[:200] if key in {'image', 'model', 'model_name', 'vae_name', 'ckpt_name'} else value[:80]
        result[str(nid)] = {'class_type': kind[:100], 'inputs': inputs}
    return result


def image_identity(directory, filename):
    """Hash at most 64 MiB; read dimensions without decoding/copying image pixels."""
    result = {'filename': filename, 'sha256': 'not_observed', 'dimensions': 'not_observed'}
    try:
        root = (Path(directory) / 'input').resolve()
        path = (root / filename).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 64 * 1024 * 1024:
            result['reason'] = 'missing, outside input directory, or exceeds 64 MiB hash limit'
            return result
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            header = stream.read(24)
            if header[:8] == b'\x89PNG\r\n\x1a\n' and len(header) == 24:
                result['dimensions'] = list(struct.unpack('>II', header[16:24]))
            elif header[:2] == b'\xff\xd8':
                stream.seek(2)
                # Bound header scanning; no decompression and no new dependency.
                while stream.tell() < min(path.stat().st_size, 1024 * 1024):
                    if stream.read(1) != b'\xff':
                        break
                    marker = stream.read(1)
                    while marker == b'\xff':
                        marker = stream.read(1)
                    if marker in (b'\xd9', b'\xda'):
                        break
                    size = struct.unpack('>H', stream.read(2))[0]
                    if marker and marker[0] in (0xc0, 0xc1, 0xc2):
                        _, h, w = struct.unpack('>BHH', stream.read(5))
                        result['dimensions'] = [w, h]
                        break
                    if size < 2:
                        break
                    stream.seek(size - 2, 1)
            stream.seek(0)
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        result['sha256'] = digest.hexdigest()
        result['evidence'] = 'input file at monitor observation time; not proof of cached tensor identity'
    except (OSError, ValueError, struct.error):
        result['reason'] = 'input unavailable or unsupported header'
    return result


def api_get(port, route):
    request = urllib.request.Request(f'http://127.0.0.1:{port}{route}')
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=1) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError('API response exceeded 2 MiB limit')
    return json.loads(payload)


def resolved(graph, nid, key, seen=None):
    seen = set() if seen is None else seen
    marker = (str(nid), key)
    if marker in seen:
        return None
    seen.add(marker)
    value = graph.get(str(nid), {}).get('inputs', {}).get(key)
    if isinstance(value, list):
        node = graph.get(value[0], {})
        # Only known scalar identity nodes; never guess arbitrary output slots.
        if value[1] == 0 and node.get('class_type') in {'INTConstant', 'FloatConstant', 'easy int', 'PrimitiveNode'}:
            for source in ('value', 'int', 'float'):
                if source in node.get('inputs', {}):
                    return resolved(graph, value[0], source, seen)
        return None
    return value


def settings(graph):
    result = {'evidence': 'submitted API inputs; linked constants resolved; dynamic node outputs unknown unless observed',
              'effective_resolution': 'not_observed', 'output_duration_seconds': 'not_observed', 'nodes': {}}
    for nid, node in graph.items():
        kind = node['class_type']
        if not any(s in kind.lower() for s in ('wanvideo', 'rife', 'video', 'loadimage')):
            continue
        values = {k: resolved(graph, nid, k) for k in node['inputs']}
        values = {k: ('unknown (connected output not observed)' if v is None and isinstance(node['inputs'][k], list) else v) for k, v in values.items()}
        if kind == 'WanVideoModelLoader':
            values['optional_torch_compile'] = 'enabled (connected)' if isinstance(node['inputs'].get('compile_args'), list) else 'disabled (input disconnected)'
        result['nodes'][nid] = {'type': kind, 'inputs': values}
        if kind == 'WanVideoImageToVideoEncode':
            w, h = (resolved(graph, nid, k) for k in ('width', 'height'))
            result['requested_resolution'] = [w, h]
            result['source_frames'] = resolved(graph, nid, 'num_frames')
        if 'RIFE' in kind:
            result['interpolation_multiplier'] = resolved(graph, nid, 'multiplier')
        if kind == 'CreateVideo':
            result['output_fps'] = resolved(graph, nid, 'fps')
        if kind == 'WanVideoSampler':
            steps, start, end = (resolved(graph, nid, k) for k in ('steps', 'start_step', 'end_step'))
            values['scheduled_step_count'] = max(0, min(steps, end) - start) if all(isinstance(v, (int, float)) for v in (steps, start, end)) else 'unknown'
    f, m, fps = (result.get(k) for k in ('source_frames', 'interpolation_multiplier', 'output_fps'))
    if all(isinstance(v, (int, float)) and v > 0 for v in (f, m, fps)):
        result['expected_output_frames'] = (f - 1) * m + 1
        result['expected_duration_seconds'] = ((f - 1) * m + 1) / fps
    # Label HIGH/LOW by the connected model's filename, never by node order.
    for nid, entry in result['nodes'].items():
        if entry['type'] in {'WanVideoSampler', 'WanVideoModelLoader'}:
            source = graph.get(nid, {}).get('inputs', {}).get('model')
            model = graph.get(source[0], {}).get('inputs', {}).get('model') if isinstance(source, list) else source
            entry['model_phase'] = ('HIGH' if isinstance(model, str) and 'high' in model.lower() else
                                    'LOW' if isinstance(model, str) and 'low' in model.lower() else 'unknown')
    return result


GPU_FIELDS = ['index', 'uuid', 'name', 'utilization.gpu', 'memory.used', 'memory.total', 'temperature.gpu', 'power.draw', 'power.limit', 'clocks.gr', 'clocks.mem', 'pcie.link.gen.current', 'clocks_throttle_reasons.active']


def parse_gpu(output, fields=GPU_FIELDS):
    rows = []
    for row in csv.reader(output.splitlines()):
        if len(row) != len(fields):
            continue
        values = {}
        for key, raw in zip(fields, row):
            raw = raw.strip()
            try:
                values[key] = float(raw)
            except ValueError:
                values[key] = None if ('N/A' in raw or 'Not Supported' in raw) else raw
        rows.append(values)
    return rows


def pcie_samples():
    """Use the installed driver's NVML library; no Python package/driver install."""
    result = {}
    try:
        lib = ctypes.CDLL('libnvidia-ml.so.1')
        if lib.nvmlInit_v2() != 0:
            return result
        try:
            count = ctypes.c_uint()
            if lib.nvmlDeviceGetCount_v2(ctypes.byref(count)) != 0:
                return result
            for i in range(min(count.value, 32)):
                handle = ctypes.c_void_p()
                if lib.nvmlDeviceGetHandleByIndex_v2(i, ctypes.byref(handle)) != 0:
                    continue
                values = {}
                for name, counter in (('tx_kib_per_second', 0), ('rx_kib_per_second', 1)):
                    value = ctypes.c_uint()
                    if lib.nvmlDeviceGetPcieThroughput(handle, counter, ctypes.byref(value)) == 0:
                        values[name] = value.value
                result[str(i)] = values
        finally:
            lib.nvmlShutdown()
    except (OSError, AttributeError):
        pass
    return result


def sample(pid):
    result = {'utc': stamp(), 'monotonic': time.monotonic(), 'gpus': [], 'pcie_throughput': 'not_observed (not exposed by portable query-gpu interface)'}
    try:
        cmd = ['nvidia-smi', '--query-gpu=' + ','.join(GPU_FIELDS), '--format=csv,noheader,nounits']
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        if run.returncode:
            # Older drivers may reject optional fields. Preserve the common metrics.
            fields = GPU_FIELDS[:11]
            run = subprocess.run(['nvidia-smi', '--query-gpu=' + ','.join(fields), '--format=csv,noheader,nounits'], capture_output=True, text=True, timeout=2)
        else:
            fields = GPU_FIELDS
        result['gpus'] = parse_gpu(run.stdout, fields) if run.returncode == 0 else []
        if run.returncode:
            result['gpu_status'] = 'unavailable (nvidia-smi query failed)'
    except (OSError, subprocess.TimeoutExpired):
        result['gpu_status'] = 'unavailable'
    result['pcie_throughput'] = pcie_samples() or 'not_observed (NVML unsupported/unavailable)'
    try:
        mem = dict((line.split(':')[0], int(line.split()[1])) for line in Path('/proc/meminfo').read_text().splitlines() if line.startswith(('MemTotal:', 'MemAvailable:')))
        result['ram_available_kib'] = mem['MemAvailable']
        result['ram_used_kib'] = mem['MemTotal'] - mem['MemAvailable']
        for line in Path(f'/proc/{int(pid)}/status').read_text().splitlines():
            if line.startswith('VmRSS:'):
                result['comfy_rss_kib'] = int(line.split()[1])
    except (OSError, ValueError, KeyError):
        pass
    return result


def stage(kind):
    return {'WanVideoModelLoader': 'model_loading', 'WanVideoSampler': 'sampler',
            'WanVideoDecode': 'vae_decode', 'RIFE VFI': 'rife', 'CreateVideo': 'video_creation', 'SaveVideo': 'video_save'}.get(kind, kind)


class Recorder:
    def __init__(self, root, console, session, directory=None):
        self.root = Path(root)
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.root.chmod(0o700)
        self.directory = directory
        self.seen = set()
        self.console = str(console)
        self.session = session
        self.active = None
        self.node = None
        self.pending_terminal = None
        self.console_fragment = b''
        self.queued_at = {}
        self.last_sequence = None
        self.recovery_peaks = {}
        self.offset = Path(console).stat().st_size if Path(console).exists() else 0
        # Recover unfinished journals; completed reports are immutable.
        for journal in self.root.glob('*/events.jsonl'):
            completed = journal.parent / 'report.json'
            if completed.exists():
                try:
                    previous = json.loads(completed.read_text())
                    if previous.get('session') == session:
                        self.seen.add(previous['prompt_id'])
                except (OSError, ValueError, KeyError):
                    pass
                continue
            saved = self.session, self.console, self.offset
            try:
                with journal.open() as stream:
                    first = json.loads(next(stream))
                    self.session = first.get('session', session)
                    self.console = first.get('console_path', self.console)
                    self.offset = first.get('console_offset', 0)
                    self.recovery_peaks = {}
                    samples = journal.parent / 'samples.jsonl'
                    if samples.exists():
                        with samples.open() as values:
                            for line in values:
                                try:
                                    for gpu in json.loads(line).get('gpus', []):
                                        used = gpu.get('memory.used')
                                        if isinstance(used, (int, float)):
                                            key = str(gpu.get('uuid', gpu.get('index')))
                                            self.recovery_peaks[key] = max(self.recovery_peaks.get(key, 0), used)
                                except ValueError:
                                    break
                    self.event(first, replay=journal.parent)
                    for line in stream:
                        try:
                            self.event(json.loads(line), replay=journal.parent)
                        except ValueError:
                            # A final partial line can result from abrupt host/power loss.
                            break
                    if self.active:
                        self.active['coverage'].append('monitor restarted; sample gap possible')
                        self.offset = self.active['console']['start_byte']
                        if self.session != session:
                            self.finish('incomplete (previous supervisor ended without terminal event)')
            except (OSError, ValueError, StopIteration):
                warn('could not recover an unfinished journal')
            finally:
                self.session, self.console, offset = saved
                if not self.active:
                    self.offset = offset

    def event(self, event, replay=None, defer=False):
        typ = event.get('type')
        pid = event.get('prompt_id')
        if typ == 'execution_start' and self.pending_terminal:
            self.finish_pending()
        if pid in self.seen:
            return
        if typ == 'execution_start' and self.active and pid == self.active['prompt_id']:
            return
        if typ == 'execution_start' or (pid and not self.active and typ in EVENTS):
            if self.active:
                self.finish('unknown (next prompt began without terminal event)', event['monotonic'])
            identity = re.sub(r'[^a-zA-Z0-9_-]', '_', str(pid))[:100]
            if replay:
                directory = replay
            else:
                directory = Path(tempfile.mkdtemp(prefix=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ-') + identity + '-', dir=self.root))
            self.console_fragment = b''
            graph = event.get('graph', {})
            self.active = {'schema_version': 1, 'session': self.session, 'prompt_id': pid, 'directory': str(directory),
                           'queued_utc': self.queued_at.get(pid, 'not_observed'), 'started_utc': event['utc'], 'start_monotonic': event['monotonic'], 'status': 'running',
                           'coverage': event.get('coverage', []) if typ == 'execution_start' else ['start event missing; partial coverage'],
                           'settings': settings(graph), 'graph': graph, 'stages': [], 'sampled_peak_vram_mib': dict(self.recovery_peaks) if replay else {},
                           'console': {'path': self.console, 'start_byte': self.offset},
                           'timing_basis': 'host monotonic wall-clock between node-start events; includes transfers, async GPU work and overhead; not GPU kernel timing'}
            if replay and 'input_images' in event:
                self.active['input_images'] = event['input_images']
            elif self.directory:
                self.active['input_images'] = [image_identity(self.directory, n['inputs']['image']) for n in graph.values()
                                               if n['class_type'] == 'LoadImage' and isinstance(n['inputs'].get('image'), str)]
            if not replay:
                private_append(directory / 'samples.jsonl', '')
            self.node = None
        if not self.active or (pid and pid != self.active['prompt_id']):
            return
        if not replay:
            event = {**event, 'session': self.session, 'console_path': self.console, 'console_offset': self.active['console']['start_byte']}
            if typ == 'execution_start':
                event['input_images'] = self.active.get('input_images', [])
            private_append(Path(self.active['directory']) / 'events.jsonl', json.dumps(event) + '\n')
        sequence = event.get('sequence')
        if sequence is not None:
            if self.last_sequence is not None and sequence != self.last_sequence + 1:
                if 'event sequence gap; one or more events may be missing' not in self.active['coverage']:
                    self.active['coverage'].append('event sequence gap; one or more events may be missing')
            self.last_sequence = sequence
        if event.get('coverage_warning'):
            self.active['coverage'].append(event['coverage_warning'])
        if typ == 'progress' and event.get('node') is not None and len(self.active.get('observed_progress', {})) < 4096:
            self.active.setdefault('observed_progress', {})[str(event['node'])] = {k: event.get(k) for k in ('value', 'max')}
        if typ == 'execution_cached':
            self.active['cached_nodes'] = event.get('nodes', [])[:2048]
        if typ == 'executing' or typ in {'execution_success', 'execution_error', 'execution_interrupted'}:
            now = event['monotonic']
            if self.node and len(self.active['stages']) < 4096:
                self.active['stages'].append({**self.node, 'wall_seconds_approx': max(0, now - self.node['start_monotonic'])})
                self.node = None
            nid = event.get('node')
            if typ == 'executing' and nid is not None:
                kind = self.active['graph'].get(str(nid), {}).get('class_type', 'unknown')
                self.node = {'node_id': str(nid), 'stage': stage(kind), 'phase': self.active['settings']['nodes'].get(str(nid), {}).get('model_phase', 'unknown'), 'start_monotonic': now, 'console_byte_approx': self.offset}
            if typ in {'execution_success', 'execution_error', 'execution_interrupted'}:
                status = {'execution_success': 'success', 'execution_error': 'failed', 'execution_interrupted': 'interrupted'}[typ]
                if defer:
                    # Journal already contains the terminal event; wait briefly for console flush/summary.
                    self.pending_terminal = (status, now, event, time.monotonic() + 2)
                else:
                    self.finish(status, now, event)
            # executing(None) is not sufficient proof of success; wait for terminal/history.

    def console_lines(self):
        try:
            with open(self.console, 'rb') as stream:
                stream.seek(self.offset)
                data = stream.read(262144)
                start = self.offset - len(self.console_fragment)
                self.offset = stream.tell()
                data = self.console_fragment + data
                self.console_fragment = data[-1024:]
            if self.active:
                # Numeric evidence only; full console remains in its existing private file.
                for match in re.finditer(rb'Sampling (\d+) frames(?: in [^\r\n]{0,80}?,)? at (\d+)x(\d+)[^\r\n]{0,80}?(\d+) steps', data):
                    f, w, h, steps = map(int, match.groups())
                    self.active['settings']['effective_resolution'] = [w, h]
                    observation = {'frames': f, 'width': w, 'height': h, 'steps': steps, 'console_byte_approx': start + match.start(), 'evidence': 'WanVideoWrapper runtime log; steps may be split sampler steps'}
                    self.active['settings']['observed_sampling'] = observation
                    observations = self.active['settings'].setdefault('sampling_observations', [])
                    if len(observations) < 128 and not any(o['console_byte_approx'] == observation['console_byte_approx'] for o in observations):
                        observations.append(observation)
                summary = re.findall(rb'Prompt executed in ([0-9.]+) seconds', data)
                if summary:
                    self.active['comfy_reported_execution_seconds'] = float(summary[-1])
                self.active['console']['end_byte'] = self.offset
        except OSError:
            pass

    def sampled(self, value):
        if not self.active:
            return
        stats = os.statvfs(self.root)
        if stats.f_bavail * stats.f_frsize < 100 * 1024 * 1024:
            note = 'sampling paused: less than 100 MiB free; no historical files removed'
            if note not in self.active['coverage']:
                self.active['coverage'].append(note)
                warn(note)
            return
        private_append(Path(self.active['directory']) / 'samples.jsonl', json.dumps(value) + '\n')
        self.update_peaks(value)

    def update_peaks(self, value):
        for gpu in value.get('gpus', []):
            used = gpu.get('memory.used')
            key = str(gpu.get('uuid', gpu.get('index')))
            if isinstance(used, (int, float)):
                peaks = self.active['sampled_peak_vram_mib']
                peaks[key] = max(peaks.get(key, 0), used)

    def finish_pending(self):
        if self.pending_terminal:
            status, now, event, _ = self.pending_terminal
            self.pending_terminal = None
            self.finish(status, now, event)

    def finish(self, status, now=None, event=None):
        if not self.active:
            return
        self.console_lines()
        report = self.active
        report.update(status=status, ended_utc=event.get('utc', stamp()) if event else stamp(), wall_seconds=(max(0, now - report['start_monotonic']) if now is not None else None))
        if event and event.get('exception_type'):
            report['exception_type'] = event['exception_type']
        report['notes'] = ['VRAM peaks are sampled device-wide usage, not exact PyTorch allocations.',
                           'Event duration ends at the execution result; ComfyUI console execution seconds, when observed, may also include executor cleanup.',
                           'Model HIGH/LOW identity is in node model names and sampler model links; model work may be deferred into samplers.',
                           'No full prompts, image data, environment or traceback payloads are stored here. See console byte range for original evidence.',
                           'Actual output frame count/duration and dynamic values are not observed unless explicitly stated.']
        directory = Path(report['directory'])
        # Drop internal graph; retain only filtered settings.
        public = {k: v for k, v in report.items() if k not in {'graph', 'directory'}}
        atomic(directory / 'report.md', markdown(public))
        atomic(directory / 'report.json', json.dumps(public, indent=2) + '\n')
        self.seen.add(report['prompt_id'])
        self.pending_terminal = None
        self.active = None
        self.node = None


def markdown(report):
    settings = report['settings']
    lines = [f"# Generation {report['prompt_id']}", '']
    if report.get('synthetic'):
        lines += ['**SYNTHETIC EXAMPLE — simulated measurements; no GPU generation.**', '']
    lines += [f"Status: {report['status']}; host wall time: {report.get('wall_seconds')} seconds.", '',
              f"ComfyUI console execution seconds: {report.get('comfy_reported_execution_seconds', 'not_observed')}.", '',
              f"Started (UTC): {report['started_utc']}", '',
              f"Effective resolution: {settings['effective_resolution']}; source frames (API): {settings.get('source_frames', 'unknown')}; "
              f"interpolation: {settings.get('interpolation_multiplier', 'unknown')}×; FPS (API): {settings.get('output_fps', 'unknown')}.", '',
              f"Expected duration: {settings.get('expected_duration_seconds', 'unknown')} s; actual output duration: {settings['output_duration_seconds']}.", '',
              f"Input identifiers: {report.get('input_images', 'not_observed')}", '',
              f"Sampled device VRAM peaks (MiB): {report['sampled_peak_vram_mib']}", '',
              '| Node | Phase | Settings |', '|---|---|---|']
    for nid, node in settings['nodes'].items():
        if node['type'] in {'WanVideoSampler', 'WanVideoModelLoader', 'WanVideoBlockSwap'}:
            lines.append(f"| {nid} {node['type']} | {node.get('model_phase', '')} | {json.dumps(node['inputs'])} |")
    lines += ['', '| Node | Phase | Stage | Approx wall seconds |', '|---|---|---|---:|']
    for item in report['stages']:
        lines.append(f"| {item['node_id']} | {item.get('phase', '')} | {item['stage']} | {item['wall_seconds_approx']:.3f} |")
    lines += ['', f"Cached nodes: {report.get('cached_nodes', 'not_observed')}", '',
              f"Console evidence (approximate byte range): `{report['console']}`", '',
              f"Coverage: {report['coverage'] or 'no gaps detected (not a guarantee of complete GPU observation)'}", '',
              report['timing_basis'], '', 'Full filtered settings and runtime observations: `report.json`.', '']
    lines += ['- ' + note for note in report['notes']]
    return '\n'.join(lines) + '\n'


def observe_api(recorder, queue, port):
    """Bounded queue snapshot and one prompt-specific history request; no /history dump."""
    running = queue.get('queue_running', [])[:1]
    pending = queue.get('queue_pending', [])[:128]
    ids = [str(item[1]) for item in pending if len(item) > 1]
    if ids != getattr(recorder, 'queued', None):
        private_append(recorder.root / (recorder.session + '.queue.jsonl'), json.dumps({'utc': stamp(), 'queued_prompt_ids': ids, 'truncated_at': 128}) + '\n')
        recorder.queued = ids
        recorder.queued_at = {pid: recorder.queued_at.get(pid, stamp()) for pid in ids}
    if running and not recorder.active:
        item = running[0]
        recorder.event({'type': 'execution_start', 'prompt_id': item[1], 'utc': stamp(), 'monotonic': time.monotonic(),
                        'graph': safe_graph(item[2]), 'coverage': ['discovered via queue; start/stage coverage incomplete']})
    if recorder.pending_terminal:
        return
    if recorder.active and not any(item[1] == recorder.active['prompt_id'] for item in running):
        pid = recorder.active['prompt_id']
        try:
            history = api_get(port, '/history/' + urllib.parse.quote(str(pid), safe='')).get(pid, {})
        except (OSError, ValueError, urllib.error.URLError):
            note = 'prompt history unavailable or response exceeded limit'
            if note not in recorder.active['coverage']:
                recorder.active['coverage'].append(note)
                warn(note)
            return
        status = history.get('status', {})
        if status.get('completed') or status.get('status_str') == 'error':
            recorder.active['coverage'].append('terminal result recovered from history; duration includes observation delay')
            messages = status.get('messages', [])
            interrupted = any(m[0] == 'execution_interrupted' for m in messages)
            recorder.finish('interrupted' if interrupted else ('success' if status.get('status_str') == 'success' else 'failed'), time.monotonic())


def monitor(args):
    sock = socket.socket(fileno=args.fd)
    recorder = Recorder(args.root, args.console, args.session, args.directory)
    next_api = 0
    expected_parent = os.getppid()
    next_sample = 0
    pid = args.pid
    while True:
        ready, _, _ = select.select([sock], [], [], .5)
        if ready:
            raw = sock.recv(65536)
            event = json.loads(raw)
            if event['type'] == 'shutdown':
                recorder.finish_pending()
                recorder.finish('incomplete (ComfyUI exited without terminal event)')
                return
            if event['type'] == 'pid':
                pid = event['pid']
            else:
                recorder.event(event, defer=True)
        recorder.console_lines()
        if recorder.pending_terminal and (time.monotonic() >= recorder.pending_terminal[3] or 'comfy_reported_execution_seconds' in recorder.active):
            recorder.finish_pending()
        if time.monotonic() >= next_api:
            next_api = time.monotonic() + 5
            try:
                queue = api_get(args.port, '/queue')
            except (OSError, ValueError, urllib.error.URLError):
                queue = None  # Startup HTTP unavailability is expected.
                if recorder.active and 'queue API unavailable' not in recorder.active['coverage']:
                    recorder.active['coverage'].append('queue API unavailable')
                    warn('queue API unavailable; event recording continues')
            if queue is not None:
                observe_api(recorder, queue, args.port)
        if recorder.active and time.monotonic() >= next_sample:
            recorder.sampled(sample(pid))
            next_sample = time.monotonic() + args.interval
        # Parent crash: preserve partial state rather than wait forever.
        if os.getppid() != expected_parent or os.getppid() == 1:
            recorder.finish_pending()
            recorder.finish('incomplete (supervisor disappeared)')
            return


def compare(root, limit):
    paths = heapq.nlargest(limit, Path(root).glob('*/report.json'))
    print('| Prompt | Status | Seconds | Effective WxH | Frames | Steps per sampler | Sampled VRAM MiB | Stage seconds (approx) |')
    print('|---|---|---:|---|---:|---|---|---|')
    for path in reversed(paths):
        try:
            r = json.loads(path.read_text())
            s = r['settings']
            steps = ', '.join(f"{nid}:{n['inputs'].get('scheduled_step_count', 'unknown')}" for nid, n in s['nodes'].items() if n['type'] == 'WanVideoSampler')
            stages = ', '.join(f"{x['node_id']} {x.get('phase', '')} {x['stage']}={x['wall_seconds_approx']:.1f}" for x in r['stages'])
            print(f"| {r['prompt_id']} | {r['status']} | {r.get('wall_seconds')} | {s['effective_resolution']} | {s.get('source_frames', 'unknown')} | {steps} | {r['sampled_peak_vram_mib']} | {stages} |")
        except (OSError, ValueError, KeyError):
            warn('unreadable report: ' + str(path))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    recovery = sub.add_parser('recover', help='finalize unfinished journals offline as incomplete')
    recovery.add_argument('root')
    c = sub.add_parser('compare')
    c.add_argument('root', nargs='?', default=str(Path(os.environ.get('COMFY_LOG_DIR', '/workspace/wan-cloud-logs')) / 'performance'))
    c.add_argument('--limit', type=int, default=10)
    m = sub.add_parser('monitor')
    for name in ('root', 'console', 'session'):
        m.add_argument('--' + name, required=True)
    m.add_argument('--fd', type=int, required=True)
    m.add_argument('--pid', type=int, default=0)
    m.add_argument('--interval', type=float, default=5)
    m.add_argument('--directory')
    m.add_argument('--port', type=int, default=8888)
    args = p.parse_args()
    if args.command == 'recover':
        Recorder(args.root, '/nonexistent-console', 'offline-recovery-' + stamp())
    elif args.command == 'compare':
        compare(args.root, max(1, min(args.limit, 1000)))
    else:
        args.interval = max(2, min(args.interval, 300))
        monitor(args)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        warn(type(error).__name__ + ': recording stopped; original ComfyUI console retained')
        sys.exit(1)
