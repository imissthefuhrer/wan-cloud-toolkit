"""Offline contracts and behavioral fixtures; no Docker build/GPU claim."""
import ctypes
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import quick_check as quick
import start_comfyui as server
from comfy_health import port_number


class QuickChecks(unittest.TestCase):
    def test_mount_requires_exact_mount_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.wan-volume-id').write_text('existing-volume')
            response = json.dumps({'filesystems': [{'target': tmp, 'fstype': 'fuse'}]})
            with patch.object(quick, 'run', return_value=response):
                quick.mounted(root, 'existing-volume')
                with self.assertRaisesRegex(RuntimeError, 'WAN_VOLUME_ID'):
                    quick.mounted(root, 'another-volume')
                with self.assertRaisesRegex(RuntimeError, 'WAN_VOLUME_ID'):
                    quick.mounted(root, '')
            for target, kind in [('/', 'ext4'), (tmp, 'overlay'), (tmp, 'tmpfs')]:
                with patch.object(quick, 'run', return_value=json.dumps({'filesystems': [{'target': target, 'fstype': kind}]})):
                    with self.assertRaisesRegex(RuntimeError, 'network volume'):
                        quick.mounted(root, 'existing-volume')

    def test_record_then_quick_check_and_change_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            workspace = Path(tmp)
            directory = workspace / 'ComfyUI'
            directory.mkdir()
            with patch.object(quick, 'mounted'), patch.object(quick, 'gpu'), patch.object(quick, 'environment', return_value={'packages': [['torch', '2.4.1+cu124']]}):
                with self.assertRaisesRegex(RuntimeError, 'record missing'):
                    quick.check(directory, workspace, 'id')
                quick.check(directory, workspace, 'id', record=True)
                quick.check(directory, workspace, 'id')
                with patch.object(quick, 'environment', return_value={'packages': []}):
                    with self.assertRaisesRegex(RuntimeError, 'environment changed'):
                        quick.check(directory, workspace, 'id')
                self.assertEqual((directory / '.wan-fast-verified.json').stat().st_mode & 0o777, 0o600)

    def test_failures_stop_dependent_checks(self):
        for failure in ('mounted', 'gpu', 'environment'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                with patch.object(quick, 'mounted') as mount, patch.object(quick, 'gpu') as gpu, patch.object(quick, 'environment') as env:
                    {'mounted': mount, 'gpu': gpu, 'environment': env}[failure].side_effect = RuntimeError(failure)
                    with self.assertRaisesRegex(RuntimeError, failure):
                        quick.check(Path(tmp), Path(tmp), 'id')
                    if failure == 'mounted':
                        gpu.assert_not_called()
                    if failure != 'environment':
                        env.assert_not_called()

    def test_models_stat_only_and_missing_models(self):
        with tempfile.TemporaryDirectory() as tmp:
            model = Path(tmp) / 'model'
            with self.assertRaises(FileNotFoundError):
                quick.stamp(model)
            model.touch()
            with self.assertRaisesRegex(RuntimeError, 'empty required file'):
                quick.stamp(model)
            model.write_bytes(b'valid fixture')
            with patch.object(Path, 'read_bytes', side_effect=AssertionError('must not hash model')):
                self.assertEqual(quick.stamp(model)[1], 13)

    def test_incompatible_venv_rejected(self):
        with patch.object(quick, 'headers'), patch.object(quick.sys, 'prefix', '/usr'), patch.object(quick.sys, 'base_prefix', '/usr'):
            with self.assertRaisesRegex(RuntimeError, 'existing ComfyUI Python 3.11 venv'):
                quick.environment(Path('/workspace/ComfyUI'))
        with patch.object(quick, 'headers', side_effect=RuntimeError('Python 3.11 required')):
            with self.assertRaisesRegex(RuntimeError, 'Python 3.11'):
                quick.environment(Path('/workspace/ComfyUI'))

    def test_cuda_unavailable(self):
        with patch.object(quick, 'run', return_value='GPU'), patch.object(quick.ctypes, 'CDLL', side_effect=OSError('libcuda missing')):
            with self.assertRaisesRegex(OSError, 'libcuda missing'):
                quick.gpu()
        driver = Mock()
        driver.cuInit.return_value = 100
        with patch.object(quick, 'run', return_value='GPU'), patch.object(quick.ctypes, 'CDLL', return_value=driver):
            with self.assertRaisesRegex(RuntimeError, 'CUDA driver'):
                quick.gpu()

    def test_ports_and_readiness_phases(self):
        self.assertEqual(port_number(8888), 8888)
        with self.assertRaises(ValueError):
            port_number(7777)
        self.assertEqual(server.readiness_phase(OSError('refused'), ''), 'initializing')
        self.assertEqual(server.readiness_phase(OSError('refused'), 'Starting server'), 'running_http_unresponsive')
        self.assertEqual(server.readiness_phase(RuntimeError('Required workflow nodes are not registered: X'), ''), 'missing_required_nodes')
        self.assertEqual(server.readiness_phase(ValueError('invalid json'), ''), 'readiness_check_failed')

    def test_quick_shell_path_does_not_import_or_install(self):
        # Reuse the existing entrypoint control-flow harness.
        from test_scripts import EntryPoints
        fixture = EntryPoints()
        fixture.setUp()
        try:
            result = fixture.run_script('start.sh', '--quick')
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = fixture.log.read_text()
            self.assertIn('verify --quick', calls)
            self.assertIn('--port 8888 --timeout 300', calls)
            self.assertNotIn('check_diffusers', calls)
            for forbidden in ('models ', 'nodes ', 'apt ', 'comfyui ', 'pip install'):
                self.assertNotIn(forbidden, calls)
            (fixture.comfy / 'venv/bin/python').unlink()
            result = fixture.run_script('start.sh', '--quick')
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Python environment not found', result.stdout)
        finally:
            fixture.doCleanups()


class ImageContract(unittest.TestCase):
    def test_image_and_build_contract(self):
        text = (ROOT / 'Dockerfile').read_text()
        self.assertIn('FROM nvidia/cuda:12.4.1-devel-ubuntu22.04', text)
        for package in ('python3.11', 'python3.11-dev', 'python3.11-venv', 'openssh-server', 'tmux', 'ffmpeg', 'build-essential', 'util-linux', 'iproute2'):
            self.assertIn(package, text)
        self.assertIn('WORKDIR /opt/wan-cloud-toolkit', text)
        self.assertIn('tools/check_python_headers.py', text)
        self.assertNotIn('pip install', text)
        self.assertNotIn('bootstrap.sh --with-models', text)
        self.assertIn('EXPOSE 22 8888', text)
        workflow = (ROOT / '.github/workflows/image.yml').read_text()
        self.assertIn('docker run --rm --entrypoint bash', workflow)
        self.assertIn('python3.11 -m venv', workflow)
        self.assertNotIn('docker push', workflow)
        self.assertNotIn(':latest', workflow)

    def test_autostart_keeps_logs_ssh_and_supervisor(self):
        entry = (ROOT / 'docker/entrypoint.sh').read_text()
        self.assertIn('ssh-keygen -A', entry)
        self.assertIn('exec /usr/sbin/sshd -D -e', entry)
        worker = (ROOT / 'docker/autostart.sh').read_text()
        self.assertLess(worker.index('mounted(Path'), worker.index('mkdir -p'))
        self.assertIn('PIPESTATUS', worker)
        self.assertIn('output.log', worker)
        self.assertIn('/status', worker)
        fast = (ROOT / 'fast-start.sh').read_text()
        self.assertIn('start.sh" --quick', fast)
        launch = (ROOT / 'start.sh').read_text()
        self.assertIn('tools/start_comfyui.py', launch)
        self.assertIn('COMFY_LOG_DIR', launch)
        supervisor = (ROOT / 'tools/start_comfyui.py').read_text()
        self.assertIn('COMFY_PERFORMANCE', supervisor)
        self.assertIn('.readiness.jsonl', supervisor)
        for script in (entry, worker, fast):
            self.assertNotIn('apt-get', script)
            self.assertNotIn('pip install', script)
            self.assertNotIn('install/models.sh', script)
