"""DataNode persistente E4. Inventario local, autorización en línea y streams acotados."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import os
from pathlib import Path
import shutil
import threading

from dfsha.common.domain import need, Fault, uid, now, asdict, proto, intent, CHUNK, DEADLINES
from dfsha.common.local import LocalCoordinator
from dfsha.common import node_rpc
from dfsha.control.monolith import Monolith
from dfsha.control.metadata import SQLiteMetadataStore
from dfsha.control.distributed import storage_cost
from dfsha.datanode.blocks import EncryptedBlockStore
from dfsha.v1 import common_pb2 as c, data_pb2 as d, data_pb2_grpc as dg, nodes_pb2 as n, nodes_pb2_grpc as ng


class DataNode:
    credentials = Monolith.credentials
    fault = Monolith.fault
    counters = ('client_write_bytes', 'client_read_bytes', 'replica_write_bytes', 'replica_read_bytes')

    def __init__(self, cfg):
        self.cfg = cfg
        self.store = SQLiteMetadataStore(cfg['sqlite_path'])
        need(self.store.path.is_file(), 'NOT_FOUND')
        key_path = Path(cfg['key_path'])
        if not key_path.is_file() or len(key_path.read_bytes()) != 32:
            raise RuntimeError('MASTER_KEY_MISSING_OR_INVALID')
        key = key_path.read_bytes()
        # Exclusive inventory owner, just as H1: prevent overlapping incarnations on one volume.
        self.owner_lock = self.store.path.with_suffix('.owner').open('a+b')
        self.owner_lock.seek(0)
        if not self.owner_lock.read(1):
            self.owner_lock.write(b'1')
            self.owner_lock.flush()
        self.owner_lock.seek(0)
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(self.owner_lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(self.owner_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with self.store.transaction(True) as tx:
            settings = tx.get('settings', 'node')
            if not settings or settings['id_node'] != cfg['certificate_identity']:
                raise RuntimeError('NODE_IDENTITY_MISMATCH')
            if settings['key_sha256'] != hashlib.sha256(key).hexdigest():
                raise RuntimeError('MASTER_KEY_MISMATCH')
            settings['generation'] += 1
            tx.put('settings', settings)
        self.generation = settings['generation']
        self.node_id = settings['id_node']
        self.inventory_id = uid()
        self.blocks = EncryptedBlockStore(cfg['block_path'], key)
        self.recover_unindexed_objects()
        self.coordinator = LocalCoordinator()
        self.guard = threading.RLock()
        self.reserved = 0
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.jobs = set()
        self.channel = node_rpc.channel(cfg['control_internal_target'], cfg)
        self.registry = ng.NodeRegistryServiceStub(self.channel)
        self.authorization = ng.InternalAuthorizationServiceStub(self.channel)
        self.stop_event = threading.Event()
        self.sequence = 0
        self.worker = threading.Thread(target=self.maintain, name='node-registration', daemon=True)

    def context(self):
        return node_rpc.context_for(self.cfg)

    def recover_unindexed_objects(self):
        """Crash window after fsync and before inventory commit: report, then let control retire."""
        import json
        import struct
        from dfsha.datanode.blocks import MAGIC
        from dfsha.common.domain import uuid
        for folder in self.blocks.root.iterdir():
            if not folder.is_dir() or folder.is_symlink():
                continue
            uuid(folder.name)
            for path in folder.iterdir():
                if path.is_symlink():
                    continue
                if path.suffix == '.staging':
                    uuid(path.stem)
                    path.unlink()  # Exclusive volume owner, no live stream before server startup.
                elif path.suffix == '.blk':
                    uuid(path.stem)
                    with self.store.transaction() as tx:
                        known = tx.get('block', path.stem)
                    if known:
                        continue
                    try:
                        with path.open('rb') as stream:
                            need(stream.read(8) == MAGIC, 'DATA_LOSS')
                            length = struct.unpack('>I', stream.read(4))[0]
                            need(0 < length <= 4096, 'DATA_LOSS')
                            obj = json.loads(stream.read(length))
                        block = c.BlockRef(file_id=folder.name, block_version_id=path.stem,
                            block_index=obj.get('block_index', 0), size_bytes=obj['size'], plaintext_sha256=bytes.fromhex(obj['sha256']))
                        for _ in self.blocks.read_verified(block):
                            pass
                        digest = hashlib.sha256()
                        with path.open('rb') as stream:
                            while chunk := stream.read(CHUNK):
                                digest.update(chunk)
                        receipt = c.DurableReceipt(receipt_id=uid(), operation_id=uid(), block=block,
                            node_id=self.node_id, boot_generation=self.generation, failure_domain=self.cfg['failure_domain'],
                            stored_size_bytes=path.stat().st_size, ciphertext_sha256=digest.digest(), durable_at_unix_ms=now())
                        with self.store.transaction(True) as tx:
                            tx.put('block', dict(id=block.block_version_id, ref=asdict(block), stored_size=receipt.stored_size_bytes,
                                receipt=asdict(receipt), recovered_unconfirmed=True))
                    except (Fault, ValueError, KeyError, struct.error):
                        from dfsha.common.telemetry import event
                        event('object_quarantined', code='DATA_LOSS')

    def location(self):
        return c.BlockLocation(node_id=self.node_id, boot_generation=self.generation,
            client_endpoint=self.cfg['client_endpoint'], private_endpoint=self.cfg['private_endpoint'], failure_domain=self.cfg['failure_domain'])

    def metrics(self):
        with self.store.transaction() as tx:
            records = tx.all('block')
            counters = tx.get('settings', 'traffic') or {}
            quarantine_bytes = sum(x['stored_size'] for x in tx.all('quarantine'))
        return dict(used_bytes=sum(x['stored_size'] for x in records) + quarantine_bytes,
            free_bytes=shutil.disk_usage(self.blocks.root).free, active_streams=len(self.blocks.active),
            reserved_bytes=self.reserved, **{k: counters.get(k, 0) for k in self.counters})

    def count(self, name, amount):
        with self.store.transaction(True) as tx:
            record = tx.get('settings', 'traffic') or dict(id='traffic')
            record[name] = record.get(name, 0) + amount
            tx.put('settings', record)

    def register_inventory(self):
        self.registry.RegisterNode(n.RegisterNodeRequest(context=self.context(), node=self.location(),
            capacity_bytes=self.cfg['capacity_bytes'], free_bytes=self.metrics()['free_bytes'], inventory_id=self.inventory_id), timeout=5)
        # Verify local content before reporting persistent receipts as ready after a restart.
        with self.store.transaction() as tx:
            records = tx.all('block')
        receipts = []
        for record in records:
            try:
                for _ in self.blocks.read_verified(proto(c.BlockRef, record['ref'])):
                    pass
                receipts.append(proto(c.DurableReceipt, record['receipt']))
            except Fault:
                continue  # Retain corrupt objects for diagnosis, never advertise them as a valid copy.
        for page in range(max(1, (len(receipts) + 63) // 64)):
            self.registry.BlockReport(n.BlockReportRequest(context=self.context(), node_id=self.node_id,
                boot_generation=self.generation, report_id=self.inventory_id, page_index=page,
                receipts=receipts[page*64:(page+1)*64], last_page=(page+1)*64 >= len(receipts)), timeout=5)
        self.sequence = 0

    def maintain(self):
        registered = False
        while not self.stop_event.is_set():
            try:
                if not registered:
                    self.register_inventory()
                    registered = True
                self.sequence += 1
                self.registry.Heartbeat(n.HeartbeatRequest(context=self.context(), node_id=self.node_id,
                    boot_generation=self.generation, sequence=self.sequence, observed_at_unix_ms=now(), **self.metrics()), timeout=2)
                with self.store.transaction() as tx:
                    finished = [t for t in tx.all('task') if t['status']['state'] in ('FINISHED', 'FAILED') and not t.get('reported')]
            except Exception as exc:
                # A lost heartbeat reply does not mean that this incarnation lost its
                # registration. Keep increasing sequence numbers; a real control restart
                # explicitly rejects the unreconciled generation with VERSION_CONFLICT.
                import grpc
                from dfsha.common.rpc import controlled_error
                if isinstance(exc, grpc.RpcError) and controlled_error(exc)['reason'] in ('VERSION_CONFLICT', 'NOT_FOUND'):
                    registered = False
                from dfsha.common.telemetry import event
                event('node_control_retry', code=type(exc).__name__)
                finished = []
            # A task error must not revoke readiness of otherwise healthy stored blocks.
            for task in finished[:8]:
                try:
                    self.report_task(task)
                except Exception:
                    pass
            self.stop_event.wait(self.cfg.get('heartbeat_seconds', .5))

    def start(self):
        self.worker.start()

    def close(self):
        self.stop_event.set()
        self.worker.join(15)
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.channel.close()
        self.owner_lock.close()

    def authorize(self, header, ctx, write):
        request = n.AuthorizeBlockRequest(context=header.context, capability=header.capability,
            session_token=self.credentials(ctx), action=c.WRITE_DATA if write else c.READ_DATA,
            node_id=self.node_id, block=header.block, length=header.block.size_bytes)
        if write:
            request.operation.CopyFrom(header.operation)
            request.fence.CopyFrom(header.fence)
        else:
            request.handle_id = header.handle_id
            request.read_id = header.read_id
            request.snapshot.CopyFrom(header.snapshot)
            request.offset = header.offset if header.HasField('offset') else 0
            request.length = header.length if header.HasField('length') else header.block.size_bytes - request.offset
            need(request.offset <= header.block.size_bytes and 0 < request.length <= header.block.size_bytes - request.offset)
        decision = self.authorization.AuthorizeBlock(request, timeout=5)
        if not decision.HasField('replay_receipt'):
            need(ctx.time_remaining() <= DEADLINES[decision.block_size_bytes] + 2 and decision.valid_until_unix_ms > now())
        return decision

    def reserve(self, amount):
        with self.guard:
            m = self.metrics()
            need(m['used_bytes'] + self.reserved + amount <= self.cfg['capacity_bytes'] and
                 self.reserved + amount + 1048576 <= m['free_bytes'], 'NO_SPACE')
            self.reserved += amount

    def PutBlock(self, requests, ctx):
        first = next(requests, None)
        need(first is not None and first.WhichOneof('frame') == 'header')
        header = first.header
        decision = self.authorize(header, ctx, True)
        if decision.HasField('replay_receipt'):
            return decision.replay_receipt
        key = header.context.user_id + ':' + header.context.request_id
        with self.store.transaction() as tx:
            previous = tx.get('put_ledger', key)
        if previous:
            need(previous['digest'] == intent(header).hex(), 'IDEMPOTENCY_MISMATCH')
            receipt = proto(c.DurableReceipt, previous['receipt'])
        else:
            block = header.block
            amount = storage_cost(block.size_bytes)
            with self.coordinator.admit(decision.block_size_bytes), self.blocks.pin(block.block_version_id, exclusive=True):
                self.reserve(amount)
                try:
                    def chunks():
                        offset = 0
                        for frame in requests:
                            need(ctx.is_active() and now() < decision.valid_until_unix_ms, 'DEADLINE_EXCEEDED')
                            need(frame.WhichOneof('frame') == 'chunk' and frame.chunk.offset == offset and
                                 len(frame.chunk.data) == min(CHUNK, block.size_bytes - offset) and len(frame.chunk.data) > 0)
                            offset += len(frame.chunk.data)
                            yield frame.chunk.data
                    need(not self.fault('no_space'), 'NO_SPACE')
                    stored, digest = self.blocks.put(block, chunks())
                    self.fault('after_block_persist')
                    receipt = c.DurableReceipt(receipt_id=uid(), operation_id=header.operation.operation_id, block=block,
                        node_id=self.node_id, boot_generation=self.generation, failure_domain=self.cfg['failure_domain'],
                        stored_size_bytes=stored, ciphertext_sha256=digest, durable_at_unix_ms=now())
                    with self.store.transaction(True) as tx:
                        tx.put('block', dict(id=block.block_version_id, ref=asdict(block), stored_size=stored, receipt=asdict(receipt)))
                        tx.put('put_ledger', dict(id=key, digest=intent(header).hex(), receipt=asdict(receipt)))
                    self.count('client_write_bytes', block.size_bytes)
                finally:
                    with self.guard:
                        self.reserved -= amount
        self.registry.ReportDurable(n.ReportDurableRequest(context=self.context(), receipt=receipt,
            client_context=header.context, operation=header.operation, fence=header.fence), timeout=5)
        return receipt

    def PatchBlock(self, requests, ctx):
        if not self.cfg.get('rf3_enabled', False):
            import grpc
            from dfsha.common.rpc import abort
            abort(ctx, grpc.StatusCode.UNIMPLEMENTED, c.NOT_IMPLEMENTED_STAGE2)
        from dfsha.datanode.patch import patch_block
        return patch_block(self, requests, ctx)

    def GetBlock(self, req, ctx):
        decision = self.authorize(req, ctx, False)
        with self.store.transaction() as tx:
            record = tx.get('block', req.block.block_version_id)
            need(record and record['ref'] == asdict(req.block), 'DATA_UNAVAILABLE')
        total = 0
        start = req.offset if req.HasField('offset') else 0
        length = req.length if req.HasField('length') else req.block.size_bytes - start
        try:
            with self.coordinator.admit(decision.block_size_bytes), self.blocks.pin(req.block.block_version_id):
                chunks = self.blocks.read_verified(req.block)
                first = next(chunks, None)
                yield d.ReadBlockFrame(header=d.ReadBlockHeader(block=req.block, offset=start, length=length,
                    range_sha256=req.block.plaintext_sha256 if start == 0 and length == req.block.size_bytes else b''))
                import itertools
                position = 0
                for chunk in itertools.chain(() if first is None else (first,), chunks):
                    need(ctx.is_active() and now() < decision.valid_until_unix_ms, 'DEADLINE_EXCEEDED')
                    low, high = max(start, position), min(start + length, position + len(chunk))
                    if high > low:
                        payload = chunk[low-position:high-position]
                        yield d.ReadBlockFrame(chunk=d.DataChunk(offset=total, data=payload))
                        total += len(payload)
                        if self.cfg.get('replication_enabled') and total < length and self.fault('interrupt_get'):
                            raise Fault('DATA_UNAVAILABLE')
                    position += len(chunk)
                    if position >= start + length:
                        break
        finally:
            self.count('client_read_bytes', total)

    def control_peer(self, ctx, req):
        need(node_rpc.peer(ctx) == self.cfg['control_identity'] and req.context.user_id == self.cfg['control_identity'] and
             req.context.service_epoch == self.cfg['service_epoch'], 'PERMISSION_DENIED')

    def VerifyReceipt(self, req, ctx):
        self.control_peer(ctx, req)
        with self.store.transaction() as tx:
            record = tx.get('block', req.block.block_version_id)
        need(record and record['ref'] == asdict(req.block), 'NOT_FOUND')
        receipt = proto(c.DurableReceipt, record['receipt'])
        need(receipt.receipt_id == req.receipt_id and receipt.operation_id == req.operation_id and
             req.expected_boot_generation == self.generation, 'VERSION_CONFLICT')
        if req.verify_content:
            with self.coordinator.admit(min(b for b in DEADLINES if b >= req.block.size_bytes)), self.blocks.pin(req.block.block_version_id):
                for _ in self.blocks.read_verified(req.block):
                    pass
        return receipt

    def internal_authorize(self, task, action):
        return self.authorization.AuthorizeInternal(n.AuthorizeInternalRequest(context=self.context(),
            task_id=task.task_id, task_capability=task.task_capability, block=task.block, action=action,
            source_node_id=task.source.node_id, destination_node_id=task.destination.node_id, fence=task.fence), timeout=5)

    def ReplicateBlock(self, req, ctx):
        self.control_peer(ctx, req)
        need(req.destination == self.location(), 'VERSION_CONFLICT')
        self.internal_authorize(req, c.STORE_REPLICA)
        with self.guard:
            with self.store.transaction(True) as tx:
                task = tx.get('task', req.task_id)
                if task:
                    need(intent(proto(n.ReplicateBlockRequest, task['request'])) == intent(req), 'IDEMPOTENCY_MISMATCH')
                else:
                    need(len(self.jobs) < 2, 'LIMIT_EXCEEDED')
                    task = dict(id=req.task_id, request=asdict(req), status=asdict(n.TaskStatus(task_id=req.task_id, state=n.ACCEPTED)))
                    tx.put('task', task)
            if task['status']['state'] in ('ACCEPTED', 'RUNNING') and req.task_id not in self.jobs:
                self.jobs.add(req.task_id)
                self.pool.submit(self.copy, req)
        return proto(n.TaskStatus, task['status'])

    def copy(self, req):
        status = n.TaskStatus(task_id=req.task_id, state=n.FAILED, error_reason=c.DATA_UNAVAILABLE)
        reserved = False
        try:
            with self.coordinator.admit(min((b for b in DEADLINES if b >= req.block.size_bytes), default=134217728)), self.blocks.pin(req.block.block_version_id, exclusive=True):
                with self.store.transaction() as tx:
                    existing = tx.get('block', req.block.block_version_id)
                if req.replace_receipt_id and existing:
                    need(existing['receipt']['receipt_id'] == req.replace_receipt_id, 'VERSION_CONFLICT')
                    self.internal_authorize(req, c.STORE_REPLICA)
                    target = self.blocks.path(req.block.file_id, req.block.block_version_id)
                    quarantine = target.with_name(req.block.block_version_id+'.'+req.replace_receipt_id+'.quarantine')
                    if target.exists():
                        os.replace(target, quarantine)
                    with self.store.transaction(True) as tx:
                        tx.put('quarantine', dict(id=req.replace_receipt_id, ref=existing['ref'], stored_size=existing['stored_size']))
                        tx.delete('block', req.block.block_version_id)
                    existing = None
                if existing:
                    receipt = proto(c.DurableReceipt, existing['receipt'])
                    need(receipt.block == req.block and receipt.ciphertext_sha256 == req.ciphertext_sha256, 'CHECKSUM_MISMATCH')
                    for _ in self.blocks.read_verified(req.block):
                        pass
                    receipt.receipt_id, receipt.operation_id = uid(), req.task_id
                    receipt.boot_generation, receipt.durable_at_unix_ms = self.generation, now()
                    with self.store.transaction(True) as tx:
                        existing['receipt'] = asdict(receipt)
                        tx.put('block', existing)
                else:
                    self.reserve(storage_cost(req.block.size_bytes))
                    reserved = True
                    with node_rpc.channel(req.source.private_endpoint, self.cfg) as connection:
                        frames = dg.ReplicaServiceStub(connection).GetReplica(d.GetReplicaRequest(context=self.context(),
                            task_id=req.task_id, block=req.block, task_capability=req.task_capability, task_fence=req.fence,
                            destination_node_id=self.node_id), timeout=240)
                        first = next(frames)
                        need(first.WhichOneof('frame') == 'header' and first.header.block == req.block and
                             first.header.ciphertext_length == req.ciphertext_length and first.header.ciphertext_sha256 == req.ciphertext_sha256 and
                             first.header.key_id == self.blocks.key_id, 'CHECKSUM_MISMATCH')
                        def chunks():
                            offset = 0
                            for frame in frames:
                                need(frame.WhichOneof('frame') == 'chunk' and frame.chunk.offset == offset and now() < req.fence.expires_at_unix_ms)
                                offset += len(frame.chunk.data)
                                yield frame.chunk.data
                        self.blocks.import_ciphertext(req.block, chunks(), req.ciphertext_length, req.ciphertext_sha256)
                    receipt = c.DurableReceipt(receipt_id=uid(), operation_id=req.task_id, block=req.block,
                        node_id=self.node_id, boot_generation=self.generation, failure_domain=self.cfg['failure_domain'],
                        stored_size_bytes=req.ciphertext_length, ciphertext_sha256=req.ciphertext_sha256, durable_at_unix_ms=now())
                    with self.store.transaction(True) as tx:
                        tx.put('block', dict(id=req.block.block_version_id, ref=asdict(req.block), stored_size=req.ciphertext_length, receipt=asdict(receipt)))
                    self.count('replica_write_bytes', req.ciphertext_length)
                status = n.TaskStatus(task_id=req.task_id, state=n.FINISHED, receipt=receipt)
        except Exception as exc:
            from dfsha.common.telemetry import event
            event('copy_failed', code=type(exc).__name__)
        finally:
            with self.guard:
                if reserved:
                    self.reserved -= storage_cost(req.block.size_bytes)
                self.jobs.discard(req.task_id)
            with self.store.transaction(True) as tx:
                task = tx.get('task', req.task_id)
                task['status'] = asdict(status)
                tx.put('task', task)
            try:
                self.report_task(task)
            except Exception:
                pass  # Durable status is retried by maintenance.

    def GetReplica(self, req, ctx):
        need(node_rpc.peer(ctx) == req.destination_node_id and req.context.user_id == req.destination_node_id, 'PERMISSION_DENIED')
        decision = self.authorization.AuthorizeInternal(n.AuthorizeInternalRequest(context=self.context(),
            task_id=req.task_id, task_capability=req.task_capability, action=c.READ_REPLICA,
            source_node_id=self.node_id, destination_node_id=req.destination_node_id, block=req.block, fence=req.task_fence), timeout=5)
        with self.store.transaction() as tx:
            record = tx.get('block', req.block.block_version_id)
        need(record and record['ref'] == asdict(req.block), 'NOT_FOUND')
        receipt = proto(c.DurableReceipt, record['receipt'])
        offset = 0
        try:
            with self.coordinator.admit(min((b for b in DEADLINES if b >= req.block.size_bytes), default=134217728)), self.blocks.pin(req.block.block_version_id):
                yield d.ReplicaFrame(header=d.ReplicaHeader(task_id=req.task_id, block=req.block,
                    ciphertext_length=receipt.stored_size_bytes, ciphertext_sha256=receipt.ciphertext_sha256, key_id=self.blocks.key_id))
                with self.blocks.path(req.block.file_id, req.block.block_version_id).open('rb') as stream:
                    while chunk := stream.read(CHUNK):
                        need(ctx.is_active() and now() < decision.valid_until_unix_ms, 'DEADLINE_EXCEEDED')
                        yield d.ReplicaFrame(chunk=d.DataChunk(offset=offset, data=chunk))
                        offset += len(chunk)
        finally:
            self.count('replica_read_bytes', offset)

    def report_task(self, task):
        self.registry.ReportTask(n.ReportTaskRequest(context=self.context(), node_id=self.node_id,
            boot_generation=self.generation, task=proto(n.TaskStatus, task['status']),
            fence=proto(c.Fence, task['request']['fence']) if self.cfg.get('replication_enabled') else None), timeout=5)
        with self.store.transaction(True) as tx:
            task['reported'] = True
            tx.put('task', task)

    def GetTask(self, req, ctx):
        self.control_peer(ctx, req)
        with self.store.transaction() as tx:
            task = tx.get('task', req.task_id)
        need(task, 'NOT_FOUND')
        return proto(n.TaskStatus, task['status'])

    def DeleteRetiredBlock(self, req, ctx):
        self.control_peer(ctx, req)
        with self.store.transaction() as tx:
            old = tx.get('task', req.task_id)
        if old:
            need(intent(proto(n.DeleteRetiredBlockRequest, old['request'])) == intent(req), 'IDEMPOTENCY_MISMATCH')
            return proto(n.TaskStatus, old['status'])
        self.authorization.AuthorizeInternal(n.AuthorizeInternalRequest(context=self.context(), task_id=req.task_id,
            task_capability=req.task_capability, action=c.DELETE_RETIRED, destination_node_id=self.node_id,
            block=req.block, fence=req.fence), timeout=5)
        with self.blocks.pin(req.block.block_version_id, exclusive=True):
            if self.cfg.get('replication_enabled'):
                with self.store.transaction() as tx:
                    current = tx.get('block', req.block.block_version_id)
                need(not current or current['receipt']['receipt_id'] == req.expected_receipt_id, 'VERSION_CONFLICT')
                self.authorization.AuthorizeInternal(n.AuthorizeInternalRequest(context=self.context(), task_id=req.task_id,
                    task_capability=req.task_capability, action=c.DELETE_RETIRED, destination_node_id=self.node_id,
                    block=req.block, fence=req.fence), timeout=5)
            self.blocks.path(req.block.file_id, req.block.block_version_id).unlink(missing_ok=True)
            status = n.TaskStatus(task_id=req.task_id, state=n.FINISHED)
            task = dict(id=req.task_id, request=asdict(req), status=asdict(status))
            with self.store.transaction(True) as tx:
                tx.delete('block', req.block.block_version_id)
                tx.put('task', task)
        self.report_task(task)
        return status
