"""Composición RF3 del SDK; ni bases de bloques ni contenido atraviesan el control."""
from contextlib import contextmanager
import hashlib
import threading
import time
import grpc
from dfsha.common.domain import need, Fault, CHUNK, DEADLINES, intent
from dfsha.control.leases import checked_range, MAX_DELTA
from dfsha.common.rpc import channel
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl, data_pb2 as d, data_pb2_grpc as dg


class AccessClient:
    def open(self, path, mode='r'):
        modes = {'r': ctl.R, 'r+': ctl.R_PLUS, 'w': ctl.W, 'w+': ctl.W_PLUS, 'x': ctl.X, 'x+': ctl.X_PLUS}
        need(mode in modes, 'UNSUPPORTED_MODE')
        return self.call(self.files.Open, ctl.OpenRequest(path=self.path(path), mode=modes[mode]))

    def renew_handle(self, handle):
        updated = self.call(self.files.RenewHandle, ctl.HandleRequest(handle_id=handle.handle_id,
            expected_handle_revision=handle.revision))
        if updated.revision >= handle.revision:
            handle.CopyFrom(updated)
        return handle

    def lock(self, handle, offset=None, length=None, *, whole_file=False, wait_ms=0):
        if not whole_file:
            checked_range(offset, length, MAX_DELTA)
            need(length > 0)
        return self.call(self.files.Lock, ctl.LockRequest(handle_id=handle.handle_id,
            whole_file=whole_file, offset=offset, length=length, wait_timeout_ms=wait_ms), deadline=6, retries=0)

    def unlock(self, fence):
        return self.call(self.files.Unlock, ctl.FenceRequest(fence=fence))

    def renew_lock(self, fence):
        fence.CopyFrom(self.call(self.files.RenewLock, ctl.FenceRequest(fence=fence)))
        return fence

    def operation(self, operation_id='', request_id=''):
        return self.call(self.uploads.GetOperation, ctl.GetOperationRequest(operation_id=operation_id,
            original_request_id=request_id), retries=0)

    def iter_read(self, handle, offset, length):
        with self.handle_guard(handle):
            yield from self._read_serialized(handle, offset, length)

    def _read_serialized(self, handle, offset, length):
        checked_range(offset, length)
        lease = self.call(self.files.BeginRead, ctl.BeginReadRequest(handle_id=handle.handle_id,
            snapshot=handle.snapshot, offset=offset, length=length))
        try:
            yield from self._iter_read(handle, offset, length, lease.read_id)
        finally:
            self.call(self.files.EndRead, ctl.EndReadRequest(handle_id=handle.handle_id, read_id=lease.read_id))

    def _iter_read(self, handle, offset, length, read_id):
        end = checked_range(offset, length)
        # Even empty and EOF reads validate the remote identity, mode and current permissions.
        cursor = ''
        with self.keepalive(handle):
            while True:
                plan = self.call(self.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
                    snapshot=handle.snapshot, offset=offset, length=length, page=c.PageRequest(limit=64, cursor=cursor), read_id=read_id))
                need(plan.snapshot == handle.snapshot, 'VERSION_CONFLICT')
                for allocation in plan.blocks:
                    grant = allocation.grants[0]
                    expected_offset, expected_length = grant.offset, grant.length
                    received, digest, attempts = 0, hashlib.sha256(), 0
                    while received < expected_length:
                        location = next(x for x in allocation.locations if x.node_id == grant.node_id)
                        request = self.prepare(d.GetBlockRequest(handle_id=handle.handle_id, snapshot=handle.snapshot,
                            block=allocation.block, offset=grant.offset, length=grant.length, capability=grant.capability, read_id=read_id))
                        wire_position = 0
                        try:
                            with channel(location.client_endpoint, self.cert_dir) as transport:
                                stream = dg.BlockServiceStub(transport).GetBlock(request, metadata=self.metadata,
                                    timeout=DEADLINES[handle.snapshot.block_size_bytes])
                                first = next(stream, None)
                                need(first is not None and first.WhichOneof('frame') == 'header' and
                                     first.header.block == allocation.block and first.header.offset == grant.offset and
                                     first.header.length == grant.length, 'DATA_LOSS')
                                for frame in stream:
                                    need(frame.WhichOneof('frame') == 'chunk' and frame.chunk.offset == wire_position and
                                         0 < len(frame.chunk.data) <= CHUNK and wire_position + len(frame.chunk.data) <= grant.length, 'DATA_LOSS')
                                    wire_position += len(frame.chunk.data)
                                    received += len(frame.chunk.data)
                                    digest.update(frame.chunk.data)
                                    self.record_traffic(location.node_id, 'client_read_bytes', len(frame.chunk.data))
                                    yield frame.chunk.data
                                need(wire_position == grant.length, 'DATA_LOSS')
                        except grpc.RpcError as exc:
                            if exc.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED) or attempts >= 2:
                                raise
                            attempts += 1
                            if received == expected_length:
                                raise
                            position = allocation.block.block_index * handle.snapshot.block_size_bytes + expected_offset + received
                            fresh = self.call(self.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
                                snapshot=handle.snapshot, offset=position, length=expected_length-received, page=c.PageRequest(limit=1), read_id=read_id))
                            need(len(fresh.blocks) == 1 and fresh.blocks[0].block == allocation.block, 'DATA_UNAVAILABLE')
                            allocation = fresh.blocks[0]
                            grant = next((g for g in allocation.grants if g.node_id != location.node_id), allocation.grants[0])
                    if expected_offset == 0 and expected_length == allocation.block.size_bytes:
                        need(digest.digest() == allocation.block.plaintext_sha256, 'CHECKSUM_MISMATCH')
                if not plan.next_cursor:
                    return
                cursor = plan.next_cursor

    def read(self, handle, offset, length):
        # Convenience bounded allocation; iter_read is the API for arbitrary large ranges.
        checked_range(offset, length, MAX_DELTA)
        return b''.join(self.iter_read(handle, offset, length))

    def begin_write(self, handle, offset, payload, *, fences=(), request_id=None):
        checked_range(offset, len(payload), MAX_DELTA)
        need(offset <= handle.snapshot.size_bytes, 'SPARSE_WRITE_UNSUPPORTED')
        parts, cursor = [], 0
        size = handle.snapshot.block_size_bytes
        while cursor < len(payload):
            absolute = offset + cursor
            length = min(len(payload)-cursor, size-absolute % size)
            parts.append(ctl.WritePart(block_index=absolute // size, block_offset=absolute % size,
                delta_offset=cursor, length=length, delta_sha256=hashlib.sha256(payload[cursor:cursor+length]).digest()))
            cursor += length
        request = self.prepare(ctl.BeginWriteRequest(handle_id=handle.handle_id, base=handle.snapshot,
            offset=offset, length=len(payload), delta_sha256=hashlib.sha256(payload).digest(), parts=parts, fences=fences), request_id)
        return self.call(self.files.BeginWrite, request)

    def prepare_blocks(self, handle, plan, payload):
        changes = []
        for allocation in plan.blocks:
            piece = memoryview(payload)[allocation.delta_offset:allocation.delta_offset+allocation.delta_length]
            header = self.prepare(d.PatchBlockHeader(operation=plan.operation, base=allocation.block,
                new_block_version_id=allocation.replacement_block_version_id, block_offset=allocation.block_offset,
                delta_length=len(piece), delta_sha256=hashlib.sha256(piece).digest(), fence=plan.fences[0],
                capability=allocation.grants[0].capability))
            def frames():
                yield d.PatchBlockFrame(header=header)
                for start in range(0, len(piece), CHUNK):
                    yield d.PatchBlockFrame(chunk=d.DataChunk(offset=start, data=bytes(piece[start:start+CHUNK])))
            with channel(allocation.locations[0].client_endpoint, self.cert_dir) as transport:
                for attempt in range(3):
                    try:
                        receipt = dg.BlockServiceStub(transport).PatchBlock(frames(), metadata=self.metadata,
                            timeout=DEADLINES[handle.snapshot.block_size_bytes])
                        break
                    except grpc.RpcError as exc:
                        if exc.code() != grpc.StatusCode.UNAVAILABLE or attempt == 2:
                            raise
                        time.sleep(.1)
            need(receipt.operation_id == plan.operation.operation_id and receipt.node_id == allocation.locations[0].node_id and
                 receipt.block.block_version_id == allocation.replacement_block_version_id and
                 receipt.block.file_id == handle.snapshot.file_id and receipt.block.block_index == allocation.block.block_index and
                 len(receipt.block.plaintext_sha256) == 32, 'DATA_LOSS')
            changes.append(ctl.BlockChange(base=allocation.block, replacement=receipt.block, receipts=[receipt]))
            self.record_traffic(receipt.node_id, 'client_write_bytes', len(piece))
        return changes

    def commit_write(self, handle, plan, changes, request_id=None):
        request = self.prepare(ctl.CommitWriteRequest(operation=plan.operation, handle_id=handle.handle_id,
            changes=changes, fences=plan.fences, expected_handle_revision=handle.revision), request_id)
        self.last_commit_request = request
        try:
            result = self.call(self.files.CommitWrite, request, retries=0)
        except grpc.RpcError as exc:
            if exc.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED):
                raise
            try:
                status = self.operation(plan.operation.operation_id)
            except grpc.RpcError:
                raise Fault('OUTCOME_UNKNOWN') from None
            if status.state == c.COMMITTED:
                result = status.result
            elif status.state == c.PREPARING:
                result = self.call(self.files.CommitWrite, request, retries=0)
            else:
                raise Fault('OPERATION_EXPIRED') from None
        handle.snapshot.CopyFrom(result.snapshot)
        handle.revision += 1
        return result

    @contextmanager
    def write_keepalive(self, handle, plan):
        stop, failures = threading.Event(), []
        def renew():
            while not stop.wait(10):
                try:
                    self.renew_handle(handle)
                    for fence in plan.fences:
                        self.call(self.files.RenewLock, ctl.FenceRequest(fence=fence))
                except Exception as exc:
                    failures.append(exc)
                    return
        worker = threading.Thread(target=renew, daemon=True)
        worker.start()
        try:
            yield
            # Commit is the authority: a renewal racing with release after a successful
            # publication must not turn an already confirmed write into a reported failure.
        finally:
            stop.set()
            worker.join(12)

    def write(self, handle, offset, payload, *, fences=(), request_id=None):
        with self.handle_guard(handle):
            return self._write_serialized(handle, offset, payload, fences=fences, request_id=request_id)

    def _write_serialized(self, handle, offset, payload, *, fences=(), request_id=None):
        checked_range(offset, len(payload), MAX_DELTA)
        if request_id:
            try:
                previous = self.operation(request_id=request_id)
            except grpc.RpcError as exc:
                if exc.code() != grpc.StatusCode.NOT_FOUND:
                    raise
            else:
                original = previous.write_intent
                need(previous.HasField('write_intent') and original.handle_id == handle.handle_id and
                     original.offset == offset and original.length == len(payload) and
                     original.delta_sha256 == hashlib.sha256(payload).digest(), 'IDEMPOTENCY_MISMATCH')
                need([intent(ctl.FenceRequest(fence=f)) for f in original.fences] ==
                     [intent(ctl.FenceRequest(fence=f)) for f in fences], 'IDEMPOTENCY_MISMATCH')
                if previous.state == c.COMMITTED:
                    return previous.result.accepted_bytes
                need(previous.state == c.PREPARING, 'OPERATION_EXPIRED')
                plan = self.call(self.files.BeginWrite, original)
                return self._finish_write(handle, plan, payload)
        plan = self.begin_write(handle, offset, payload, fences=fences, request_id=request_id)
        return self._finish_write(handle, plan, payload)

    def _finish_write(self, handle, plan, payload):
        self.last_operation = plan.operation
        if not payload:
            return self.operation(plan.operation.operation_id).result.accepted_bytes
        with self.write_keepalive(handle, plan):
            try:
                changes = self.prepare_blocks(handle, plan, payload)
                return self.commit_write(handle, plan, changes).accepted_bytes
            except Exception as exc:
                # A failed status query does not authorize claiming that a commit was aborted.
                try:
                    status = self.operation(plan.operation.operation_id)
                    if status.state == c.COMMITTED:
                        handle.snapshot.CopyFrom(status.result.snapshot)
                        return status.result.accepted_bytes
                    if status.state == c.PREPARING:
                        self.call(self.files.AbortWrite, ctl.OperationRequest(operation=plan.operation), retries=0)
                except grpc.RpcError:
                    raise Fault('OUTCOME_UNKNOWN') from exc
                raise
