"""Offline maintenance of immutable metadata pages; never discard replay results."""
import hashlib
import json
import time

from dfsha.common.domain import need
from dfsha.common.etcd_probe_client import prefix_end
from dfsha.control.etcd_metadata import compare, encode
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb


def quiescent(lab):
    need(getattr(lab, 'protected', False), 'PERMISSION_DENIED')
    # Only a supervisor that owns the known process handles may perform this
    # operation. A directory or absent PID file alone is not proof of quiescence.
    need(all(p.process is not None and p.process.poll() is not None for p in lab.controls+lab.nodes[:3]), 'LOCK_BUSY')
    need(all(not p.process or p.process.poll() is not None for p in lab.nodes[3:]), 'LOCK_BUSY')


def release_pin(lab, snapshot_id, expected_digest):
    quiescent(lab)
    store = lab.metadata()
    try:
        with store.transaction(True) as tx:
            identity = 'migration-pin:'+snapshot_id
            old = tx.get('retention-result', identity)
            if old:
                need(old['digest'] == expected_digest, 'IDEMPOTENCY_MISMATCH')
                return old
            pin = tx.get('migration-pin', snapshot_id)
            snapshot = tx.get('snapshot', snapshot_id)
            need(pin and snapshot, 'NOT_FOUND')
            need(hashlib.sha256(encode(snapshot)).hexdigest() == expected_digest, 'VERSION_CONFLICT')
            tx.delete('migration-pin', snapshot_id)
            result = dict(id=identity, digest=expected_digest, snapshot=snapshot_id, released=True)
            tx.put('retention-result', result)
            return result
    finally:
        store.channel.close()


def collect_pages(lab):
    """Require an offline backup window; gate/root comparisons fence every batch.

    Keeps all records in the active and migration roots, including snapshots,
    idempotency ledgers and tombstones. This is not block GC or MVCC compaction.
    """
    quiescent(lab)
    store = lab.metadata()
    marked, deleted, scanned = set(), 0, 0
    last_renewal = time.monotonic()
    try:
        with store.transaction(True):
            root = store.range(store.root_key)
            gate = store.range(store.gate_key)
            need(root and gate, 'SERVICE_UNAVAILABLE')
            guards = [compare(store.gate_key, gate.value), pb.Compare(key=store.root_key,
                target=pb.Compare.MOD, result=pb.Compare.EQUAL, mod_revision=root.mod_revision)]
            def renew():
                nonlocal last_renewal
                if time.monotonic()-last_renewal >= 1:
                    store.keepalive(store.local.gate_lease)
                    last_renewal = time.monotonic()
            def blob(identity):
                renew()
                need(len(marked) < 100000, 'LIMIT_EXCEEDED')
                record = store.range(store.prefix+b'pages/'+identity.encode())
                need(record, 'DATA_LOSS')
                payload = store.cipher.open(record.value, record.key)
                need(store.page_address(payload) == identity, 'DATA_LOSS')
                marked.add(identity)
                if payload[:1] == b'L':
                    return payload[1:]
                need(payload[:1] == b'I', 'DATA_LOSS')
                return b''.join(blob(child) for child in json.loads(payload[1:]))
            roots = [root]
            imported = store.range(store.prefix+b'import-root')
            if imported:
                roots.append(imported)
                guards.append(pb.Compare(key=imported.key, target=pb.Compare.MOD,
                    result=pb.Compare.EQUAL, mod_revision=imported.mod_revision))
            for reference in roots:
                tree = json.loads(blob(reference.value.decode()))
                for shards in tree.values():
                    for bucket_id in shards.values():
                        for record_id in json.loads(blob(bucket_id)).values():
                            blob(record_id)
            prefix = store.prefix+b'pages/'
            cursor = prefix
            while True:
                renew()
                page = store.rpc(store.kv.Range, pb.RangeRequest(key=cursor, range_end=prefix_end(prefix),
                    limit=128, keys_only=True, sort_order=pb.RangeRequest.ASCEND, sort_target=pb.RangeRequest.KEY))
                if not page.kvs:
                    break
                scanned += len(page.kvs)
                need(scanned <= 100000, 'LIMIT_EXCEEDED')
                stale = [kv.key for kv in page.kvs if kv.key[len(prefix):].decode() not in marked]
                for start in range(0, len(stale), 32):
                    renew()
                    result = store.rpc(store.kv.Txn, pb.TxnRequest(compare=guards, success=[
                        pb.RequestOp(request_delete_range=pb.DeleteRangeRequest(key=key)) for key in stale[start:start+32]]))
                    need(result.succeeded, 'VERSION_CONFLICT')
                    deleted += sum(response.response_delete_range.deleted for response in result.responses)
                cursor = page.kvs[-1].key+b'\0'
                if not page.more:
                    break
        return dict(scanned=scanned, retained=len(marked), deleted=deleted, offline=True,
            root_changed=False, replay_records_deleted=False, mvcc_compacted=False)
    finally:
        store.channel.close()
