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
import check_image as image_probe
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

    def test_added_node_invalidates_inventory_without_tracking_caches(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'ComfyUI-WanVideoWrapper').mkdir()
            before = quick.node_inventory(root)
            (root / '__pycache__').mkdir()
            self.assertEqual(quick.node_inventory(root), before)
            (root / 'unreviewed-node').mkdir()
            self.assertNotEqual(quick.node_inventory(root), before)

    def test_system_identity_includes_built_package_manifest(self):
        with patch.object(quick, 'digest', side_effect=lambda p: str(p)), patch.object(Path, 'is_file', return_value=True):
            identity = quick.system_identity()
        self.assertEqual(identity['image_packages'], '/etc/wan-cloud-system-packages.txt')
        self.assertIn('libc', identity)

    def test_quick_verification_failure_prevents_supervisor_launch(self):
        from test_scripts import EntryPoints, executable
        fixture = EntryPoints()
        fixture.setUp()
        try:
            executable(fixture.root / 'install/verify.sh', '#!/bin/bash\nexit 17\n')
            result = fixture.run_script('start.sh', '--quick')
            self.assertEqual(result.returncode, 17)
            calls = fixture.log.read_text().splitlines()
            self.assertEqual(len(calls), 1)  # Port/process preflight only.
            self.assertIn('--preflight', calls[0])
        finally:
            fixture.doCleanups()

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


    def test_cpu_image_probe_checks_abi_libraries_without_driver(self):
        with patch.object(image_probe, 'headers'), patch.object(image_probe.sys, 'executable', '/usr/bin/python3.11'), patch.object(image_probe.importlib, 'import_module') as importer, patch.object(image_probe.subprocess, 'run', return_value=Mock(stdout='libc.so found', stderr='')), patch.object(image_probe.ctypes, 'CDLL') as loader, patch.object(Path, 'is_file', return_value=True):
            image_probe.check()
            self.assertIn('ensurepip', [c.args[0] for c in importer.call_args_list])
            self.assertEqual([c.args[0] for c in loader.call_args_list],
                             ['libstdc++.so.6', 'libgomp.so.1', 'libnvrtc.so.12'])

    def test_cpu_probe_rejects_wrong_path_and_missing_shared_libraries(self):
        with patch.object(image_probe, 'headers'), patch.object(image_probe.sys, 'executable', '/usr/local/bin/python3.11'):
            with self.assertRaisesRegex(RuntimeError, 'Expected image interpreter'):
                image_probe.check()
        with patch.object(image_probe, 'headers'), patch.object(image_probe.sys, 'executable', '/usr/bin/python3.11'), patch.object(image_probe.importlib, 'import_module'), patch.object(image_probe.subprocess, 'run', return_value=Mock(stdout='libssl.so => not found', stderr='')):
            with self.assertRaisesRegex(RuntimeError, 'unresolved shared libraries'):
                image_probe.check()

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
