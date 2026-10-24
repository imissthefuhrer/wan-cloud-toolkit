"""Regression tests for shell control flow; no GPU, downloads, or pip installs."""
import hashlib
import http.server
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
PAYLOAD = b"model-weights\n" * 4096


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


class Downloads(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.destination = self.root / "model.safetensors"
        self.ranges = []
        self.interrupt = False
        self.corrupt = False
        self.metadata = True
        self.redirect = False
        self.final_status = 200
        self.head_size = len(PAYLOAD)
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_HEAD(self):
                if fixture.redirect and self.path == "/model":
                    self.send_response(307)
                    self.send_header("Location", "/canonical")
                    self.end_headers()
                    return
                if fixture.redirect and self.path == "/canonical":
                    self.send_response(302)
                    self.send_header("Location", "/artifact")
                else:
                    self.send_response(fixture.final_status)
                if fixture.metadata and self.path != "/artifact":
                    self.send_header("X-Linked-Etag", '"' + hashlib.sha256(PAYLOAD).hexdigest() + '"')
                    self.send_header("X-Linked-Size", str(len(PAYLOAD)))
                self.send_header("Content-Length", str(fixture.head_size))
                self.end_headers()

            def do_GET(self):
                offset = int(self.headers.get("Range", "bytes=0-").split("=")[1].split("-")[0])
                fixture.ranges.append(offset)
                self.send_response(206 if offset else 200)
                if offset:
                    self.send_header("Content-Range", f"bytes {offset}-{len(PAYLOAD)-1}/{len(PAYLOAD)}")
                self.send_header("Content-Length", str(len(PAYLOAD) - offset))
                self.end_headers()
                body = (b"x" * len(PAYLOAD) if fixture.corrupt else PAYLOAD)[offset:]
                if fixture.interrupt:
                    fixture.interrupt = False
                    body = body[:len(body)//2]
                self.wfile.write(body)
                self.close_connection = True

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)
        # Bound wget retries so an intentional interruption returns immediately.
        executable(self.root / "bin/wget", f'#!/bin/bash\nexec {shutil.which("wget")} --tries=1 --timeout=2 "$@"\n')

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def download(self):
        return subprocess.run(
            ["bash", "-c", 'set -euo pipefail; source "$1"; download_model "$2" "$3"',
             "test", str(ROOT / "lib/common.sh"),
             f"http://127.0.0.1:{self.server.server_port}/model", str(self.destination)],
            env={**os.environ, "PATH": f"{self.root}/bin:" + os.environ["PATH"]},
            capture_output=True, text=True, timeout=10)

    def assert_complete(self):
        self.assertEqual(self.destination.read_bytes(), PAYLOAD)
        self.assertFalse(Path(str(self.destination) + ".part").exists())

    def inspect_metadata(self):
        return subprocess.run(
            ["python3", str(ROOT / "tools/model_metadata.py"),
             f"http://127.0.0.1:{self.server.server_port}/model"],
            capture_output=True, text=True, timeout=10)

    def test_metadata_follows_307_and_302_without_get(self):
        self.redirect = True
        result = self.inspect_metadata()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), f"{hashlib.sha256(PAYLOAD).hexdigest()} {len(PAYLOAD)}")
        self.assertEqual(self.ranges, [])

    def test_metadata_rejects_final_error(self):
        self.redirect = True
        self.final_status = 403
        self.assertNotEqual(self.inspect_metadata().returncode, 0)
        self.assertEqual(self.ranges, [])

    def test_metadata_rejects_length_mismatch(self):
        self.head_size = len(PAYLOAD) + 1
        self.assertNotEqual(self.inspect_metadata().returncode, 0)
        self.assertEqual(self.ranges, [])

    def test_fresh_download_and_verified_rerun(self):
        self.assertEqual(self.download().returncode, 0)
        self.assert_complete()
        self.assertEqual(self.download().returncode, 0)
        self.assertEqual(self.ranges, [0])

    def test_interruption_resumes_without_publishing_partial_file(self):
        self.interrupt = True
        self.assertNotEqual(self.download().returncode, 0)
        self.assertFalse(self.destination.exists())
        partial = Path(str(self.destination) + ".part")
        offset = partial.stat().st_size
        self.assertGreater(offset, 0)
        self.assertEqual(self.download().returncode, 0)
        self.assert_complete()
        self.assertEqual(self.ranges, [0, offset])

    def test_legacy_partial_file_is_not_accepted(self):
        self.destination.write_bytes(PAYLOAD[:100])
        self.assertEqual(self.download().returncode, 0)
        self.assert_complete()
        self.assertEqual(self.ranges, [100])

    def test_same_size_corrupt_existing_file_is_replaced(self):
        self.destination.write_bytes(b"x" * len(PAYLOAD))
        self.assertEqual(self.download().returncode, 0)
        self.assert_complete()
        self.assertEqual(self.ranges, [0])

    def test_bad_checksum_is_rejected(self):
        self.corrupt = True
        self.assertNotEqual(self.download().returncode, 0)
        self.assertFalse(self.destination.exists())
        self.assertFalse(Path(str(self.destination) + ".part").exists())

    def test_missing_metadata_fails_without_trusting_existing_file(self):
        self.metadata = False
        self.destination.write_bytes(b"partial")
        self.assertNotEqual(self.download().returncode, 0)
        self.assertEqual(self.destination.read_bytes(), b"partial")
        self.assertEqual(self.ranges, [])


