"""Run unmodified ComfyUI with a fail-open, nonblocking execution-event tap.

The import hook waits for normal main.py initialization before wrapping server.
No ComfyUI files, execution functions, tensors or CUDA state are modified.
"""
import importlib.abc
import importlib.machinery
import json
import os
from pathlib import Path
import runpy
import socket
import sys
import time

from performance import EVENTS, safe_graph, stamp, warn


def install_tap(server, emit):
    original = server.PromptServer.send_sync

    def send_sync(self, event, data, *args, **kwargs):
        # Preserve original event delivery and its return/error semantics.
        result = original(self, event, data, *args, **kwargs)
        if event in EVENTS and isinstance(data, dict):
            try:
                record = {'type': event, 'utc': stamp(), 'monotonic': time.monotonic()}
                for key in ('prompt_id', 'node', 'nodes', 'exception_type', 'value', 'max'):
                    if key in data:
                        record[key] = data[key]
                if event == 'execution_start':
                    try:
                        running, _ = self.prompt_queue.get_current_queue()
                        for item in running:
                            if item[1] == data.get('prompt_id'):
                                record['graph'] = safe_graph(item[2])
                                if len(item[2]) > 2048:
                                    record['coverage_warning'] = 'submitted graph truncated at 2048 nodes'
                                break
                    except Exception:
                        record['coverage_warning'] = 'submitted graph unavailable at execution start'
                emit(record)
            except Exception:
                warn('event capture failed; generation continues; original console retained')
        return result

    server.PromptServer.send_sync = send_sync


class TapFinder(importlib.abc.MetaPathFinder):
    def __init__(self, emit):
        self.emit = emit

    def find_spec(self, fullname, path=None, target=None):
        if fullname != 'server':
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None:
            return None
        original = spec.loader
        emit = self.emit

        class Loader(importlib.abc.Loader):
            def create_module(self, spec):
                return original.create_module(spec)

            def exec_module(self, module):
                original.exec_module(module)
                try:
                    install_tap(module, emit)
                except Exception:
                    warn('event tap unavailable; original console retained')
        spec.loader = Loader()
        return spec


def main():
    fd = int(sys.argv[1])
    directory = Path(sys.argv[2]).resolve()
    sys.argv = [str(directory / 'main.py'), *sys.argv[3:]]
    sys.path.insert(0, str(directory))
    try:
        sock = socket.socket(fileno=fd)
        sock.setblocking(False)
    except OSError:
        sock = None
        warn('event socket unavailable; ComfyUI continues with original console logging')
    dropped = False
    sequence = 0

    def emit(record):
        nonlocal dropped, sequence
        sequence += 1
        record["sequence"] = sequence
        try:
            payload = json.dumps(record).encode()
            if len(payload) > 60000:
                record.pop('graph', None)
                record['coverage_warning'] = 'graph exceeded event size limit'
                payload = json.dumps(record).encode()
            if sock is not None:
                sock.send(payload)
        except (OSError, ValueError):
            if not dropped:
                warn('event channel unavailable/full; some diagnostics missing; generation continues')
                dropped = True

    sys.meta_path.insert(0, TapFinder(emit))
    runpy.run_path(str(directory / 'main.py'), run_name='__main__')


if __name__ == '__main__':
    main()
