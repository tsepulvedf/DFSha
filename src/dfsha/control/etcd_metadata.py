"""UoW compartida: páginas inmutables y publicación CAS protegida por leases etcd."""
from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import threading
import time
from uuid import uuid4
import grpc

from dfsha.common.domain import Fault, need
from dfsha.common.rpc import channel
from dfsha.common.failover import FailoverChannel
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb, rpc_pb2_grpc as api

PAGE_BYTES = 131072
MAX_GUARDS = 48


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def compare(key, value):
    return pb.Compare(key=key, target=pb.Compare.VALUE, result=pb.Compare.EQUAL, value=value)


class EtcdMetadataStore:
    def __init__(self, cfg):
        self.cfg = cfg
        self.prefix = cfg['etcd_prefix'].encode().rstrip(b'/')+b'/v1/'
        need(self.prefix.startswith(b'/dfsha/ha/') and b'..' not in self.prefix)
        self.channel = FailoverChannel([channel(x, Path(cfg['etcd_certificate_dir']), cfg['etcd_identity'])
            for x in cfg['etcd_endpoints']])
        self.kv, self.lease = api.KVStub(self.channel), api.LeaseStub(self.channel)
        self.watch = api.WatchStub(self.channel)
        self.local = threading.local()
        self.cache, self.cache_size = OrderedDict(), 0
        self.cache_guard = threading.Lock()
        self.root_key, self.gate_key = self.prefix+b'root', self.prefix+b'gate'
        self.rpc_timeout = cfg.get('etcd_timeout_seconds', 3)

    def rpc(self, method, request):
        try:
            return method(request, timeout=self.rpc_timeout)
        except grpc.RpcError as exc:
            code = exc.code()
            reason = 'SERVICE_UNAVAILABLE'
            if code == grpc.StatusCode.UNAUTHENTICATED:
                reason = 'UNAUTHENTICATED'
            elif code == grpc.StatusCode.PERMISSION_DENIED:
                reason = 'PERMISSION_DENIED'
            elif code == grpc.StatusCode.RESOURCE_EXHAUSTED or (code == grpc.StatusCode.FAILED_PRECONDITION
                    and 'space exceeded' in (exc.details() or '')):
                reason = 'NO_SPACE'
            elif code == grpc.StatusCode.DATA_LOSS:
                reason = 'DATA_LOSS'
            raise Fault(reason) from exc

    def range(self, key):
        response = self.rpc(self.kv.Range, pb.RangeRequest(key=key))
        return response.kvs[0] if response.kvs else None

    def grant(self, seconds):
        identity = uuid4().int & ((1 << 63)-1)
        result = self.rpc(self.lease.LeaseGrant, pb.LeaseGrantRequest(ID=identity, TTL=max(1, math.ceil(seconds))))
        need(not result.error, 'SERVICE_UNAVAILABLE')
        return result.ID

    def keepalive(self, identity):
        try:
            stream = self.lease.LeaseKeepAlive(iter([pb.LeaseKeepAliveRequest(ID=identity)]), timeout=self.rpc_timeout)
            result = next(stream)
            need(result.TTL > 0, 'LOCK_EXPIRED')
            return result.TTL
        except (grpc.RpcError, StopIteration) as exc:
            raise Fault('SERVICE_UNAVAILABLE') from exc
        finally:
            if 'stream' in locals():
                stream.cancel()

    def gate_lease(self):
        lease = getattr(self.local, 'gate_lease', None)
        if lease:
            try:
                self.keepalive(lease)
                return lease
            except Fault as exc:
                if exc.reason != 'LOCK_EXPIRED':
                    raise
        lease = self.grant(self.cfg.get('metadata_gate_lease_seconds', 10))
        self.local.gate_lease = lease
        return lease

    def cache_put(self, digest, payload):
        with self.cache_guard:
            old = self.cache.pop(digest, None)
            self.cache_size -= len(old) if old else 0
            self.cache[digest] = payload
            self.cache_size += len(payload)
            while self.cache_size > 16*1048576:
                _, removed = self.cache.popitem(last=False)
                self.cache_size -= len(removed)

    def page(self, payload):
        need(len(payload) <= PAGE_BYTES+1, 'LIMIT_EXCEEDED')
        digest = hashlib.sha256(payload).hexdigest()
        with self.cache_guard:
            cached = digest in self.cache
        if not cached:
            tx = getattr(self.local, 'unit', None)
            if tx and tx.write:
                tx.pages[digest] = payload
                need(sum(map(len, tx.pages.values())) <= 16*1048576, 'LIMIT_EXCEEDED')
            else:
                self.rpc(self.kv.Put, pb.PutRequest(key=self.prefix+b'pages/'+digest.encode(), value=payload))
                self.cache_put(digest, payload)
        return digest

    def persist_pages(self, pages):
        batch, size = [], 0
        def flush():
            if batch:
                self.rpc(self.kv.Txn, pb.TxnRequest(success=[pb.RequestOp(request_put=pb.PutRequest(
                    key=self.prefix+b'pages/'+digest.encode(), value=payload)) for digest, payload in batch]))
                for digest, payload in batch:
                    self.cache_put(digest, payload)
        for digest, payload in pages.items():
            if len(batch) >= 32 or size+len(payload) > 524288:
                flush()
                batch, size = [], 0
            batch.append((digest, payload))
            size += len(payload)
        flush()

    def blob(self, payload):
        if len(payload) <= PAGE_BYTES:
            return self.page(b'L'+payload)
        children = [self.page(b'L'+payload[i:i+PAGE_BYTES]) for i in range(0, len(payload), PAGE_BYTES)]
        while len(children) > 64:
            children = [self.page(b'I'+encode(children[i:i+64])) for i in range(0, len(children), 64)]
        return self.page(b'I'+encode(children))

    def read_blob(self, digest):
        with self.cache_guard:
            payload = self.cache.get(digest)
        if payload is None:
            record = self.range(self.prefix+b'pages/'+digest.encode())
            need(record is not None, 'DATA_LOSS')
            payload = record.value
            need(hashlib.sha256(payload).hexdigest() == digest, 'DATA_LOSS')
            self.cache_put(digest, payload)
        if payload[:1] == b'L':
            return payload[1:]
        need(payload[:1] == b'I', 'DATA_LOSS')
        return b''.join(self.read_blob(x) for x in json.loads(payload[1:]))

    def object(self, digest):
        return json.loads(self.read_blob(digest)) if digest else {}

    def lease_live(self, record):
        key = record.get('lease_key')
        if not key:
            return False
        tx = getattr(self.local, 'unit', None)
        if tx and key in tx.effects and tx.effects[key].HasField('request_put'):
            return tx.effects[key].request_put.value.decode() == record['lease_owner']
        if tx and key in tx.lease_reads:
            value = tx.lease_reads[key]
        else:
            value = self.range(key.encode())
            if tx:
                tx.lease_reads[key] = value
        valid = value is not None and value.value.decode() == record['lease_owner']
        if valid and tx:
            tx.guards[key.encode()] = value.value
        return valid

    @contextmanager
    def transaction(self, write=False):
        if getattr(self.local, 'unit', None) is not None:
            raise RuntimeError('Una UoW etcd no admite transacciones anidadas')
        owner, lease, released = str(uuid4()).encode(), None, False
        started = acquired = prepared = time.monotonic()
        try:
            if write:
                lease = self.gate_lease()
                deadline = time.monotonic()+self.cfg.get('metadata_gate_wait_seconds', 4)
                while True:
                    # Poll with a linearizable read: a failed write transaction
                    # still enters Raft and can starve the current owner.
                    if self.range(self.gate_key) is not None:
                        need(time.monotonic() < deadline, 'SERVICE_UNAVAILABLE')
                        time.sleep(.025)
                        continue
                    result = self.rpc(self.kv.Txn, pb.TxnRequest(compare=[pb.Compare(key=self.gate_key,
                        target=pb.Compare.CREATE, result=pb.Compare.EQUAL, create_revision=0)],
                        success=[pb.RequestOp(request_put=pb.PutRequest(key=self.gate_key, value=owner, lease=lease))]))
                    if result.succeeded:
                        break
                    need(time.monotonic() < deadline, 'SERVICE_UNAVAILABLE')
                    time.sleep(.01)
            acquired = time.monotonic()
            root = self.range(self.root_key)
            tx = EtcdUnit(self, root, write)
            tx.guards.update(getattr(self.local, 'required_guards', {}))
            self.local.unit = tx
            yield tx
            prepared = time.monotonic()
            if write:
                digest = tx.flush()
                self.persist_pages(tx.pages)
                guards = [compare(self.gate_key, owner), pb.Compare(key=self.root_key, target=pb.Compare.MOD,
                    result=pb.Compare.EQUAL, mod_revision=root.mod_revision if root else 0)]
                need(len(tx.guards) <= MAX_GUARDS and len(tx.effects) <= MAX_GUARDS, 'LIMIT_EXCEEDED')
                guards.extend(compare(k, v) for k, v in tx.guards.items())
                effects = list(tx.effects.values())
                marker = self.prefix+b'commits/'+owner
                effects.append(pb.RequestOp(request_put=pb.PutRequest(key=marker, value=digest.encode(), lease=lease)))
                previous_marker = getattr(self.local, 'previous_marker', None)
                if previous_marker:
                    effects.append(pb.RequestOp(request_delete_range=pb.DeleteRangeRequest(key=previous_marker)))
                if not root or root.value != digest.encode():
                    effects.append(pb.RequestOp(request_put=pb.PutRequest(key=self.root_key, value=digest.encode())))
                effects.append(pb.RequestOp(request_delete_range=pb.DeleteRangeRequest(key=self.gate_key)))
                request = pb.TxnRequest(compare=guards, success=effects)
                need(request.ByteSize() < 262144, 'LIMIT_EXCEEDED')
                result = self.rpc(self.kv.Txn, request)
                if not result.succeeded:
                    # A repeated Txn can fail after its first attempt committed.
                    # Root equality alone cannot prove lease effects committed.
                    committed = self.range(marker)
                    need(committed and committed.value == digest.encode(), 'VERSION_CONFLICT')
                released = True
                self.local.previous_marker = marker
        finally:
            self.local.unit = None
            if write and self.cfg.get('metadata_trace_timing'):
                from dfsha.common.telemetry import event
                event('metadata_timing', code=f'wait={acquired-started:.3f};work={max(0, prepared-acquired):.3f};publish={time.monotonic()-max(prepared, acquired):.3f};ok={released}')
            if lease and not released:
                try:
                    self.rpc(self.kv.Txn, pb.TxnRequest(compare=[compare(self.gate_key, owner)],
                        success=[pb.RequestOp(request_delete_range=pb.DeleteRangeRequest(key=self.gate_key))]))
                except Fault:
                    pass  # Lost quorum: expiry releases only this acquisition, never another owner.


