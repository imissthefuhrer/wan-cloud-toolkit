"""CPU-only image contract probe. Does not install packages or require a GPU."""
import ctypes
import importlib
from pathlib import Path
import subprocess
import sys

from check_python_headers import check as headers


def check():
    headers()
    if Path(sys.executable).resolve() != Path('/usr/bin/python3.11'):
        raise RuntimeError('Expected image interpreter /usr/bin/python3.11 for the retained venv')
    for module in ('ssl', 'sqlite3', 'bz2', 'lzma', 'ctypes', 'venv', 'ensurepip'):
        importlib.import_module(module)
    result = subprocess.run(['ldd', sys.executable], capture_output=True, text=True, check=True)
    if 'not found' in result.stdout + result.stderr:
        raise RuntimeError('Image Python has unresolved shared libraries: ' + result.stdout)
    # Driver libcuda is deliberately NOT needed on the CPU builder. The CUDA
    # compiler/runtime libraries and ordinary C++/OpenMP libraries must load.
    for library in ('libstdc++.so.6', 'libgomp.so.1', 'libnvrtc.so.12'):
        ctypes.CDLL(library)
    if not Path('/usr/local/cuda/bin/nvcc').is_file():
        raise RuntimeError('CUDA development compiler missing')
    print('CPU image probe passed: /usr/bin/python3.11, headers, standard extensions, C++/OpenMP/NVRTC')


if __name__ == '__main__':
    check()
