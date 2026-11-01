"""Regenerate synthetic documentation fixtures; never contacts ComfyUI or a GPU."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from performance import Recorder, atomic, markdown, safe_graph
from test_performance import event, graph

DEST = Path(__file__).resolve().parents[1] / 'docs/examples/performance'


def main():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        console = root / 'synthetic-console.txt'
        console.write_text('SYNTHETIC console fixture; no GPU used.\n')
        recorder = Recorder(root / 'reports', console, 'SYNTHETIC')
        for number, (width, seconds, vram) in enumerate(((720, 100, 23000), (832, 130, 27000), (960, 180, 32000)), 1):
            pid = f'SYNTHETIC-{number}'
            recorder.event(event('execution_start', 0, pid, graph=safe_graph(graph())))
            recorder.active['synthetic'] = True
            for node, start in [('3', 1), ('4', 6), ('13', seconds * .4), ('14', seconds * .45), ('8', seconds * .8), ('6', seconds * .9), ('7', seconds * .95), ('15', seconds * .98)]:
                recorder.event(event('executing', start, pid, node=node))
                if node in ('4', '14'):
                    with console.open('a') as stream:
                        stream.write(f'Sampling 113 frames at {width}x480 with 4 steps\n')
                    recorder.console_lines()
            recorder.sampled({'utc': '2026-01-01T00:00:05Z', 'monotonic': 5,
                              'synthetic': True, 'gpus': [{'uuid': 'GPU-SYNTHETIC', 'name': 'Simulated GPU', 'memory.used': vram, 'memory.total': 49152, 'utilization.gpu': 95}]})
            recorder.event(event('execution_success', seconds, pid))
            source = next(p.parent for p in (root / 'reports').glob('*/report.json') if json.loads(p.read_text())['prompt_id'] == pid)
            destination = DEST / pid
            destination.mkdir(parents=True, exist_ok=True)
            report = json.loads((source / 'report.json').read_text())
            report['console']['path'] = '../synthetic-console.txt'
            report['ended_utc'] = '2026-01-01T00:03:00Z'
            atomic(destination / 'report.json', json.dumps(report, indent=2) + '\n')
            atomic(destination / 'report.md', markdown(report))
            (destination / 'samples.jsonl').write_bytes((source / 'samples.jsonl').read_bytes())
        (DEST / 'synthetic-console.txt').write_bytes(console.read_bytes())


if __name__ == '__main__':
    main()
