"""Snapshot/restore etcd 3.6.14; no sustituye el respaldo de bloques y claves."""
import json
import os
from pathlib import Path
import subprocess
from runtime import ROOT, PROCESS_FLAGS


def binary(name):
    return ROOT/'.tools/etcd-3.6.14'/('windows-amd64' if os.name == 'nt' else 'linux-amd64')/(name+('.exe' if os.name == 'nt' else ''))


def execute(args):
    result = subprocess.run([str(x) for x in args], cwd=ROOT, capture_output=True, text=True,
        encoding='utf-8', timeout=60, creationflags=PROCESS_FLAGS)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout


def snapshot(cluster, destination):
    destination = Path(destination)
    if destination.exists():
        raise FileExistsError(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    certs = cluster.certs
    execute([binary('etcdctl'), '--endpoints=https://'+cluster.targets[0],
        '--cacert='+str(certs/'ca.crt'), '--cert='+str(certs/'etcd-root.crt'),
        '--key='+str(certs/'etcd-root.key'), '--command-timeout=30s', 'snapshot', 'save', destination])
    return json.loads(execute([binary('etcdutl'), 'snapshot', 'status', destination, '--write-out=json']))


def restore(snapshot_path, cluster):
    """Restore each member into NEW directories with NEW membership/token."""
    for member in cluster.members:
        args = dict(item[2:].split('=', 1) for item in member.args[1:])
        destination = Path(args['data-dir'])
        if destination.exists():
            raise FileExistsError(destination)
        execute([binary('etcdutl'), 'snapshot', 'restore', snapshot_path,
            '--data-dir='+str(destination), '--name='+args['name'],
            '--initial-cluster='+args['initial-cluster'],
            '--initial-cluster-token='+args['initial-cluster-token'],
            '--initial-advertise-peer-urls='+args['initial-advertise-peer-urls'],
            '--bump-revision=1000000000', '--mark-compacted'])
    cluster.restored = True
