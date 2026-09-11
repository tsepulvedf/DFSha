"""COW autenticado. Delta <=16 MiB; la base y el resultado se procesan por fragmentos."""
from contextlib import ExitStack
import hashlib
import time
from dfsha.common.domain import need, Fault, uid, now, asdict, proto, intent, CHUNK, DEADLINES
from dfsha.control.distributed import storage_cost
from dfsha.control.leases import MAX_DELTA, checked_range
from dfsha.v1 import common_pb2 as c, data_pb2 as d, nodes_pb2 as n


def patch_block(node, requests, ctx):
    first = next(requests, None)
    need(first is not None and first.WhichOneof('frame') == 'header')
    header = first.header
    checked_range(header.block_offset, header.delta_length, MAX_DELTA)
    need(0 < header.delta_length <= MAX_DELTA and len(header.delta_sha256) == 32)
    decision = node.authorization.AuthorizeBlock(n.AuthorizeBlockRequest(context=header.context,
        session_token=node.credentials(ctx), node_id=node.node_id, action=c.PATCH_DATA,
        capability=header.capability, operation=header.operation, block=header.base,
        replacement_block_version_id=header.new_block_version_id, offset=header.block_offset,
        length=header.delta_length, delta_sha256=header.delta_sha256, fence=header.fence), timeout=5)
    if decision.HasField('replay_receipt'):
        return decision.replay_receipt
    need(ctx.time_remaining() <= DEADLINES[decision.block_size_bytes] + 2 and decision.valid_until_unix_ms > now())
    key = header.context.user_id + ':' + header.context.request_id
    if header.base.block_version_id:
        # The control may have scheduled its existing authenticated S/S copy primitive.
        # Wait for the durable inventory predicate, before taking the resource budget/pin
        # required by that copy itself (important for the one-slot 128 MiB profile).
        until = time.monotonic() + min(60, ctx.time_remaining())
        while True:
            with node.store.transaction() as tx:
                base = tx.get('block', header.base.block_version_id)
            if base:
                need(base['ref'] == asdict(header.base), 'DATA_LOSS')
                break
            need(ctx.is_active() and time.monotonic() < until and now() < decision.valid_until_unix_ms, 'DATA_UNAVAILABLE')
            node.stop_event.wait(.05)
    with node.coordinator.admit(decision.block_size_bytes), ExitStack() as stack:
        stack.enter_context(node.blocks.pin(header.new_block_version_id, exclusive=True))
        if header.base.block_version_id:
            while True:
                try:
                    stack.enter_context(node.blocks.pin(header.base.block_version_id))
                    break
                except Fault as exc:
                    if exc.reason != 'LOCK_BUSY':
                        raise
                    need(ctx.is_active() and time.monotonic() < until, 'DATA_UNAVAILABLE')
                    node.stop_event.wait(.02)
        with node.store.transaction() as tx:
            previous = tx.get('patch_ledger', key)
        if previous:
            need(previous['digest'] == intent(header).hex(), 'IDEMPOTENCY_MISMATCH')
            receipt = proto(c.DurableReceipt, previous['receipt'])
        else:
            amount = storage_cost(decision.replacement_size_bytes)
            node.reserve(amount)
            try:
                need(not node.fault('no_space'), 'NO_SPACE')
                delta = bytearray()
                for frame in requests:
                    need(ctx.is_active() and now() < decision.valid_until_unix_ms, 'DEADLINE_EXCEEDED')
                    need(frame.WhichOneof('frame') == 'chunk' and frame.chunk.offset == len(delta) and
                         0 < len(frame.chunk.data) <= CHUNK and len(delta) + len(frame.chunk.data) <= header.delta_length)
                    delta.extend(frame.chunk.data)
                need(len(delta) == header.delta_length and hashlib.sha256(delta).digest() == header.delta_sha256, 'CHECKSUM_MISMATCH')
                need(header.block_offset <= header.base.size_bytes, 'SPARSE_WRITE_UNSUPPORTED')
                if header.base.block_version_id:
                    with node.store.transaction() as tx:
                        base = tx.get('block', header.base.block_version_id)
                    need(base and base['ref'] == asdict(header.base), 'DATA_UNAVAILABLE')

                def result_chunks():
                    source = iter(node.blocks.read_verified(header.base)) if header.base.block_version_id else iter(())
                    pending = bytearray()
                    source_done = False
                    offset = 0
                    while offset < decision.replacement_size_bytes:
                        wanted = min(CHUNK, decision.replacement_size_bytes - offset)
                        while len(pending) < wanted and not source_done:
                            value = next(source, None)
                            if value is None:
                                source_done = True
                            else:
                                pending.extend(value)
                        # Any appended bytes are completely covered by the authorized delta.
                        chunk = bytearray(pending[:wanted])
                        del pending[:wanted]
                        if len(chunk) < wanted:
                            need(offset + len(chunk) >= header.block_offset and
                                 offset + wanted <= header.block_offset + len(delta), 'SPARSE_WRITE_UNSUPPORTED')
                            chunk.extend(b'\0' * (wanted - len(chunk)))
                        low = max(offset, header.block_offset)
                        high = min(offset + wanted, header.block_offset + len(delta))
                        if high > low:
                            chunk[low-offset:high-offset] = delta[low-header.block_offset:high-header.block_offset]
                        need(ctx.is_active() and now() < decision.valid_until_unix_ms, 'DEADLINE_EXCEEDED')
                        yield bytes(chunk)
                        offset += wanted

                digest = hashlib.sha256()
                for chunk in result_chunks():
                    digest.update(chunk)
                replacement = c.BlockRef(file_id=header.base.file_id, block_index=header.base.block_index,
                    block_version_id=header.new_block_version_id, size_bytes=decision.replacement_size_bytes,
                    plaintext_sha256=digest.digest())
                stored, cipher_digest = node.blocks.put(replacement, result_chunks())
                node.fault('after_block_persist')
                receipt = c.DurableReceipt(receipt_id=uid(), operation_id=header.operation.operation_id,
                    block=replacement, node_id=node.node_id, boot_generation=node.generation,
                    failure_domain=node.cfg['failure_domain'], stored_size_bytes=stored,
                    ciphertext_sha256=cipher_digest, durable_at_unix_ms=now())
                with node.store.transaction(True) as tx:
                    tx.put('block', dict(id=replacement.block_version_id, ref=asdict(replacement),
                        stored_size=stored, receipt=asdict(receipt)))
                    tx.put('patch_ledger', dict(id=key, digest=intent(header).hex(), receipt=asdict(receipt)))
                node.count('client_write_bytes', len(delta))
                node.count('patch_base_plaintext_processed_bytes', 4 * header.base.size_bytes)
                node.count('patch_result_processed_bytes', 2 * replacement.size_bytes)
                node.count('patch_ciphertext_stored_bytes', stored)
            finally:
                with node.guard:
                    node.reserved -= amount
    node.registry.ReportDurable(n.ReportDurableRequest(context=node.context(), receipt=receipt, patch=header), timeout=5)
    return receipt
