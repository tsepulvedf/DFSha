"""R3/W2 en Windows: contenido, copias reales, tráfico, caída y reparación."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4
from hito2_runtime import Cluster
from runtime import ROOT, wait_until
from measure_hito1 import memory
from measure_stage5 import counters
from dfsha.common.domain import CHUNK, asdict


def protection(client, path):
    result, cursor = [], ''
    while True:
        page = client.protection(path, cursor=cursor)
        result.extend(asdict(b) for b in page.blocks)
        if not page.next_cursor:
            return result
        cursor = page.next_cursor


def full(client, path):
    def ready():
        rows = protection(client, path)
        return rows if all(x.get('eligible', 0) >= 3 for x in rows) else None
    return wait_until(ready, seconds=300)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bytes', type=int, default=536870912)
    parser.add_argument('--block-size', type=int, default=67108864, choices=(4194304, 67108864, 134217728))
    parser.add_argument('--evidence', type=Path, default=ROOT/'docs/evidencias/etapa6/measurement.json')
    args = parser.parse_args()
    root = ROOT/'.runtime/measure-e6'/str(uuid4())
    report = dict(status='PENDIENTE', timestamp=datetime.now(timezone.utc).isoformat(), bytes=args.bytes,
        block_size=args.block_size, chunk_bytes=CHUNK, target=3, minimum=2, failure_profile='process-simulation',
        runtime=str(root), scope='Un host Windows; un control y 3/4 DataNodes independientes; no tolerancia de host')
    try:
        with Cluster(root, block_size=args.block_size, replication=True) as lab:
            client = lab.client()
            try:
                source = root/'source.bin'
                original = hashlib.sha256()
                pattern = bytes(range(256))*(CHUNK//256)
                with source.open('wb') as out:
                    remaining = args.bytes
                    while remaining:
                        chunk = pattern[:min(CHUNK, remaining)]
                        out.write(chunk)
                        original.update(chunk)
                        remaining -= len(chunk)
                started = time.monotonic()
                result = client.send(source, '/large')
                report['upload_seconds'] = time.monotonic()-started
                report['commit'] = asdict(result)
                report['before_failure'] = full(client, '/large')
                output = root/'download.bin'
                started = time.monotonic()
                client.receive('/large', output)
                report['download_seconds'] = time.monotonic()-started
                digest = hashlib.sha256()
                with output.open('rb') as inp:
                    while chunk := inp.read(CHUNK):
                        digest.update(chunk)
                assert original.digest() == digest.digest()
                report['original_sha256'], report['downloaded_sha256'] = original.hexdigest(), digest.hexdigest()
                report['client_useful_traffic'] = deepcopy(client.traffic)
                report['transfer_traffic'] = counters(lab)
                h = client.open('/large', 'r+')
                before = counters(lab)
                started = time.monotonic()
                client.write(h, args.block_size//2, b'X'*4096)
                report['patch_commit_seconds'] = time.monotonic()-started
                full(client, '/large')
                after = counters(lab)
                report['patch_traffic'] = {k: {field: after[k].get(field, 0)-before[k].get(field, 0)
                    for field in set(after[k]) | set(before[k])} for k in after}
                assert sum(x.get('client_write_bytes', 0) for x in report['patch_traffic'].values()) == 4096
                assert client.read(h, args.block_size//2, 4096) == b'X'*4096
                client.close(h)
                # Preserve the departing node's high-water mark before its PID disappears.
                node_memory = {p.info['node_id']: dict(node_id=p.info['node_id'], pid=p.info['pid'],
                    **memory(p.info['pid'])) for p in lab.nodes[:3]}
                started = time.monotonic()
                lab.nodes[0].stop()
                wait_until(lambda: next(x for x in client.nodes().nodes if x.node.node_id == lab.node_ids[0]).state == 'UNAVAILABLE', seconds=15)
                report['detect_seconds_from_stop'] = time.monotonic()-started
                report['degraded'] = protection(client, '/large')
                started = time.monotonic()
                h = client.open('/large')
                assert client.read(h, args.block_size//2, 4096) == b'X'*4096
                client.close(h)
                report['alternate_seconds_from_open'] = time.monotonic()-started
                started = time.monotonic()
                lab.nodes[3].start()
                lab.wait_ready(3, client)
                report['after_repair'] = full(client, '/large')
                report['repair_seconds_from_fourth_start'] = time.monotonic()-started
                expected = hashlib.sha256()
                with source.open('rb') as inp:
                    position = 0
                    while chunk := inp.read(CHUNK):
                        low, high = max(position, args.block_size//2), min(position+len(chunk), args.block_size//2+4096)
                        if high > low:
                            chunk = bytearray(chunk)
                            chunk[low-position:high-position] = b'X'*(high-low)
                        expected.update(chunk)
                        position += len(chunk)
                downloaded = client.receive('/large', output, overwrite=True)
                assert downloaded['sha256'] == expected.hexdigest()
                report['patched_expected_sha256'] = expected.hexdigest()
                report['repaired_download_sha256'] = downloaded['sha256']
                report['control_content_bytes'] = client.nodes().control_content_bytes
                assert report['control_content_bytes'] == 0
                report['memory_method'] = 'Windows PeakWorkingSetSize del PID anunciado por el proceso servidor; no del lanzador venv. Máximo desde el arranque.'
                node_memory.update({p.info['node_id']: dict(node_id=p.info['node_id'], pid=p.info['pid'],
                    **memory(p.info['pid'])) for p in lab.nodes if p.process.poll() is None})
                report['memory'] = dict(client=dict(pid=os.getpid(), **memory(os.getpid())),
                    control=dict(pid=lab.control.info['pid'], **memory(lab.control.info['pid'])),
                    datanodes=list(node_memory.values()))
                report['memory_goals_met'] = report['memory']['client']['peak_resident_bytes'] <= 256*1048576 and report['memory']['control']['peak_resident_bytes'] <= 512*1048576 and all(x['peak_resident_bytes'] <= 512*1048576 for x in report['memory']['datanodes'])
                assert report['memory_goals_met']
                report['status'] = 'EJECUTADO'
            finally:
                client.shutdown()
    except BaseException as exc:
        report.update(status='FALLIDO', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(dict(status=report['status'], evidence=str(args.evidence))))


if __name__ == '__main__':
    main()
