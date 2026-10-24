"""Loopback HTTP checks shared by server startup and the SSH client."""
import json
from pathlib import Path
import re
import socket
import urllib.request


def port_number(value):
    value = int(value)
    if not 1 <= value <= 65535 or value == 7777:
        raise ValueError("Use a port from 1–65535 other than code-server's reserved 7777")
    return value


def check_port(port, host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port_number(port)))
        except OSError as error:
            raise RuntimeError(f"Port {host}:{port} is occupied; leave its process alone and select an explicit free port") from error


def required_nodes(workflow):
    return {n["type"] for n in json.loads(Path(workflow).read_text())["nodes"]}


def health(port, workflow, timeout=2):
    # Avoid HTTP_PROXY/ALL_PROXY for localhost, including on the Mint client.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    result = {}
    for endpoint in ("system_stats", "object_info"):
        with opener.open(f"http://127.0.0.1:{port_number(port)}/{endpoint}", timeout=timeout) as response:
            if response.status != 200:
                raise RuntimeError(f"ComfyUI /{endpoint} returned HTTP {response.status}")
            raw = response.read(16 * 1024 * 1024 + 1)
            if len(raw) > 16 * 1024 * 1024:
                raise RuntimeError("ComfyUI API response exceeded 16 MiB")
            result[endpoint] = json.loads(raw)
    stats = result["system_stats"]
    if not isinstance(stats, dict) or not isinstance(stats.get("system"), dict) or not isinstance(stats.get("devices"), list):
        raise RuntimeError("HTTP service is not a recognizable ComfyUI /system_stats API")
    info = result["object_info"]
    if not isinstance(info, dict):
        raise RuntimeError("ComfyUI /object_info is not an object")
    missing = required_nodes(workflow) - info.keys()
    if missing:
        raise RuntimeError("Required workflow nodes are not registered: " + ", ".join(sorted(missing)))


def import_failure(text):
    if re.search(r"torch.*(?:has no attribute [\"']accelerator|torch\.accelerator)|No module named [\"']torch\.accelerator", text, re.I):
        return "WanVideoWrapper/dependency torch.accelerator failure: preserve Torch 2.4.1+cu124; review the diffusers==0.33.1 compatibility repair in README.md and retain the traceback"
    if re.search(r"IMPORT FAILED|Cannot import .*(?:custom_nodes|custom node)|failed to import .*(?:custom_nodes|WanVideoWrapper)", text, re.I):
        return "Custom-node import failed; inspect the persistent startup log"
    return None
