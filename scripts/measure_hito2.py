"""512 MiB con tres clientes, un control y tres DN: hashes, tráfico útil y picos del SO."""
import argparse
from datetime import datetime, timezone
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
from dfsha.common.domain import CHUNK, asdict
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl
from hito2_runtime import Cluster
from measure_hito1 import memory
from runtime import ROOT, PROCESS_FLAGS, wait_until


def worker(args):
    source, target = args.directory / f'input-{args.worker}', args.directory / f'output-{args.worker}'
    expected = hashlib.sha256()
    with source.open('wb') as stream:
        left = args.bytes
        while left:
            chunk = os.urandom(min(CHUNK, left))
            stream.write(chunk)
            expected.update(chunk)
            left -= len(chunk)
    (args.directory / f'ready-{args.worker}').touch()
    wait_until(lambda: (args.directory / 'go').exists(), seconds=120)
    start = time.monotonic()
    client = Client(args.target, args.directory / 'client-trust')
    try:
        client.login('admin', 'development-password')
        result = client.send(source, f'/worker-{args.worker}')
        downloaded = client.receive(f'/worker-{args.worker}', target)
        assert downloaded['bytes'] == args.bytes and downloaded['sha256'] == expected.hexdigest()
        report = dict(status='EJECUTADO', pid=os.getpid(), bytes=args.bytes, sha256=expected.hexdigest(),
            downloaded_sha256=downloaded['sha256'], seconds=round(time.monotonic()-start, 3),
            block_size_bytes=result.snapshot.block_size_bytes, traffic=client.traffic, **memory(os.getpid()))
        (args.directory / f'worker-{args.worker}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    finally:
        client.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--worker', type=int)
    parser.add_argument('--bytes', type=int, default=536870912)
    parser.add_argument('--target')
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--block-size', type=int, choices=(4194304, 67108864, 134217728), default=67108864)
    parser.add_argument('--evidence', type=Path, default=ROOT / 'docs/evidencias/etapa4/measurement.json')
    args = parser.parse_args()
    if args.worker is not None:
        return worker(args)
    directory = ROOT / '.runtime/measure-h2' / str(uuid4())
    report = dict(status='PENDIENTE', timestamp=datetime.now(timezone.utc).isoformat(), runtime=str(directory),
        block_size_bytes=args.block_size, chunk_bytes=CHUNK, clients=3, replicas=1, durable_acks=1,
        metric='Windows PeakWorkingSetSize/PeakPagefileUsage; Linux VmHWM', scope='TLS/mTLS loopback; un solo host')
    processes, logs = [], []
    try:
        if shutil.disk_usage(ROOT).free < args.bytes*5 + 1073741824:
            raise RuntimeError('BLOQUEADO POR ENTORNO: espacio insuficiente para datos aislados de prueba')
        with Cluster(directory, block_size=args.block_size) as app:
            for index, size in enumerate((args.bytes, 134217729, 134217729)):
                log = (directory / f'client-{index}.log').open('wb')
                logs.append(log)
                processes.append(subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker', str(index),
                    '--bytes', str(size), '--target', app.target, '--directory', str(directory)], cwd=ROOT,
                    stdout=log, stderr=subprocess.STDOUT, creationflags=PROCESS_FLAGS))
            wait_until(lambda: all((directory / f'ready-{i}').exists() for i in range(3)), seconds=120)
            (directory / 'go').touch()
            wait_until(lambda: all(p.poll() is not None for p in processes), seconds=1200)
            if any(p.returncode for p in processes):
                raise RuntimeError('Roundtrip falló: consultar logs privados en runtime')
            workers = [json.loads((directory / f'worker-{i}.json').read_text()) for i in range(3)]
            report['workers'] = workers
            client = app.client()
            try:
                expected_write = sum(w['bytes'] for w in workers)
                status = wait_until(lambda: (value if sum(x.client_write_bytes for x in value.nodes) == expected_write and
                    sum(x.client_read_bytes for x in value.nodes) == expected_write else None)
                    if (value := app.statuses(client)) else None, seconds=15)
                report['nodes'] = [asdict(x) for x in status.nodes]
                report['control_content_bytes'] = status.control_content_bytes
                handle = client.open_read('/worker-0')
                plan = client.call(client.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
                    snapshot=handle.snapshot, offset=0, length=handle.snapshot.size_bytes, page=c.PageRequest(limit=64)))
                report['primary_file_blocks'] = [dict(index=b.block.block_index, bytes=b.block.size_bytes,
                    node_id=b.locations[0].node_id) for b in plan.blocks]
                client.close(handle)
            finally:
                client.shutdown()
            report['control_memory'] = dict(pid=app.control.info['pid'], **memory(app.control.info['pid']))
            report['datanode_memory'] = [dict(node_id=node.info['node_id'], pid=node.info['pid'], **memory(node.info['pid'])) for node in app.nodes[:3]]
            assert len({b['node_id'] for b in report['primary_file_blocks']}) >= 2
            assert sum(x['client_write_bytes'] for x in workers[0]['traffic'].values()) == args.bytes
            assert sum(x['client_read_bytes'] for x in workers[0]['traffic'].values()) == args.bytes
            assert not list((app.control.directory / 'blocks').rglob('*.blk'))
            report['memory_goals_met'] = all(x['peak_resident_bytes'] <= 268435456 for x in workers) and \
                all(x['peak_resident_bytes'] <= 536870912 for x in [report['control_memory']] + report['datanode_memory'])
            report['status'] = 'EJECUTADO'
    except BaseException as exc:
        report.update(status='FALLIDO', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                p.wait(timeout=10)
        for log in logs:
            log.close()
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(args.evidence), memory_goals_met=report['memory_goals_met'])))


if __name__ == '__main__':
    main()
