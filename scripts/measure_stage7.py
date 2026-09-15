"""Medición HA local: archivo >=512 MiB, delta de 4 KiB y tráfico separado."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from uuid import uuid4
from ha_runtime import HACluster
from runtime import ROOT
from measure_hito1 import memory
from measure_stage5 import counters
from measure_stage6 import full
from dfsha.common.domain import CHUNK


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bytes', type=int, default=536870912)
    parser.add_argument('--block-size', type=int, default=67108864, choices=(4194304, 67108864, 134217728))
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    if args.bytes < 536870912:
        parser.error('La medición de aceptación requiere al menos 512 MiB')
    root = ROOT/'.runtime/measure-e7'/str(uuid4())
    report = dict(status='PENDIENTE', timestamp=datetime.now(timezone.utc).isoformat(), runtime=str(root),
        file_bytes=args.bytes, block_size_bytes=args.block_size, chunk_bytes=CHUNK, target_replicas=3,
        minimum_durable=2, metadata_majority=2, failure_profile='process-simulation',
        scope='Un host Windows. Cliente y supervisor de proxies comparten proceso; no tolerancia de host.')
    try:
        with HACluster(root, block_size=args.block_size) as lab:
            source, output = root/'source.bin', root/'download.bin'
            pattern = bytes(range(256))*(CHUNK//256)
            with source.open('wb') as out:
                left = args.bytes
                while left:
                    value = pattern[:min(left, CHUNK)]
                    out.write(value)
                    left -= len(value)
            expected = digest(source)
            client = lab.client()
            try:
                start = time.monotonic()
                client.send(source, '/large')
                report['upload_seconds'] = time.monotonic()-start
                report['copies_before'] = full(client, '/large')
                client.receive('/large', output)
                assert digest(output) == expected
                report['initial_sha256'] = expected
                report['transfer_client_traffic'] = deepcopy(client.traffic)
                handle = client.open('/large', 'r+')
                before = counters(lab)
                start = time.monotonic()
                assert client.write(handle, args.block_size//2, b'P'*4096) == 4096
                report['patch_commit_seconds'] = time.monotonic()-start
                report['copies_after_patch'] = full(client, '/large')
                after = counters(lab)
                report['patch_traffic'] = {node: {key: values.get(key, 0)-before[node].get(key, 0)
                    for key in set(values)|set(before[node])} for node, values in after.items()}
                assert sum(row.get('client_write_bytes', 0) for row in report['patch_traffic'].values()) == 4096
                with source.open('r+b') as stream:
                    stream.seek(args.block_size//2)
                    stream.write(b'P'*4096)
                expected = digest(source)
                report['control_memory'] = {str(i): memory(p.info['pid']) for i,p in enumerate(lab.controls)}
                report['etcd_membership'] = lab.etcd.status()
                report['etcd_memory'] = {str(i): memory(p.process.pid) for i,p in enumerate(lab.etcd.members)}
                failed = client.channel.index
                start = time.monotonic()
                lab.controls[failed].stop()
                assert client.read(handle, args.block_size//2, 4096) == b'P'*4096
                report['failover_read_seconds_from_stop_request'] = time.monotonic()-start
                client.close(handle)
                client.receive('/large', output, overwrite=True)
                assert digest(output) == expected
                report['patched_sha256'] = expected
                report['datanode_memory'] = {str(i): memory(p.info['pid']) for i,p in enumerate(lab.nodes[:3])}
                report['client_and_proxy_supervisor_memory'] = memory(os.getpid())
                report['metadata_tls_bytes_by_control'] = {str(i): dict(to_etcd=sum(p.up_bytes for p in group),
                    from_etcd=sum(p.down_bytes for p in group)) for i,group in enumerate(lab.proxies)}
                report['data_traffic'] = counters(lab)
                report['control_file_content_bytes'] = 0
                report['status'] = 'EJECUTADO'
            finally:
                client.shutdown()
    except Exception as exc:
        import traceback
        report['status'], report['error'] = 'FALLIDO', str(exc)
        report['traceback'] = traceback.format_exc()
    finally:
        selected = {'put_started', 'put_authorized', 'block_grant_issued', 'block_path_rejected', 'node_rpc_rejected'}
        report['traces'] = []
        for logfile in root.glob('*/server.log'):
            for line in logfile.read_text(encoding='utf-8', errors='replace').splitlines():
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get('event') in selected:
                    report['traces'].append(dict(process=logfile.parent.name, **row))
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(args.evidence))))
    return int(report['status'] != 'EJECUTADO')


if __name__ == '__main__':
    raise SystemExit(main())