class EtcdUnit:
    def __init__(self, store, root, write):
        self.store, self.write = store, write
        self.root = store.object(root.value.decode()) if root else {}
        self.buckets, self.pending, self.guards, self.effects = {}, {}, {}, {}
        self.lease_reads = {}
        self.pages = {}

    def bucket(self, kind, identity):
        shard = hashlib.sha256(identity.encode()).hexdigest()[:2]
        key = (kind, shard)
        if key not in self.buckets:
            self.buckets[key] = self.store.object(self.root.get(kind, {}).get(shard))
        return self.buckets[key]

    def get(self, kind, identity):
        if identity is None:
            return None  # Optional references use the same semantics as SQLite.
        if (kind, identity) in self.pending:
            return deepcopy(self.pending[(kind, identity)])
        digest = self.bucket(kind, identity).get(identity)
        return self.store.object(digest) if digest else None

    def all(self, kind):
        identities = set()
        for shard, digest in self.root.get(kind, {}).items():
            key = (kind, shard)
            if key not in self.buckets:
                self.buckets[key] = self.store.object(digest)
            identities.update(self.buckets[key])
        identities.update(i for k, i in self.pending if k == kind)
        return [value for identity in sorted(identities) if (value := self.get(kind, identity)) is not None]

    def children(self, parent):
        return sorted((x for x in self.all('node') if x.get('alive') and x.get('parent') == parent), key=lambda x: x['name'])

    def put(self, kind, value):
        need(self.write, 'PERMISSION_DENIED')
        if kind in ('lock', 'handle', 'datanode', 'session') and not value.get('closed') and not value.get('revoked'):
            previous = self.get(kind, value['id'])
            if kind == 'session':
                value['deadline'] = value['expires']/1000
            if kind == 'datanode':
                value['deadline'] = time.time()+self.store.cfg.get('unavailable_ms', 6000)/1000
                if not self.store.lease_live(value):
                    value.pop('lease_key', None)
            if not value.get('lease_key'):
                ttl = 300 if kind == 'lock' and value.get('whole') and value.get('automatic') else max(1, value['deadline']-time.time())
                value['lease'] = self.store.grant(ttl)
                value['lease_key'] = (self.store.prefix+b'leases/'+kind.encode()+b'/'+value['id'].encode()).decode()
                value['lease_owner'] = str(uuid4())
                self.effects[value['lease_key']] = pb.RequestOp(request_put=pb.PutRequest(
                    key=value['lease_key'].encode(), value=value['lease_owner'].encode(), lease=value['lease']))
            elif previous and value.get('deadline', 0) > previous.get('deadline', 0):
                need(self.store.lease_live(value), 'LOCK_EXPIRED')
                self.store.keepalive(value['lease'])
        self.pending[(kind, value['id'])] = deepcopy(value)

    def session_live(self, session):
        return self.store.lease_live(session)

    def delete(self, kind, identity):
        need(self.write, 'PERMISSION_DENIED')
        previous = self.get(kind, identity)
        if previous and previous.get('lease_key'):
            key = previous['lease_key']
            self.effects[key] = pb.RequestOp(request_delete_range=pb.DeleteRangeRequest(key=key.encode()))
        self.pending[(kind, identity)] = None

    def flush(self):
        changed = set()
        for (kind, identity), value in self.pending.items():
            bucket = self.bucket(kind, identity)
            digest = self.store.blob(encode(value)) if value is not None else None
            if bucket.get(identity) == digest:
                continue
            if digest:
                bucket[identity] = digest
            else:
                bucket.pop(identity, None)
            changed.add((kind, hashlib.sha256(identity.encode()).hexdigest()[:2]))
        for kind, shard in changed:
            self.root.setdefault(kind, {})[shard] = self.store.blob(encode(self.buckets[(kind, shard)]))
        return self.store.blob(encode(self.root))
