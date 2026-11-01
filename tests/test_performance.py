"""Offline fixtures only: no CUDA, model downloads or RunPod access."""
import contextlib
import io
import json
import os
from pathlib import Path
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import performance as perf
import comfy_performance_runner as runner
import start_comfyui as launcher


def graph():
    return {
        '1': {'class_type': 'INTConstant', 'inputs': {'value': 8}},
        '2': {'class_type': 'INTConstant', 'inputs': {'value': 4}},
        '3': {'class_type': 'WanVideoModelLoader', 'inputs': {'model': 'Wan_HIGH.safetensors', 'base_precision': 'fp16', 'block_swap_args': ['9', 0]}},
        '4': {'class_type': 'WanVideoSampler', 'inputs': {'model': ['3', 0], 'steps': ['1', 0], 'start_step': 0, 'end_step': ['2', 0]}},
        '5': {'class_type': 'WanVideoImageToVideoEncode', 'inputs': {'width': ['12', 0], 'height': ['12', 1], 'num_frames': 113}},
        '6': {'class_type': 'RIFE VFI', 'inputs': {'multiplier': 2}},
        '7': {'class_type': 'CreateVideo', 'inputs': {'fps': 32}},
        '8': {'class_type': 'WanVideoDecode', 'inputs': {}},
        '9': {'class_type': 'WanVideoBlockSwap', 'inputs': {'blocks_to_swap': 20}},
        '10': {'class_type': 'CLIPTextEncode', 'inputs': {'text': 'PRIVATE PROMPT TOKEN SECRET'}},
        '11': {'class_type': 'LoadImage', 'inputs': {'image': 'input.png'}},
        '12': {'class_type': 'GetImageSize', 'inputs': {}},
        '13': {'class_type': 'WanVideoModelLoader', 'inputs': {'model': 'Wan_LOW.safetensors'}},
        '14': {'class_type': 'WanVideoSampler', 'inputs': {'model': ['13', 0], 'steps': ['1', 0], 'start_step': ['2', 0], 'end_step': 10000}},
        '15': {'class_type': 'SaveVideo', 'inputs': {}},
    }


def event(typ, seconds, pid='synthetic-prompt', **kwargs):
    return {'type': typ, 'prompt_id': pid, 'utc': '2026-01-01T00:00:00+00:00', 'monotonic': seconds, **kwargs}


