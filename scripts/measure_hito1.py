"""Roundtrip de 1 GiB + dos clientes independientes; picos reales del SO, sin mocks."""
import argparse
from datetime import datetime, timezone
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

from dfsha.client.sdk import Client
from dfsha.common.domain import CHUNK
from generate_certs import generate
from hito1_runtime import Hito1Process
from runtime import ROOT, PROCESS_FLAGS


def memory(pid):
    if os.name == 'nt':
        from ctypes import wintypes as w

        class Counters(ctypes.Structure):
            _fields_ = [('cb', w.DWORD), ('faults', w.DWORD)] + [(name, ctypes.c_size_t) for name in (
                'peak_working_set', 'working_set', 'peak_paged', 'paged', 'peak_nonpaged', 'nonpaged',
                'pagefile', 'peak_pagefile')]
        kernel, psapi = ctypes.WinDLL('kernel32', use_last_error=True), ctypes.WinDLL('psapi', use_last_error=True)
        kernel.OpenProcess.argtypes, kernel.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        kernel.CloseHandle.argtypes = [w.HANDLE]
        psapi.GetProcessMemoryInfo.argtypes = [w.HANDLE, ctypes.POINTER(Counters), w.DWORD]
        handle = kernel.OpenProcess(0x0400 | 0x0010, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            counters = Counters()
            counters.cb = ctypes.sizeof(counters)
            if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
                raise ctypes.WinError(ctypes.get_last_error())
            return dict(peak_resident_bytes=counters.peak_working_set, peak_commit_bytes=counters.peak_pagefile)
        finally:
            kernel.CloseHandle(handle)
    text = Path(f'/proc/{pid}/status').read_text()
    values = {line.split(':')[0]: line.split(':')[1].strip() for line in text.splitlines() if ':' in line}
    return dict(peak_resident_bytes=int(values['VmHWM'].split()[0]) * 1024)


def worker(args):
    directory = args.directory
    source, target = directory / f'input-{args.worker}', directory / f'output-{args.worker}'
    expected = hashlib.sha256()
    with source.open('wb') as stream:
        left = args.bytes
        while left:
            chunk = os.urandom(min(CHUNK, left))
            stream.write(chunk)
            expected.update(chunk)
            left -= len(chunk)
    (directory / f'worker-{args.worker}.ready').touch()
    deadline = time.monotonic() + 120
    while not (directory / 'go').exists():
        if time.monotonic() > deadline:
            raise TimeoutError('Barrera de prueba')
        time.sleep(.1)
    started = time.monotonic()
    client = Client(args.target, directory / 'certs')
    client.login('admin', 'development-password')
    result = client.send(source, f'/client-{args.worker}')
    downloaded = client.receive(f'/client-{args.worker}', target)
    assert downloaded['sha256'] == expected.hexdigest() and downloaded['bytes'] == args.bytes
    client.shutdown()
    record = dict(status='EJECUTADO', pid=os.getpid(), bytes=args.bytes, sha256=expected.hexdigest(),
                  block_size=result.snapshot.block_size_bytes, seconds=round(time.monotonic() - started, 3),
                  **memory(os.getpid()))
    (directory / f'worker-{args.worker}.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=int)
    parser.add_argument('--bytes', type=int)
    parser.add_argument('--target')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--evidence', type=Path, default=ROOT / 'docs/evidencias/etapa3/medicion.json')
    args = parser.parse_args()
    if args.worker is not None:
        return worker(args)
    directory = ROOT / '.runtime/measure-h1' / str(uuid4())
    directory.mkdir(parents=True)
    free = shutil.disk_usage(directory).free
    report = dict(status='PENDIENTE', timestamp=datetime.now(timezone.utc).isoformat(),
        runtime=str(directory), initial_free_bytes=free, block_size_bytes=67108864, clients=3,
        transport_chunk_bytes=CHUNK, admission_units=4, weight_per_64mib_stream=2,
        budgets=dict(client_resident_bytes=268435456, server_resident_bytes=536870912),
        metric='Windows PeakWorkingSetSize / PeakPagefileUsage; Linux VmHWM',
        scope='monolito TLS loopback, no distribución ni benchmark comparativo')
    processes, logs = [], []
    try:
        if free < 5 * 1073741824:
            raise RuntimeError('BLOQUEADO POR ENTORNO: se requieren 5 GiB libres')
        generate(directory / 'certs')
        with Hito1Process(directory / 'server', directory / 'certs', 67108864) as server:
            for index, size in enumerate((1073741824, 67108865, 67108865)):
                log = (directory / f'client-{index}.log').open('wb')
                logs.append(log)
                processes.append(subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(index),
                    '--bytes', str(size), '--target', server.target, '--directory', str(directory)],
                    cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=PROCESS_FLAGS))
            until = time.monotonic() + 120
            while not all((directory / f'worker-{i}.ready').exists() for i in range(3)):
                if time.monotonic() > until or any(p.poll() is not None for p in processes):
                    raise RuntimeError('Cliente no llegó a la barrera; consultar logs runtime')
                time.sleep(.1)
            (directory / 'go').touch()
            until = time.monotonic() + 1200
            while any(p.poll() is None for p in processes):
                report['server_memory'] = memory(server.info['pid'])
                if time.monotonic() > until:
                    raise TimeoutError('Verificación excedió 20 minutos')
                time.sleep(.25)
            report['server_memory'] = memory(server.info['pid'])
            report['server_pid'] = server.info['pid']
            if any(p.returncode for p in processes):
                raise RuntimeError('Roundtrip fallido; consultar logs runtime')
            report['workers'] = [json.loads((directory / f'worker-{i}.json').read_text()) for i in range(3)]
            report['memory_goals_met'] = all(w['peak_resident_bytes'] <= 268435456 for w in report['workers']) and \
                report['server_memory']['peak_resident_bytes'] <= 536870912
            report['status'] = 'EJECUTADO'
    except Exception as exc:
        report.update(status='FALLIDO', error=str(exc))
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)
        for log in logs:
            log.close()
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report), flush=True)
    return 0 if report['status'] == 'EJECUTADO' else 1


if __name__ == '__main__':
    raise SystemExit(main())
