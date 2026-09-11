"""Autorización y recibos de PatchBlock por mTLS; nunca recibe contenido."""
import hmac
from dfsha.common import node_rpc
from dfsha.common.domain import need, asdict, proto, now, intent
from dfsha.v1 import common_pb2 as c, nodes_pb2 as n, data_pb2 as d, control_pb2 as ctl


def validate_header(app, tx, user, session, header, node):
    op, handle, _, _ = app.commands.write_operation(tx, user, session, header.operation)
    part = next((p for p in op['parts'] if p['replacement']['block_version_id'] == header.new_block_version_id), None)
    need(part, 'PERMISSION_DENIED')
    delta = proto(ctl.WritePart, part['part'])
    need(asdict(header.base) == part['base'] and header.block_offset == delta.block_offset and
         header.delta_length == delta.length and header.delta_sha256 == delta.delta_sha256, 'IDEMPOTENCY_MISMATCH')
    need(any(intent(ctl.FenceRequest(fence=header.fence)) ==
             intent(ctl.FenceRequest(fence=proto(c.Fence, value))) for value in op['fences']), 'LOCK_EXPIRED')
    assignment = tx.get('assignment', header.new_block_version_id)
    need(assignment and assignment['node'] == node['id'] and assignment['operation'] == op['id'] and
         assignment['generation'] == int(node['location']['boot_generation']), 'PERMISSION_DENIED')
    return op, part, assignment


def authorize_patch(app, req, ctx):
    need(hasattr(app, 'leases'), 'UNSUPPORTED_MODE')
    need(req.node_id in app.allowed and node_rpc.peer(ctx) == app.allowed[req.node_id]['identity'], 'PERMISSION_DENIED')
    header = d.PatchBlockHeader(context=req.context, operation=req.operation, base=req.block,
        new_block_version_id=req.replacement_block_version_id, block_offset=req.offset, delta_length=req.length,
        delta_sha256=req.delta_sha256, fence=req.fence, capability=req.capability)
    with app.store.transaction() as tx:
        user, session = app.authenticated(tx, req.session_token, req)
        node = tx.get('datanode', req.node_id)
        need(app.state(node) in ('READY', 'SUSPECT'), 'DATA_UNAVAILABLE')
        previous = app.replay(tx, user, header, 'PatchBlock', c.DurableReceipt)
        if previous:
            need(previous.node_id == node['id'], 'PERMISSION_DENIED')
            return n.AuthorizationDecision(replay_receipt=previous, valid_until_unix_ms=session['expires'])
        op, part, _ = validate_header(app, tx, user, session, header, node)
        replacement = proto(c.BlockRef, part['replacement'])
        need(hmac.compare_digest(req.capability, app.capability(user, op, replacement, node, 'patch')), 'PERMISSION_DENIED')
        return n.AuthorizationDecision(subject_id=user['id'], authz_revision=1,
            valid_until_unix_ms=min(session['expires'], app.leases.expiry_hint(tx.get('handle', op['handle']))), block_size_bytes=op['block_size'],
            replacement_size_bytes=replacement.size_bytes)


def report_patch(app, req, ctx):
    need(hasattr(app, 'leases'), 'UNSUPPORTED_MODE')
    receipt, header = req.receipt, req.patch
    app.node_peer(ctx, req, receipt.node_id)
    with app.store.transaction(True) as tx:
        node = tx.get('datanode', receipt.node_id)
        need(node and receipt.boot_generation == int(node['location']['boot_generation']), 'VERSION_CONFLICT')
        user = tx.get('user', header.context.user_id)
        need(user and not user['disabled'] and header.context.service_epoch == app.system['epoch'], 'UNAUTHENTICATED')
        previous = app.replay(tx, user, header, 'PatchBlock', c.DurableReceipt)
        if previous:
            need(previous == receipt, 'IDEMPOTENCY_MISMATCH')
            return c.MutationResult(request_id=req.context.request_id, revision=1)
        op = tx.get('upload', receipt.operation_id)
        session = tx.get('session', op['session']) if op else None
        need(session and not session['revoked'] and session['expires'] > now(), 'UNAUTHENTICATED')
        op, part, assignment = validate_header(app, tx, user, session, header, node)
        expected = proto(c.BlockRef, part['replacement'])
        block = receipt.block
        need(receipt.operation_id == op['id'] and block.file_id == expected.file_id and
             block.block_version_id == expected.block_version_id and block.block_index == expected.block_index and
             block.size_bytes == expected.size_bytes and len(block.plaintext_sha256) == 32 and
             len(receipt.ciphertext_sha256) == 32 and receipt.failure_domain == node['location']['failure_domain'] and
             block.size_bytes < receipt.stored_size_bytes <= assignment['reserved'], 'CHECKSUM_MISMATCH')
        tx.put('block', dict(id=block.block_version_id, file=block.file_id, operation=op['id'], ref=asdict(block),
            stored_size=receipt.stored_size_bytes, receipt=asdict(receipt)))
        app.confirm_location(tx, receipt, node['inventory_id'])
        app.remember(tx, user, header, 'PatchBlock', receipt)
    return c.MutationResult(request_id=req.context.request_id, revision=1)
