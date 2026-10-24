"""Linux Mint foreground SSH tunnel. Own and clean up only this SSH process."""
import argparse
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

from comfy_health import check_port, health, port_number

WORKFLOW = Path(__file__).resolve().parents[1] / "workflows/Wan22-I2V-Remix.json"


def ssh_arguments(args):
    port_number(args.local_port)
    port_number(args.remote_port)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]*", args.hostname):
        raise ValueError("Supply the current SSH hostname or IPv4 address, without a URL or username")
    if not re.fullmatch(r"[a-zA-Z0-9_][a-zA-Z0-9_.-]*", args.username):
        raise ValueError("Invalid SSH username")
    if not 1 <= args.ssh_port <= 65535:
        raise ValueError("SSH port must be from 1–65535")
    identity = Path(args.identity).expanduser()
    if not identity.is_file():
        raise ValueError("SSH identity file does not exist")
    return ["ssh", "-4", "-N", "-T", "-F", "/dev/null",
            "-o", "ExitOnForwardFailure=yes", "-o", "GatewayPorts=no",
            "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes",
            "-o", "ConnectTimeout=10", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=3", "-o", "ControlMaster=no",
            "-L", f"127.0.0.1:{args.local_port}:127.0.0.1:{args.remote_port}",
            "-p", str(args.ssh_port), "-l", args.username, "-i", str(identity), args.hostname]


def stop(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()


def interrupted(*_):
    raise KeyboardInterrupt


def connect(args):
    command = ssh_arguments(args)
    check_port(args.local_port)
    state = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "wan-cloud-toolkit"
    state.mkdir(parents=True, exist_ok=True)
    fd, logfile = tempfile.mkstemp(prefix=time.strftime("ssh-%Y%m%dT%H%M%SZ-", time.gmtime()), suffix=".log", dir=state)
    print(f"SSH diagnostics: {logfile}", flush=True)
    with os.fdopen(fd, "w") as log:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=log)
        try:
            deadline = time.monotonic() + args.timeout
            error = "No HTTP response yet"
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"SSH exited with status {process.returncode}; inspect {logfile} for authentication, host-key, or forwarding errors")
                try:
                    health(args.local_port, WORKFLOW, timeout=min(2, max(.1, deadline - time.monotonic())))
                    break
                except Exception as failure:
                    error = str(failure)
                time.sleep(.25)
            else:
                raise RuntimeError(f"Tunnel health timed out after {args.timeout}s: {error}. Check remote start.sh logs, port {args.remote_port}, and required nodes; SSH diagnostics: {logfile}")
            if process.poll() is not None:
                raise RuntimeError("SSH closed during health verification")
            url = f"http://127.0.0.1:{args.local_port}/"
            print(f"ComfyUI and workflow nodes verified: {url}\nKeep this terminal open; Ctrl-C closes this tunnel.", flush=True)
            subprocess.run(["xdg-open", url], check=True, timeout=15)
            result = process.wait()
            if result:
                raise RuntimeError(f"SSH disconnected with status {result}; inspect {logfile}")
        finally:
            stop(process)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("hostname")
    parser.add_argument("ssh_port", type=int)
    parser.add_argument("username")
    parser.add_argument("identity")
    parser.add_argument("--local-port", type=port_number, default=8888)
    parser.add_argument("--remote-port", type=port_number, default=8888)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    if not 0 < args.timeout <= 600:
        parser.error("timeout must be greater than zero and at most 600 seconds")
    try:
        connect(args)
    except KeyboardInterrupt:
        return 130
    except Exception as error:
        print(f"Connection failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, interrupted)
    sys.exit(main())
