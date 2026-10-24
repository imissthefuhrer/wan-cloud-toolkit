"""No RunPod/SSH/GPU needed: loopback HTTP fixtures and owned-process mocks."""
import argparse
import http.server
import io
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import comfy_health as api
import connect_comfyui as client
import start_comfyui as server
import check_diffusers as dependencies


class Health(unittest.TestCase):
    def setUp(self):
        self.info = {n: {} for n in api.required_nodes(client.WORKFLOW)}
        self.stats = {"system": {}, "devices": []}
        self.status = 200
        self.invalid = False
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                self.send_response(fixture.status)
                self.end_headers()
                body = fixture.stats if self.path == "/system_stats" else fixture.info
                self.wfile.write(b"not json" if fixture.invalid else json.dumps(body).encode())

        self.http = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def health(self):
        api.health(self.http.server_port, client.WORKFLOW, timeout=.5)

    def test_http_ready_and_all_nodes_registered(self):
        self.health()

    def test_missing_wan_node_is_failure(self):
        del self.info["WanVideoModelLoader"]
        with self.assertRaisesRegex(RuntimeError, "WanVideoModelLoader"):
            self.health()

    def test_wrong_http_service_is_failure(self):
        self.stats = {"code-server": True}
        with self.assertRaisesRegex(RuntimeError, "recognizable ComfyUI"):
            self.health()

    def test_http_error_is_failure(self):
        self.status = 503
        with self.assertRaises(Exception):
            self.health()

    def test_invalid_json_is_failure(self):
        self.invalid = True
        with self.assertRaises(ValueError):
            self.health()

    def test_occupied_local_and_server_ports_fail(self):
        with self.assertRaisesRegex(RuntimeError, "occupied"):
            api.check_port(self.http.server_port)
        with self.assertRaisesRegex(RuntimeError, "occupied"):
            server.preflight(Path(tempfile.gettempdir()) / "nonexistent-comfy", self.http.server_port)

    def test_unreachable_http_is_failure(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
            with self.assertRaises(Exception):
                api.health(port, client.WORKFLOW, timeout=.1)


class Tunnel(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.key = Path(self.tmp.name) / "identity with spaces"
        self.key.write_text("fixture placeholder")
        self.args = argparse.Namespace(hostname="current-pod.example", ssh_port=12345,
                                       username="root", identity=str(self.key), local_port=8888,
                                       remote_port=8888, timeout=.01)
        self.process = Mock()
        self.process.returncode = None
        self.process.poll.side_effect = lambda: self.process.returncode

        def wait(timeout=None):
            self.process.returncode = 0
            return 0
        self.process.wait.side_effect = wait
        self.patchers = [patch.object(client, "check_port"),
                         patch.object(client.subprocess, "Popen", return_value=self.process),
                         patch.object(client.subprocess, "run"),
                         patch.dict(client.os.environ, {"XDG_STATE_HOME": self.tmp.name})]
        self.mocks = [p.start() for p in self.patchers]
        for p in self.patchers:
            self.addCleanup(p.stop)

    def test_current_connection_arguments_ipv4_loopback_and_failure_option(self):
        args = client.ssh_arguments(self.args)
        self.assertIn("-4", args)
        self.assertIn("ExitOnForwardFailure=yes", args)
        self.assertIn("StrictHostKeyChecking=yes", args)
        self.assertEqual(args[args.index("-L") + 1], "127.0.0.1:8888:127.0.0.1:8888")
        self.assertEqual(args[args.index("-p") + 1], "12345")
        self.assertEqual(args[args.index("-i") + 1], str(self.key))
        self.assertEqual(args[-1], self.args.hostname)

    def test_occupied_port_never_starts_ssh_or_browser(self):
        self.mocks[0].side_effect = RuntimeError("occupied")
        with self.assertRaisesRegex(RuntimeError, "occupied"):
            client.connect(self.args)
        self.mocks[1].assert_not_called()
        self.mocks[2].assert_not_called()

    def test_only_open_browser_after_health_success(self):
        order = []
        self.mocks[2].side_effect = lambda *a, **k: order.append("browser")
        with patch.object(client, "health", side_effect=lambda *a, **k: order.append("health")):
            client.connect(self.args)
        self.assertEqual(order, ["health", "browser"])
        self.assertEqual(self.mocks[2].call_args.args[0], ["xdg-open", "http://127.0.0.1:8888/"])

    def test_health_timeout_cleans_owned_ssh_without_browser(self):
        with patch.object(client, "health", side_effect=RuntimeError("missing nodes")):
            with self.assertRaisesRegex(RuntimeError, "timed out.*missing nodes"):
                client.connect(self.args)
        self.process.terminate.assert_called_once()
        self.mocks[2].assert_not_called()

    def test_ssh_exit_never_opens_browser(self):
        self.process.returncode = 255
        with self.assertRaisesRegex(RuntimeError, "255"):
            client.connect(self.args)
        self.mocks[2].assert_not_called()

    def test_browser_failure_cleans_owned_ssh(self):
        self.mocks[2].side_effect = subprocess.CalledProcessError(1, "xdg-open")
        with patch.object(client, "health"):
            with self.assertRaises(subprocess.CalledProcessError):
                client.connect(self.args)
        self.process.terminate.assert_called_once()

    def test_reserved_ports_and_bad_host_are_rejected(self):
        for port in (0, 7777, 65536):
            with self.assertRaises(ValueError):
                api.port_number(port)
        self.args.hostname = "-oProxyCommand=evil"
        with self.assertRaises(ValueError):
            client.ssh_arguments(self.args)


class Startup(unittest.TestCase):
    def test_real_supervisor_against_local_fake_comfyui(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "venv/bin").mkdir(parents=True)
            (directory / "venv/bin/python").symlink_to(sys.executable)
            (directory / "nodes.json").write_text(json.dumps({n: {} for n in api.required_nodes(client.WORKFLOW)}))
            (directory / "main.py").write_text('''import http.server,json,sys,threading
assert sys.argv[1:3] == ["--listen", "0.0.0.0"]
info=json.load(open("nodes.json"))
class Handler(http.server.BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def do_GET(self):
  self.send_response(200); self.end_headers()
  self.wfile.write(json.dumps({"system":{},"devices":[]} if self.path=="/system_stats" else info).encode())
server=http.server.ThreadingHTTPServer(("127.0.0.1",int(sys.argv[4])),Handler)
threading.Timer(2,server.shutdown).start()
print("Fake ComfyUI serving",flush=True)
server.serve_forever(); server.server_close()
''')
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            result = subprocess.run([sys.executable, "-B", str(Path(server.__file__)),
                                     "--directory", tmp, "--port", str(port),
                                     "--timeout", "5", "--log-dir", str(directory / "logs")],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("ComfyUI READY", result.stdout)
            status = next((directory / "logs").glob("*.status")).read_text()
            self.assertIn("ready=True", status)
            self.assertIn("comfy_exit=0", status)

    def test_specific_accelerator_and_generic_import_failures(self):
        text = "Cannot import custom_nodes/ComfyUI-WanVideoWrapper: module 'torch' has no attribute 'accelerator'"
        self.assertIn("diffusers==0.33.1", api.import_failure(text))
        self.assertIn("Custom-node import", api.import_failure("(IMPORT FAILED): /workspace/ComfyUI/custom_nodes/foo"))
        self.assertIsNone(api.import_failure("all custom nodes imported"))

    def test_existing_comfy_process_detected_without_killing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "main.py").write_text("import time; time.sleep(10)")
            process = subprocess.Popen([sys.executable, "main.py"], cwd=tmp)
            try:
                with self.assertRaisesRegex(RuntimeError, "Existing ComfyUI"):
                    server.preflight(tmp, 8888)
                self.assertIsNone(process.poll())
            finally:
                client.stop(process)

    def test_lazy_diffusers_import_accelerator_failure_is_reported(self):
        with patch.object(sys, "stderr", new_callable=io.StringIO) as output:
            with patch.object(sys, "argv", ["check_diffusers.py"]), patch.object(dependencies, "check_versions"), patch.object(dependencies.importlib, "import_module", side_effect=AttributeError("module 'torch' has no attribute 'accelerator'")):
                self.assertEqual(dependencies.main(), 1)
                self.assertIn("diffusers==0.33.1", output.getvalue())

    def test_diffusers_check_exercises_lazy_scheduler_symbols(self):
        schedulers = Mock()
        with patch.object(dependencies.importlib, "import_module", return_value=schedulers) as importer:
            dependencies.check()
        modules = [c.args[0] for c in importer.call_args_list]
        self.assertIn("diffusers.models.transformers.transformer_wan", modules)
        self.assertIn("diffusers.loaders", modules)
        self.assertIn("diffusers.schedulers", modules)
        self.assertIn("diffusers.utils.torch_utils", modules)

    def test_supervisor_startup_exit_is_failure_and_status_is_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = Mock(stdout=io.BytesIO(b"(IMPORT FAILED): custom_nodes/ComfyUI-WanVideoWrapper\n"), returncode=1)
            process.poll.return_value = 1
            with patch.object(server, "preflight"), patch.object(server.subprocess, "Popen", return_value=process):
                with self.assertRaisesRegex(RuntimeError, "import failed"):
                    server.supervise(tmp, 8888, .1, tmp)
            self.assertEqual(len(list(Path(tmp).glob("*.status"))), 1)

    def test_supervisor_ready_requires_api_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = Mock(stdout=io.BytesIO(b"Starting server\n"), returncode=0)
            process.poll.side_effect = [None, 0, 0]
            with patch.object(server, "preflight"), patch.object(server.subprocess, "Popen", return_value=process), patch.object(server, "health") as health:
                self.assertEqual(server.supervise(tmp, 8888, 1, tmp), 0)
            health.assert_called_once()
            status = next(Path(tmp).glob("*.status")).read_text()
            self.assertIn("ready=True", status)

    def test_supervisor_http_timeout_stops_only_owned_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            process = Mock(stdout=io.BytesIO(b"Starting server\n"), returncode=-15)
            process.poll.return_value = None
            with patch.object(server, "preflight"), patch.object(server.subprocess, "Popen", return_value=process), patch.object(server, "health", side_effect=RuntimeError("missing nodes")):
                with self.assertRaisesRegex(RuntimeError, "timed out.*missing nodes"):
                    server.supervise(tmp, 8888, .01, tmp)
            process.terminate.assert_called_once()
