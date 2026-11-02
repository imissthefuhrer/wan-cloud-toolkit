"""Supervise one ComfyUI process, persistent log, and startup/API checks."""
import argparse
import os
from pathlib import Path
import signal
import socket
import json
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
        runner_path = str(Path(__file__).with_name("comfy_performance_runner.py")).encode()
        toolkit_runner = runner_path in args and str(directory).encode() in args
        if toolkit_runner or str(directory / "main.py").encode() in args or (b"main.py" in args and cwd == directory):
            raise RuntimeError(f"Existing ComfyUI process PID {entry.name}; inspect its logs and health before starting another instance")
    check_port(port, "0.0.0.0")


def supervise(directory, port, timeout, log_dir):
    directory = Path(directory).resolve()
    preflight(directory, port)
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    fd, filename = tempfile.mkstemp(prefix=time.strftime("comfy-start-%Y%m%dT%H%M%SZ-", time.gmtime()), suffix=".log", dir=log_dir)
    status = Path(filename + ".status")
    print(f"Persistent ComfyUI startup log: {filename}", flush=True)
    monitor = None
    sender = receiver = None
    monitor_log = None
    diagnostics = os.environ.get("COMFY_PERFORMANCE", "1") != "0"
    command = [str(directory / "venv/bin/python"), "-u", "main.py", "--listen", "0.0.0.0", "--port", str(port)]
    pass_fds = ()
    monitor_command = None
    if diagnostics:
        try:
            interval = float(os.environ.get("COMFY_PERFORMANCE_INTERVAL", "5"))
            if not 2 <= interval <= 300:
                raise ValueError("interval must be between 2 and 300 seconds")
            sender, receiver = socket.socketpair(socket.AF_UNIX, socket.SOCK_DGRAM)
            sender.setblocking(False)
            root = Path(log_dir) / "performance"
            root.mkdir(mode=0o700, exist_ok=True)
            monitor_fd, monitor_name = tempfile.mkstemp(prefix="monitor-", suffix=".log", dir=root)
            monitor_log = os.fdopen(monitor_fd, "a")
            monitor_command = [sys.executable, str(Path(__file__).with_name("performance.py")), "monitor",
                               "--root", str(root), "--console", filename, "--session", Path(filename).name,
                               "--fd", str(receiver.fileno()), "--interval", str(interval),
                               "--directory", str(directory), "--port", str(port)]
            monitor = subprocess.Popen(monitor_command, pass_fds=(receiver.fileno(),),
                                       stdout=monitor_log, stderr=monitor_log)
            command = [str(directory / "venv/bin/python"), "-u", str(Path(__file__).with_name("comfy_performance_runner.py")),
                       str(sender.fileno()), str(directory), "--listen", "0.0.0.0", "--port", str(port)]
            pass_fds = (sender.fileno(),)
            print(f"Automatic performance reports: {root}; monitor log: {monitor_name}", flush=True)
        except Exception as error:
            command = [str(directory / "venv/bin/python"), "-u", "main.py", "--listen", "0.0.0.0", "--port", str(port)]
            pass_fds = ()
            print(f"Performance diagnostics warning: setup failed ({type(error).__name__}); ComfyUI continues with console logging", file=sys.stderr)
    try:
        process = subprocess.Popen(command, cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, pass_fds=pass_fds)
    except Exception:
        os.close(fd)
        if monitor is not None:
            monitor.terminate()
            monitor.wait(timeout=3)
        for channel in (sender, receiver):
            if channel is not None:
                channel.close()
        if monitor_log is not None:
            monitor_log.close()
        raise
    def notify(value):
        if sender is not None:
            try:
                sender.send(json.dumps(value).encode())
            except Exception:
                print("Performance diagnostics warning: event channel failed; original console retained", file=sys.stderr)

    notify({"type": "pid", "pid": process.pid})
    monitor_restarts = 0
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
            if monitor is not None and monitor.poll() is not None:
                if monitor_restarts < 3:
                    monitor_restarts += 1
                    try:
                        monitor = subprocess.Popen(monitor_command, pass_fds=(receiver.fileno(),), stdout=monitor_log, stderr=monitor_log)
                        notify({"type": "pid", "pid": process.pid})
                        print("Performance diagnostics warning: restarting failed monitor; sample coverage may be incomplete", file=sys.stderr)
                    except Exception:
                        monitor = None
                else:
                    print("Performance diagnostics warning: monitor failed repeatedly; console logging continues", file=sys.stderr)
                    monitor = None
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
        notify({"type": "shutdown"})
        if monitor is not None:
            try:
                monitor.wait(timeout=6)
            except Exception:
                try:
                    monitor.terminate()
                    monitor.wait(timeout=2)
                except Exception:
                    print("Performance diagnostics warning: monitor cleanup failed; partial journals retained", file=sys.stderr)
        for channel in (sender, receiver):
            if channel is not None:
                channel.close()
        if monitor_log is not None:
            monitor_log.close()
        os.chmod(filename, 0o600)
        status_fd = os.open(status, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(status_fd, "w") as output:
            output.write(f"supervisor_exit={result}\ncomfy_exit={process.returncode}\nready={ready}\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True)
    parser.add_argument("--port", type=port_number, default=8888)
    parser.add_argument("--timeout", type=float, default=300)
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
