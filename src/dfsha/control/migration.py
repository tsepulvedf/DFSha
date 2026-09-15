"""Transición offline: backup SQLite/WAL y activación única del espacio etcd."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
from uuid import uuid4
from dfsha.control.metadata import SQLiteMetadataStore
from dfsha.control.etcd_metadata import encode
from dfsha.v1 import common_pb2 as c


def migrate(source, backup, destination):
    source, backup = Path(source), Path(backup)
    if backup.exists() or destination.range(destination.root_key):
        raise ValueError('Backup y espacio etcd deben estar vacíos; no sobrescribir una autoridad')
    owner = source.with_suffix('.owner').open('a+b')
    try:
        owner.seek(0)
        if not owner.read(1):
            owner.write(b'1')
            owner.flush()
        owner.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(owner.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        backup.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source) as src, sqlite3.connect(backup) as out:
            src.backup(out)
        original = SQLiteMetadataStore(source)
        with original.transaction(True) as tx:
            system = tx.get('settings', 'system')
            if system.get('authority_migrated'):
                raise ValueError('SQLite ya fue desactivado por una migración anterior')
            system['authority_migrated'] = destination.prefix.decode()
            tx.put('settings', system)
        with sqlite3.connect(backup) as db:
            records = [(kind, json.loads(body)) for kind, body in db.execute('SELECT kind,body FROM objects ORDER BY kind,id')]
        original_digest = hashlib.sha256(encode(records)).hexdigest()
        retained = []
        epoch = str(uuid4())
        for kind, value in records:
            if kind == 'settings' and value['id'] == 'system':
                value['epoch'] = epoch
                value.pop('authority_migrated', None)
            if kind == 'settings' and value['id'] == 'control-epoch':
                value.update(epoch=epoch, generation=value.get('generation', 0)+1)
            if kind == 'handle' and not value['closed']:
                retained.append(('migration-pin', dict(id=value['snapshot'], snapshot=value['snapshot'])))
                value['closed'] = True
            if kind == 'session':
                value['revoked'] = True
            if kind == 'upload' and value['state'] == c.PREPARING:
                value.update(state=c.ABORTED, reserved=0)
            if kind == 'task' and value['status']['state'] in ('ACCEPTED', 'RUNNING'):
                value.update(expires=0, reserved=0)
                value['status']['state'] = 'FAILED'
            if kind == 'datanode':
                value.update(seen=0, reconciled=False)
        records = [(kind, value) for kind, value in records if kind not in ('lock', 'handle', 'read')]+retained
        if not any(k == 'settings' and v['id'] == 'control-epoch' for k, v in records):
            records.append(('settings', dict(id='control-epoch', epoch=epoch, generation=1)))
        # Staging has its own root, never the authority used by a ControlNode.
        active = destination.root_key
        destination.root_key = destination.prefix+b'import-root'
        try:
            for start in range(0, len(records), 32):
                with destination.transaction(True) as tx:
                    for kind, value in records[start:start+32]:
                        if kind == 'datanode':
                            # Imported nodes must reconcile before receiving a fresh liveness lease.
                            tx.pending[(kind, value['id'])] = value
                        else:
                            tx.put(kind, value)
            with destination.transaction() as tx:
                for kind, expected in records:
                    if tx.get(kind, expected['id']) != expected:
                        raise RuntimeError('MIGRATION_VERIFICATION_FAILED')
            root = destination.range(destination.root_key)
            from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb
            result = destination.rpc(destination.kv.Txn, pb.TxnRequest(compare=[pb.Compare(key=active,
                target=pb.Compare.CREATE, result=pb.Compare.EQUAL, create_revision=0)], success=[pb.RequestOp(
                    request_put=pb.PutRequest(key=active, value=root.value))]))
            if not result.succeeded:
                raise RuntimeError('Otra autoridad activó ese espacio; SQLite sigue desactivado')
        finally:
            destination.root_key = active
        return dict(status='EJECUTADO', records=len(records), original_sha256=original_digest,
            imported_sha256=hashlib.sha256(encode(records)).hexdigest(), epoch=epoch,
            retained_snapshots=len(retained), sqlite_disabled=True, backup=str(backup), root=root.value.decode())
    finally:
        owner.close()
