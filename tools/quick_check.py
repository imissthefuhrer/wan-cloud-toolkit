"""Bounded startup checks; no dependency installs, model reads, or heavy imports."""
import argparse
import ctypes
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from check_python_headers import check as headers
from comfy_health import port_number

ROOT = Path(__file__).resolve().parents[1]
NODES = ('ComfyUI-WanVideoWrapper', 'ComfyUI-KJNodes', 'ComfyUI-Easy-Use',
         'ComfyUI-Custom-Scripts', 'ComfyUI-Frame-Interpolation')


def run(*args):
    return subprocess.check_output(args, text=True, stderr=subprocess.PIPE, timeout=30).strip()


def mounted(workspace, identity):
    """An exact mount and operator-enrolled marker are both required."""
    info = json.loads(run('findmnt', '--json', '--mountpoint', str(workspace),
                          '--output', 'TARGET,FSTYPE'))['filesystems']
    if len(info) != 1 or info[0]['target'] != str(workspace) or info[0]['fstype'] in ('overlay', 'tmpfs', 'ramfs'):
        raise RuntimeError('Expected persistent network volume mounted exactly at /workspace')
    if not identity or (workspace / '.wan-volume-id').read_text().strip() != identity:
        raise RuntimeError('WAN_VOLUME_ID does not match the enrolled persistent volume')


def gpu():
    print(run('nvidia-smi', '--query-gpu=name,driver_version,memory.total,memory.free,utilization.gpu', '--format=csv,noheader'))
    cuda = ctypes.CDLL('libcuda.so.1')
    count = ctypes.c_int()
    if cuda.cuInit(0) != 0 or cuda.cuDeviceGetCount(ctypes.byref(count)) != 0 or count.value < 1:
        raise RuntimeError('CUDA driver initialization failed or no GPU is accessible')
    for index in range(count.value):
        major, minor = ctypes.c_int(), ctypes.c_int()
        if cuda.cuDeviceComputeCapability(ctypes.byref(major), ctypes.byref(minor), index) != 0:
            raise RuntimeError('Cannot query CUDA compute capability')
        if major.value >= 10:
            raise RuntimeError('Blackwell/newer GPUs are not validated with the pinned Torch 2.4.1 stack')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def stamp(path):
    s = path.stat()
    if not path.is_file() or s.st_size <= 0:
        raise RuntimeError(f'Missing or empty required file: {path}')
    return [str(path.resolve()), s.st_size, s.st_mtime_ns]


def system_identity():
    # Captured at build time, not by running dpkg on every startup.
    manifest = Path('/etc/wan-cloud-system-packages.txt')
    return dict(os_release=digest(Path('/etc/os-release')),
                image_packages=digest(manifest) if manifest.is_file() else None,
                libc=os.confstr('CS_GNU_LIBC_VERSION'))


def node_inventory(node_root):
    # One directory level only. Runtime bytecode caches do not invalidate checks.
    return sorted(p.name for p in node_root.iterdir()
                  if p.name != '__pycache__' and not p.name.startswith('.'))


def environment(directory):
    headers()
    if sys.prefix == sys.base_prefix or Path(sys.prefix).resolve() != (directory / 'venv').resolve():
        raise RuntimeError('Must run with the existing ComfyUI Python 3.11 venv; no replacement is attempted')
    # Enumerate only installed distribution metadata; never import Torch/diffusers/CuPy.
    packages = sorted((d.metadata['Name'], d.version) for d in md.distributions())
    import yaml  # Small parser already required by the installed toolkit nodes.
    node_root = directory / 'custom_nodes'
    config = node_root / 'ComfyUI-Frame-Interpolation/config.yaml'
    rife = node_root / 'ComfyUI-Frame-Interpolation' / yaml.safe_load(config.read_text())['ckpts_path'] / 'rife/rife47.pth'
    models = [
        'diffusion_models/Wan2.2_Remix_NSFW_i2v_14b_high_lighting_v2.0.safetensors',
        'diffusion_models/Wan2.2_Remix_NSFW_i2v_14b_low_lighting_v2.0.safetensors',
        'text_encoders/nsfw_wan_umt5-xxl_fp8_scaled.safetensors',
        'loras/Wan2.2-Lightning_I2V-A14B-4steps-lora_HIGH_fp16.safetensors',
        'loras/Wan2.2-Lightning_I2V-A14B-4steps-lora_LOW_fp16.safetensors',
        'vae/wan_2.1_vae.safetensors']
    repos = [directory] + [node_root / n for n in NODES]
    return dict(schema=2, directory=str(directory), packages=packages,
                system=system_identity(), nodes=node_inventory(node_root),
                python=[sys.version, sys.base_prefix, stamp(Path(sys.executable).resolve())],
                revisions=[run('git', '-C', str(p), 'rev-parse', 'HEAD') for p in repos],
                tracked_edits=[hashlib.sha256(run('git', '-C', str(p), 'diff', '--no-ext-diff', 'HEAD', '--').encode()).hexdigest() for p in repos],
                toolkit=[digest(p) for p in sorted((ROOT / 'tools').glob('*.py'))],
                launchers=[digest(ROOT / p) for p in ('start.sh', 'fast-start.sh', 'install/verify.sh',
                           'docker/autostart.sh', 'docker/entrypoint.sh')],
                config=[digest(config), digest(directory / 'wan-cloud-constraints.txt'),
                        digest(ROOT / 'workflows/Wan22-I2V-Remix.json'),
                        digest(ROOT / 'constraints/wan-python.txt')],
                main=stamp(directory / 'main.py'),
                models=[stamp(directory / 'models' / p) for p in models] + [stamp(rife)])


def check(directory, workspace, identity, record=False):
    mounted(workspace, identity)
    directory = directory.resolve()
    directory.relative_to(workspace.resolve())
    port_number(os.environ.get('COMFY_PORT', '8888'))
    gpu()
    current = json.loads(json.dumps(environment(directory)))
    receipt = directory / '.wan-fast-verified.json'
    if record:
        fd, name = tempfile.mkstemp(prefix='.wan-fast-', dir=directory)
        try:
            with os.fdopen(fd, 'w') as output:
                json.dump(current, output, sort_keys=True)
            os.replace(name, receipt)
        finally:
            if Path(name).exists():
                Path(name).unlink()
        print(f'Full verification record saved: {receipt}')
    else:
        if not receipt.is_file() or json.loads(receipt.read_text()) != current:
            raise RuntimeError('Full verification record missing or environment changed. Run install/verify.sh --record-fast after maintenance/model integrity checks')
        print('Quick checks passed; full verification record matches (models checked by stat only)')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--record', action='store_true', help='Internal: only after successful full verification')
    args = parser.parse_args()
    try:
        check(Path(os.environ.get('COMFY_DIR', '/workspace/ComfyUI')),
              Path('/workspace'), os.environ.get('WAN_VOLUME_ID', ''), args.record)
    except Exception as error:
        print(f'Quick verification failed: {error}. No files were repaired or installed.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