class Recording(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.console = self.base / 'comfy.log'
        self.console.write_text('old persistent console\n')
        self.root = self.base / 'performance'
        self.r = perf.Recorder(self.root, self.console, 'test-session')

    def start(self, pid='synthetic-prompt'):
        self.r.event(event('execution_start', 10, pid, graph=perf.safe_graph(graph())))

    def reports(self):
        return [json.loads(p.read_text()) for p in self.root.glob('*/report.json')]

    def test_success_dynamic_console_and_connected_sampler_inputs(self):
        self.start()
        self.r.event(event('executing', 12, node='3'))
        self.r.event(event('executing', 17, node='4'))
        with self.console.open('a') as stream:
            stream.write('Sampling 113 frames at 720x480 with 4 steps\n')
        self.r.console_lines()
        self.r.event(event('progress', 18, node='4', value=4, max=4))
        self.r.event(event('executing', 27, node='8'))
        self.r.sampled({'utc': perf.stamp(), 'gpus': [{'uuid': 'GPU-fixture', 'memory.used': 24000}]})
        self.r.event(event('execution_success', 30))
        r = self.reports()[0]
        self.assertEqual(r['status'], 'success')
        self.assertEqual(r['wall_seconds'], 20)
        self.assertEqual([s['wall_seconds_approx'] for s in r['stages']], [5, 10, 3])
        self.assertEqual(r['stages'][1]['phase'], 'HIGH')
        self.assertEqual(r['settings']['effective_resolution'], [720, 480])
        self.assertEqual(r['settings']['requested_resolution'], [None, None])
        self.assertEqual(r['settings']['nodes']['4']['inputs']['steps'], 8)
        self.assertEqual(r['settings']['nodes']['4']['inputs']['scheduled_step_count'], 4)
        self.assertEqual(r['settings']['nodes']['14']['inputs']['scheduled_step_count'], 4)
        self.assertEqual(r['settings']['nodes']['14']['model_phase'], 'LOW')
        self.assertAlmostEqual(r['settings']['expected_duration_seconds'], 7.03125)
        self.assertEqual(r['settings']['output_duration_seconds'], 'not_observed')
        self.assertEqual(r['observed_progress']['4']['max'], 4)
        self.assertEqual(r['sampled_peak_vram_mib']['GPU-fixture'], 24000)
        self.assertNotIn('PRIVATE PROMPT', json.dumps(r))
        self.assertEqual(r['settings']['nodes']['3']['inputs']['optional_torch_compile'], 'disabled (input disconnected)')
        self.assertIn('old persistent console', self.console.read_text())
        self.assertTrue(next(self.root.glob('*/report.md')).exists())

    def test_failed_interrupted_and_crashed(self):
        for index, terminal in enumerate(('execution_error', 'execution_interrupted')):
            self.start(str(index))
            self.r.event(event(terminal, 25, str(index), exception_type='RuntimeError'))
        self.start('crash')
        self.r.finish('incomplete (ComfyUI exited without terminal event)')
        self.assertEqual({r['status'].split()[0] for r in self.reports()}, {'failed', 'interrupted', 'incomplete'})
        self.assertIsNone(next(r for r in self.reports() if r['prompt_id'] == 'crash')['wall_seconds'])

    def test_multiple_sequential_generations_preserve_prior_bytes(self):
        for i in range(3):
            self.start(str(i))
            self.r.event(event('execution_success', 20 + i, str(i)))
        before = {p: p.read_bytes() for p in self.root.glob('*/*')}
        self.start('fourth')
        self.r.event(event('execution_success', 40, 'fourth'))
        for path, data in before.items():
            self.assertEqual(path.read_bytes(), data)
        self.assertEqual(len(self.reports()), 4)

    def test_monitor_restart_replays_events_samples_and_deduplicates(self):
        self.start()
        self.r.event(event('executing', 12, node='4'))
        self.r.sampled({'gpus': [{'uuid': 'GPU-fixture', 'memory.used': 33333}]})
        self.r = perf.Recorder(self.root, self.console, 'test-session')
        self.r.event(event('execution_success', 30))
        self.assertEqual(len(self.reports()), 1)
        self.assertEqual(self.reports()[0]['sampled_peak_vram_mib']['GPU-fixture'], 33333)
        self.assertEqual(self.reports()[0]['stages'][0]['wall_seconds_approx'], 18)
        self.r = perf.Recorder(self.root, self.console, 'test-session')
        self.r.event(event('execution_success', 30))
        self.assertEqual(len(self.reports()), 1)
        self.assertEqual(len(list(self.root.glob('*/events.jsonl'))), 1)

    def test_new_supervisor_recovers_partial_previous_session(self):
        self.start()
        self.r.event(event('executing', 12, node='4'))
        journal = next(self.root.glob('*/events.jsonl'))
        with journal.open('a') as stream:
            stream.write('{partial')
        perf.Recorder(self.root, self.console, 'new-session')
        self.assertIn('incomplete', self.reports()[0]['status'])
        self.assertIsNone(self.reports()[0]['wall_seconds'])

    def test_incomplete_history_does_not_claim_success(self):
        self.start()
        with patch.object(perf, 'api_get', return_value={}):
            perf.observe_api(self.r, {'queue_running': [], 'queue_pending': []}, 8888)
        self.assertEqual(self.r.active['status'], 'running')
        self.assertEqual(self.reports(), [])

    def test_queue_discovery_and_history_failure_recovery(self):
        queue = {'queue_running': [[0, 'late', graph(), {}, []]], 'queue_pending': [[1, 'pending', {}, {}, []]]}
        perf.observe_api(self.r, queue, 8888)
        self.assertIn('incomplete', self.r.active['coverage'][0])
        with patch.object(perf, 'api_get', return_value={'late': {'status': {'status_str': 'error', 'completed': False, 'messages': [['execution_interrupted', {}]]}}}):
            perf.observe_api(self.r, {'queue_running': [], 'queue_pending': []}, 8888)
        self.assertEqual(self.reports()[0]['status'], 'interrupted')
        queue_log = next(self.root.glob('*.queue.jsonl')).read_text()
        self.assertIn('pending', queue_log)
        self.assertNotIn('PRIVATE PROMPT', queue_log)

    def test_report_write_failure_recovers_terminal_result_and_peaks(self):
        self.start()
        self.r.sampled({'gpus': [{'uuid': 'GPU-fixture', 'memory.used': 12345}]})
        with patch.object(perf, 'atomic', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                self.r.event(event('execution_success', 40))
        self.r = perf.Recorder(self.root, self.console, 'test-session')
        self.assertEqual(self.reports()[0]['status'], 'success')
        self.assertEqual(self.reports()[0]['sampled_peak_vram_mib']['GPU-fixture'], 12345)

    def test_terminal_is_journaled_before_console_flush_and_recoverable(self):
        self.start()
        self.r.event(event('execution_success', 40), defer=True)
        self.assertEqual(self.reports(), [])
        self.assertIn('execution_success', next(self.root.glob('*/events.jsonl')).read_text())
        with self.console.open('a') as stream:
            stream.write('Prompt executed in 31.25 seconds\n')
        self.r.finish_pending()
        self.assertEqual(self.reports()[0]['wall_seconds'], 30)
        self.assertEqual(self.reports()[0]['comfy_reported_execution_seconds'], 31.25)

    def test_event_gap_is_explicit_and_console_chunks_reassemble(self):
        self.r.event(event('execution_start', 10, graph=perf.safe_graph(graph()), sequence=1))
        self.r.event(event('executing', 12, node='4', sequence=3))
        with self.console.open('a') as stream:
            stream.write('Sampling 113 frames at 720x')
        self.r.console_lines()
        with self.console.open('a') as stream:
            stream.write('480 with 4 steps\n')
        self.r.console_lines()
        self.r.event(event('execution_success', 30, sequence=4))
        self.assertEqual(self.reports()[0]['settings']['effective_resolution'], [720, 480])
        self.assertTrue(any('sequence gap' in c for c in self.reports()[0]['coverage']))

    def test_low_disk_pauses_samples_without_deleting_history(self):
        self.start()
        with patch.object(perf.os, 'statvfs', return_value=types.SimpleNamespace(f_bavail=1, f_frsize=4096)):
            self.r.sampled({'gpus': []})
        self.assertIn('sampling paused', self.r.active['coverage'][0])
        self.assertEqual(next(self.root.glob('*/samples.jsonl')).read_text(), '')
        self.r.event(event('execution_success', 30))
        self.assertEqual(len(self.reports()), 1)

    def test_unknown_dynamic_values_and_cycles(self):
        s = perf.settings(perf.safe_graph(graph()))
        self.assertEqual(s['effective_resolution'], 'not_observed')
        self.assertIn('unknown', s['nodes']['5']['inputs']['width'])
        cyc = {'1': {'class_type': 'INTConstant', 'inputs': {'value': ['1', 0]}}}
        self.assertIsNone(perf.resolved(cyc, '1', 'value'))

    def test_restricted_permissions_and_atomic_writes(self):
        self.start()
        self.r.event(event('execution_success', 25))
        for path in self.root.rglob('*'):
            mode = stat.S_IMODE(path.stat().st_mode)
            self.assertEqual(mode & 0o077, 0, str(path))
        destination = self.root / 'atomic.json'
        perf.atomic(destination, 'original')
        with patch.object(perf.os, 'replace', side_effect=OSError('synthetic disk error')):
            with self.assertRaises(OSError):
                perf.atomic(destination, 'new')
        self.assertEqual(destination.read_text(), 'original')
        self.assertEqual(list(self.root.glob('.report-*')), [])

    def test_console_memory_and_windowed_sampling_formats(self):
        self.start()
        with self.console.open('a') as stream:
            stream.write('Sampling 113 frames in 2 windows, at 832x480 with 4 steps\nCUDA allocated 123 MiB\n')
        self.r.console_lines()
        self.r.event(event('execution_success', 30))
        self.assertEqual(self.reports()[0]['settings']['effective_resolution'], [832, 480])
        self.assertIn('CUDA allocated', self.console.read_text())

    def test_offline_comparison(self):
        for i in range(3):
            self.start(str(i))
            self.r.event(event('execution_success', 20 + i, str(i)))
        with contextlib.redirect_stdout(io.StringIO()) as output:
            perf.compare(self.root, 3)
        self.assertEqual(output.getvalue().count('| success |'), 3)
        self.assertIn('not_observed', output.getvalue())


class Interfaces(unittest.TestCase):
    def test_optional_gpu_fields_and_missing_nvidia(self):
        rows = perf.parse_gpu('0, GPU-fixture, A6000, 99, 23456, 49140, 65, 230, 300, 1800, 7000, N/A, [Not Supported]')
        self.assertEqual(rows[0]['memory.used'], 23456)
        self.assertIsNone(rows[0]['clocks_throttle_reasons.active'])
        with patch.object(perf.subprocess, 'run', side_effect=FileNotFoundError), patch.object(perf, 'pcie_samples', return_value={}):
            self.assertEqual(perf.sample(os.getpid())['gpu_status'], 'unavailable')

    def test_optional_gpu_query_falls_back(self):
        good = '0, GPU-fixture, A6000, 99, 23000, 49140, 65, 230, 300, 1800, 7000'
        with patch.object(perf.subprocess, 'run', side_effect=[Mock(returncode=1), Mock(returncode=0, stdout=good)]) as run, patch.object(perf, 'pcie_samples', return_value={}):
            self.assertEqual(perf.sample(os.getpid())['gpus'][0]['memory.used'], 23000)
            self.assertEqual(run.call_count, 2)

    def test_image_hash_dimensions_and_no_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'input').mkdir()
            (root / 'input/input.png').write_bytes(b'\x89PNG\r\n\x1a\n' + b'\0' * 8 + struct.pack('>II', 1920, 1080))
            identity = perf.image_identity(root, 'input.png')
            self.assertEqual(identity['dimensions'], [1920, 1080])
            self.assertEqual(len(identity['sha256']), 64)
            self.assertEqual(perf.image_identity(root, '../secret')['sha256'], 'not_observed')

    def test_tap_preserves_browser_delivery_and_filters_sensitive_payloads(self):
        original = Mock(return_value='original return')
        cls = type('PromptServer', (), {'send_sync': original})
        module = types.SimpleNamespace(PromptServer=cls)
        instance = cls()
        instance.prompt_queue = Mock()
        instance.prompt_queue.get_current_queue.return_value = ([[0, 'id', graph(), {'api_token': 'SECRET'}, []]], [])
        emit = Mock()
        runner.install_tap(module, emit)
        self.assertEqual(instance.send_sync('execution_start', {'prompt_id': 'id'}, 'browser-client'), 'original return')
        original.assert_called_once_with(instance, 'execution_start', {'prompt_id': 'id'}, 'browser-client')
        self.assertNotIn('SECRET', json.dumps(emit.call_args.args[0]))
        self.assertNotIn('PRIVATE PROMPT', json.dumps(emit.call_args.args[0]))
        emit.side_effect = OSError('full channel')
        self.assertEqual(instance.send_sync('execution_success', {'prompt_id': 'id'}), 'original return')

    def test_api_is_loopback_proxy_free_and_bounded(self):
        response = Mock()
        response.read.return_value = b'{}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(perf.urllib.request, 'build_opener', return_value=opener):
            self.assertEqual(perf.api_get(8888, '/queue'), {})
            self.assertEqual(opener.open.call_args.args[0].full_url, 'http://127.0.0.1:8888/queue')
            response.read.return_value = b'x' * (2 * 1024 * 1024 + 1)
            with self.assertRaisesRegex(ValueError, 'limit'):
                perf.api_get(8888, '/queue')

    @patch.dict(os.environ, {'COMFY_PERFORMANCE': '0'})
    def test_disabled_diagnostics_preserve_legacy_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = Mock(pid=123, stdout=io.BytesIO(b'console\n'), returncode=0)
            process.poll.side_effect = [None, 0, 0]
            with patch.object(launcher, 'preflight'), patch.object(launcher, 'health'), patch.object(launcher.subprocess, 'Popen', return_value=process) as start:
                self.assertEqual(launcher.supervise(tmp, 8888, 1, tmp), 0)
            self.assertEqual(start.call_count, 1)
            self.assertEqual(start.call_args.args[0][2], 'main.py')
            self.assertFalse((Path(tmp) / 'performance').exists())

    @patch.dict(os.environ, {'COMFY_PERFORMANCE': '1'})
    def test_monitor_setup_failure_does_not_interrupt_comfy(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = Mock(pid=123, stdout=io.BytesIO(b'console\n'), returncode=0)
            process.poll.side_effect = [None, 0, 0]
            with patch.object(launcher, 'preflight'), patch.object(launcher, 'health'), patch.object(launcher.socket, 'socketpair', side_effect=OSError('synthetic failure')), patch.object(launcher.subprocess, 'Popen', return_value=process):
                self.assertEqual(launcher.supervise(tmp, 8888, 1, tmp), 0)

    @patch.dict(os.environ, {'COMFY_PERFORMANCE': '1'})
    def test_repeated_monitor_failure_never_stops_generation(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = Mock(pid=123, stdout=io.BytesIO(b'console\n'), returncode=0)
            process.poll.side_effect = [None, None, None, None, None, 0, 0]
            monitor = Mock()
            monitor.poll.return_value = 1
            with patch.object(launcher, 'preflight'), patch.object(launcher, 'health'), patch.object(launcher.subprocess, 'Popen', side_effect=[monitor, process, monitor, monitor, monitor]) as launch:
                self.assertEqual(launcher.supervise(tmp, 8888, 1, tmp), 0)
            self.assertEqual(launch.call_count, 5)
            process.terminate.assert_not_called()

    def test_preflight_detects_toolkit_runner_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'venv/bin').mkdir(parents=True)
            (root / 'venv/bin/python').symlink_to(sys.executable)
            (root / 'server.py').write_text('class PromptServer:\n def send_sync(self, *args): pass\n')
            (root / 'main.py').write_text('import time\ntime.sleep(30)\n')
            sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
            try:
                process = subprocess.Popen([sys.executable, str(Path(runner.__file__)), str(sender.fileno()), str(root)], cwd=root, pass_fds=(sender.fileno(),), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    with self.assertRaisesRegex(RuntimeError, 'Existing ComfyUI process'):
                        launcher.preflight(root, 43199)
                finally:
                    process.terminate()
                    process.wait(timeout=3)
            finally:
                sender.close()
                receiver.close()

    def test_runner_and_monitor_subprocess_integration(self):
        """Normal main.py imports server, simulates browser events, and exits."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'venv/bin').mkdir(parents=True)
            (root / 'venv/bin/python').symlink_to(sys.executable)
            (root / 'server.py').write_text('class PromptServer:\n def send_sync(self, *args, **kwargs): pass\n')
            (root / 'main.py').write_text('''import time
from server import PromptServer
class Queue:
 def get_current_queue(self):
  return ([[0, "integration", {"1": {"class_type": "WanVideoSampler", "inputs": {"steps": 8}}}, {}, []]], [])
s = PromptServer()
s.prompt_queue = Queue()
time.sleep(.4)
s.send_sync("execution_start", {"prompt_id": "integration"}, "browser")
s.send_sync("executing", {"prompt_id": "integration", "node": "1"}, "browser")
print("Sampling 113 frames at 720x480 with 4 steps", flush=True)
time.sleep(.8)
s.send_sync("execution_success", {"prompt_id": "integration"}, "browser")
print("Prompt executed in 1.20 seconds", flush=True)
time.sleep(.4)
''')
            with patch.dict(os.environ, {'COMFY_PERFORMANCE': '1'}), patch.object(launcher, 'preflight'), patch.object(launcher, 'health'):
                self.assertEqual(launcher.supervise(root, 43199, 3, root / 'logs'), 0)
            reports = list((root / 'logs/performance').glob('*/report.json'))
            self.assertEqual(len(reports), 1)
            report = json.loads(reports[0].read_text())
            self.assertEqual(report['status'], 'success')
            self.assertEqual(report['comfy_reported_execution_seconds'], 1.2)
            self.assertEqual(report['settings']['effective_resolution'], [720, 480])
            self.assertTrue(next((root / 'logs').glob('*.log')).exists())


if __name__ == '__main__':
    unittest.main()
