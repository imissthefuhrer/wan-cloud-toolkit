"""Supervise one ComfyUI process, persistent log, and startup/API checks."""
import argparse
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time

from comfy_health import check_port, health, import_failure, port_number
from connect_comfyui import interrupted, stop

WORKFLOW = Path(__file__).resolve().parents[1] / "workflows/Wan22-I2V-Remix.json"


def preflight(directory, port):
    directory = Path(directory).resolve()
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().split(b"\0")
            cwd = (entry / "cwd").resolve(strict=True)
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
        if str(directory / "main.py").encode() in args or (b"main.py" in args and cwd == directory):
            raise RuntimeError(f"Existing ComfyUI process PID {entry.name}; inspect its logs and health before starting another instance")
    check_port(port, "0.0.0.0")


def supervise(directory, port, timeout, log_dir):
    directory = Path(directory).resolve()
    preflight(directory, port)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=time.strftime("comfy-start-%Y%m%dT%H%M%SZ-", time.gmtime()), suffix=".log", dir=log_dir)
    status = Path(filename + ".status")
    print(f"Persistent ComfyUI startup log: {filename}", flush=True)
    try:
        process = subprocess.Popen([str(directory / "venv/bin/python"), "-u", "main.py", "--listen", "0.0.0.0", "--port", str(port)],
                                   cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception:
        os.close(fd)
        raise
    state = {"tail": "", "error": None}

    def capture():
        try:
            with os.fdopen(fd, "w", buffering=1) as log:
                for line in iter(process.stdout.readline, b""):
                    text = line.decode(errors="replace")
                    log.write(text)
                    print(text, end="", flush=True)
                    state["tail"] = (state["tail"] + text)[-65536:]
                    failure = import_failure(state["tail"])
                    if failure:
                        state["error"] = failure
        except Exception as error:
            state["error"] = f"Startup logging failed: {error}"

    reader = threading.Thread(target=capture, daemon=True)
    reader.start()
    ready = False
    result = 1
    try:
        deadline = time.monotonic() + timeout
        last_error = "Waiting for ComfyUI HTTP startup"
        while True:
            if state["error"]:
                raise RuntimeError(state["error"])
            code = process.poll()
            if code is not None:
                reader.join(timeout=5)
                if state["error"]:
                    raise RuntimeError(state["error"])
                if not ready:
                    raise RuntimeError(f"ComfyUI exited before readiness (status {code})")
                result = code
                return result
            if not ready:
                if time.monotonic() >= deadline:
                    raise RuntimeError(f"ComfyUI startup timed out after {timeout}s: {last_error}")
                try:
                    health(port, WORKFLOW, timeout=min(2, max(.1, deadline - time.monotonic())))
                    if state["error"]:
                        raise RuntimeError(state["error"])
                    ready = True
                    print(f"ComfyUI READY on port {port}: all required workflow node types registered", flush=True)
                except Exception as error:
                    last_error = str(error)
            time.sleep(.25)
    finally:
        stop(process)
        reader.join(timeout=5)
        process.stdout.close()
        os.chmod(filename, 0o600)
        status.write_text(f"supervisor_exit={result}\ncomfy_exit={process.returncode}\nready={ready}\n")
        status.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--port", type=port_number, default=8888)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--log-dir", default="/workspace/wan-cloud-logs")
    parser.add_argument("--preflight", action="store_true")
    args = parser.parse_args()
    if not 0 < args.timeout <= 600:
        parser.error("timeout must be greater than zero and at most 600 seconds")
    try:
        if args.preflight:
            preflight(args.directory, args.port)
            return 0
        return supervise(args.directory, args.port, args.timeout, args.log_dir)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"ComfyUI startup failed: {error}. Inspect the persistent startup log; no unrelated service was stopped.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    sys.exit(main())