class EntryPoints(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "lib").mkdir()
        shutil.copy(ROOT / "lib/common.sh", self.root / "lib/common.sh")
        shutil.copytree(ROOT / "tools", self.root / "tools")
        shutil.copytree(ROOT / "constraints", self.root / "constraints")
        # Control-flow fixture only; actual supervisor/API behavior has its own tests.
        (self.root / "tools/start_comfyui.py").write_text(
            'import os,sys\nwith open(os.environ["CALL_LOG"],"a") as f: f.write("supervisor " + " ".join(sys.argv[1:]) + "\\n")\n')
        self.log = self.root / "calls"
        self.comfy = self.root / "ComfyUI"
        self.env = {**os.environ, "COMFY_DIR": str(self.comfy), "CALL_LOG": str(self.log)}
        for script in ("bootstrap.sh", "start.sh"):
            shutil.copy(ROOT / script, self.root / script)
        for script in ("apt", "python", "comfyui", "models", "nodes", "verify"):
            executable(self.root / f"install/{script}.sh",
                       f'#!/bin/bash\nprintf "%s\\n" "{script} $*" >> "$CALL_LOG"\n')
        executable(self.comfy / "venv/bin/python",
                   '#!/bin/bash\nprintf "%s\\n" "python $*" >> "$CALL_LOG"\n')

    def run_script(self, script, *args):
        return subprocess.run(["bash", str(self.root / script), *args], env=self.env,
                              capture_output=True, text=True, timeout=5)

    def test_default_bootstrap_checks_basic_installation(self):
        # Static ordering check: never execute bootstrap during preflight tests.
        script = (ROOT / "bootstrap.sh").read_text()
        calls = [script.index(f'"$SCRIPT_DIR/install/{name}.sh"')
                 for name in ("apt", "python", "comfyui", "nodes", "verify", "models")]
        self.assertEqual(calls, sorted(calls))

    def test_models_bootstrap_checks_full_workflow(self):
        script = (ROOT / "bootstrap.sh").read_text()
        self.assertIn('"$SCRIPT_DIR/install/verify.sh" --basic', script)
        self.assertIn('if [[ "$WITH_MODELS" == true ]]; then', script)
        self.assertGreater(script.rindex('"$SCRIPT_DIR/install/verify.sh"'),
                           script.index('"$SCRIPT_DIR/install/models.sh"'))

    def test_start_modes(self):
        for args, verification in [((), "verify --basic"), (("--full",), "verify ")]:
            with self.subTest(args=args):
                self.log.unlink(missing_ok=True)
                self.assertEqual(self.run_script("start.sh", *args).returncode, 0)
                calls = self.log.read_text().splitlines()
                self.assertIn("--port 8888 --preflight", calls[0])
                self.assertIn("tools/check_diffusers.py", calls[1])
                self.assertEqual(calls[2], verification)
                self.assertIn("--port 8888 --timeout 120", calls[3])

    def test_verification_failure_prevents_start(self):
        executable(self.root / "install/verify.sh", "#!/bin/bash\nexit 9\n")
        self.assertEqual(self.run_script("start.sh").returncode, 9)
        calls = self.log.read_text().splitlines()
        self.assertEqual(len(calls), 2)  # Preflight and CPU import check; no startup.

    def test_unknown_start_option_rejected(self):
        self.assertNotEqual(self.run_script("start.sh", "--unknown").returncode, 0)
        self.assertFalse(self.log.exists())


if __name__ == "__main__":
    unittest.main()
