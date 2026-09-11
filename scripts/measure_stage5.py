"""Parche de 4 KiB sobre 512 MiB: tráfico separado y memoria real por proceso."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
from pathlib import Path
import time
import tomllib
from uuid import uuid4
from concurrent.futures import ThreadPoolExecutor
from hito2_runtime import Cluster
from measure_hito1 import memory
from dfsha.control.metadata import SQLiteMetadataStore
from dfsha.common.domain import CHUNK
from runtime import ROOT


def counters(lab):
    result = {}
    for process in lab.nodes[:3]:
        cfg = tomllib.loads(process.config.read_text(encoding='utf-8'))['datanode']
        with SQLiteMetadataStore(cfg['sqlite_path']).transaction() as tx:
            values = tx.get('settings', 'traffic') or {}
        result[process.info['node_id']] = {key: value for key, value in values.items() if key != 'id'}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--block-size', type=int, choices=(4194304, 67108864, 134217728), default=67108864)
    parser.add_argument('--bytes', type=int, default=536870912)
    parser.add_argument('--evidence', type=Path, default=ROOT / 'docs/evidencias/etapa5/measurement.json')
    args = parser.parse_args()
    root = ROOT / '.runtime/measure-e5' / str(uuid4())
    report = dict(status='PENDIENTE', timestamp=datetime.now(timezone.utc).isoformat(), runtime=str(root),
        file_bytes=args.bytes, block_size_bytes=args.block_size, chunk_bytes=CHUNK, replicas=1, durable_acks=1,
        platform=platform.platform(), scope='Un host local; tres clientes SDK en proceso de medición; CN y tres DN separados')
    try:
        with Cluster(root, block_size=args.block_size, rf3=True) as lab:
            source = root / 'source.bin'
            original = hashlib.sha256()
            pattern = bytes(range(256)) * (CHUNK // 256)
            with source.open('wb') as out:
                remaining = args.bytes
                while remaining:
                    chunk = pattern[:min(CHUNK, remaining)]
                    out.write(chunk)
                    original.update(chunk)
                    remaining -= len(chunk)
            client = lab.client()
            others = [lab.client(), lab.client()]
            try:
                client.send(source, '/large')
                h = client.open('/large', 'r+')
                old = client.open('/large')
                before = counters(lab)
                offset, delta = args.block_size // 2, b'P' * 4096
                started = time.monotonic()
                assert client.write(h, offset, delta) == len(delta)
                report['patch_seconds'] = round(time.monotonic() - started, 3)
                after = counters(lab)
                report['patch_traffic'] = {identity: {key: values.get(key, 0) - before[identity].get(key, 0)
                    for key in set(values) | set(before[identity]) | {'client_write_bytes', 'client_read_bytes',
                        'replica_write_bytes', 'replica_read_bytes'}} for identity, values in after.items()}
                expected = hashlib.sha256()
                with source.open('rb') as stream:
                    position = 0
                    while chunk := stream.read(CHUNK):
                        low, high = max(position, offset), min(position + len(chunk), offset + len(delta))
                        if high > low:
                            chunk = bytearray(chunk)
                            chunk[low-position:high-position] = delta[low-offset:high-offset]
                        expected.update(chunk)
                        position += len(chunk)
                actual = hashlib.sha256()
                for chunk in client.iter_read(h, 0, h.snapshot.size_bytes):
                    actual.update(chunk)
                assert actual.digest() == expected.digest()
                assert client.read(old, offset, len(delta)) == pattern[offset % CHUNK:offset % CHUNK + len(delta)]
                report.update(original_sha256=original.hexdigest(), expected_sha256=expected.hexdigest(),
                    downloaded_sha256=actual.hexdigest(), control_content_bytes=lab.statuses(client).control_content_bytes)
                # Concurrent SDK sessions patch separate blocks from a common snapshot.
                handles = [sdk.open('/large', 'r+') for sdk in others]
                import threading
                barrier = threading.Barrier(2)
                def concurrent(sdk, handle, index):
                    data = bytes([65 + index]) * 4096
                    plan = sdk.begin_write(handle, (index+1)*args.block_size, data)
                    changes = sdk.prepare_blocks(handle, plan, data)
                    barrier.wait(30)
                    return sdk.commit_write(handle, plan, changes).snapshot.file_version
                with ThreadPoolExecutor(2) as pool:
                    futures = [pool.submit(concurrent, sdk, handle, index) for index, (sdk, handle) in enumerate(zip(others, handles))]
                    report['concurrent_commit_versions'] = [future.result(timeout=60) for future in futures]
                latest = client.open('/large')
                try:
                    assert client.read(latest, args.block_size, 4096) == b'A' * 4096
                    assert client.read(latest, 2 * args.block_size, 4096) == b'B' * 4096
                    report['concurrent_patches_verified'] = True
                finally:
                    client.close(latest)
                report['client_process_memory'] = dict(pid=os.getpid(), **memory(os.getpid()))
                report['control_memory'] = dict(pid=lab.control.info['pid'], **memory(lab.control.info['pid']))
                report['datanode_memory'] = [dict(node_id=p.info['node_id'], pid=p.info['pid'], **memory(p.info['pid'])) for p in lab.nodes[:3]]
                traffic = report['patch_traffic'].values()
                assert sum(x.get('client_write_bytes', 0) for x in traffic) == 4096
                assert sum(x.get('client_read_bytes', 0) for x in traffic) == 0
                assert report['control_content_bytes'] == 0 and not list((lab.control.directory / 'blocks').rglob('*.blk'))
                report['memory_goals_met'] = report['client_process_memory']['peak_resident_bytes'] <= 268435456 and all(
                    x['peak_resident_bytes'] <= 536870912 for x in [report['control_memory']] + report['datanode_memory'])
                assert report['memory_goals_met']
                for sdk, handle in zip(others, handles):
                    sdk.close(handle)
                client.close(h)
                client.close(old)
                report['status'] = 'EJECUTADO'
            finally:
                for sdk in [client] + others:
                    sdk.shutdown()
    except BaseException as exc:
        report.update(status='FALLIDO', error=type(exc).__name__ + ': ' + str(exc))
        raise
    finally:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(args.evidence))))


if __name__ == '__main__':
    main()
