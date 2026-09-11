"""RF3 CQRS. Bloques fuera del control; publicación y fencing en una misma UoW."""
import hashlib
from dfsha.common.domain import need, Fault, uid, now, asdict, proto, manifest_hash, intent
from dfsha.control.auth import new_node
from dfsha.control.distributed import ClusterQueries, ClusterCommands, storage_cost
from dfsha.control.leases import MAX_DELTA, checked_range
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl

READ_MODES = (ctl.R, ctl.R_PLUS, ctl.W_PLUS, ctl.X_PLUS)
WRITE_MODES = (ctl.R_PLUS, ctl.W, ctl.W_PLUS, ctl.X, ctl.X_PLUS)


class AccessQueries(ClusterQueries):
    def handle(self, tx, user, session, identity):
        h = tx.get('handle', identity)
        need(h and h['user'] == user['id'] and h['session'] == session['id'] and
             not h['closed'] and self.app.leases.live(h), 'STALE_HANDLE')
        node = tx.get('node', h['file'])
        self.app.auth.require(tx, user, node, 4 if h['mode'] in READ_MODES else 2)
        for ancestor in h['ancestors']:
            self.app.auth.require(tx, user, tx.get('node', ancestor), 1)
        snap = tx.get('snapshot', h['snapshot'])
        need(snap, 'STALE_HANDLE')
        return h, snap

    def writable(self, tx, user, session, identity):
        h, snap = self.handle(tx, user, session, identity)
        need(h['mode'] in WRITE_MODES, 'PERMISSION_DENIED')
        node = tx.get('node', h['file'])
        self.app.auth.require(tx, user, node, 2)
        current = tx.get('snapshot', node['snapshot'])
        need(node['alive'] and current['ref']['content_epoch'] == snap['ref']['content_epoch'], 'VERSION_CONFLICT')
        return h, snap, node, current

    def ResolveBlocks(self, tx, user, session, req):
        h, snap = self.handle(tx, user, session, req.handle_id)
        need(h['mode'] in READ_MODES, 'PERMISSION_DENIED')
        need(not h.get('busy') or h['busy'] == req.read_id, 'HANDLE_BUSY')
        if req.read_id:
            self.validate_read(tx, h, req.read_id, req.offset, req.length)
        need(asdict(req.snapshot) == snap['ref'], 'VERSION_CONFLICT')
        offset = req.offset if req.HasField('offset') else 0
        length = req.length if req.HasField('length') else max(0, req.snapshot.size_bytes - offset)
        end = min(checked_range(offset, length), req.snapshot.size_bytes)
        need(1 <= req.page.limit <= 64)
        try:
            cursor = int(req.page.cursor or '0')
        except ValueError:
            raise Fault('INVALID_ARGUMENT') from None
        size = req.snapshot.block_size_bytes
        start_index = offset // size
        stop_index = (end + size - 1) // size if length and offset < end else start_index
        need(0 <= cursor <= max(0, stop_index - start_index))
        selected = snap['blocks'][start_index + cursor:min(stop_index, start_index + cursor + req.page.limit)]
        planned = []
        for value in selected:
            block = proto(c.BlockRef, value)
            plan = self.app.plan(block, user, h, read=True, tx=tx)
            low = max(0, offset - block.block_index * size)
            high = min(block.size_bytes, end - block.block_index * size)
            for grant in plan.grants:
                grant.offset, grant.length = low, high - low
                node = tx.get('datanode', grant.node_id)
                grant.capability = self.app.capability(user, h, block, node, f'read:{low}:{high-low}:{req.read_id}')
            planned.append(plan)
        next_index = cursor + len(planned)
        return ctl.BlockPlan(blocks=planned, snapshot=req.snapshot,
            next_cursor=str(next_index) if start_index + next_index < stop_index else '')

    def validate_read(self, tx, h, identity, offset, length):
        record = tx.get('read', identity)
        end = checked_range(offset, length)
        need(record and record['handle'] == h['id'] and record['session'] == h['session'] and
             h.get('busy') == identity and not record['closed'], 'HANDLE_BUSY')
        need(record['offset'] <= offset and end <= record['offset'] + record['length'], 'PERMISSION_DENIED')
        return record


class AccessCommands(ClusterCommands):
    def BeginRead(self, tx, user, session, req):
        h, snap = self.q.handle(tx, user, session, req.handle_id)
        need(h['mode'] in READ_MODES, 'PERMISSION_DENIED')
        need(not h.get('busy'), 'HANDLE_BUSY')
        need(asdict(req.snapshot) == snap['ref'], 'VERSION_CONFLICT')
        checked_range(req.offset, req.length)
        record = dict(id=uid(), handle=h['id'], session=session['id'], offset=req.offset, length=req.length, closed=False)
        tx.put('read', record)
        h['busy'] = record['id']
        tx.put('handle', h)
        return ctl.ReadLease(read_id=record['id'], snapshot=req.snapshot, expires_at_unix_ms=h['expires'])

    def EndRead(self, tx, user, session, req):
        h = tx.get('handle', req.handle_id)
        record = tx.get('read', req.read_id)
        need(h and record and record['handle'] == h['id'] and record['session'] == session['id'] and
             h['user'] == user['id'], 'PERMISSION_DENIED')
        record['closed'] = True
        tx.put('read', record)
        if h.get('busy') == record['id']:
            h['busy'] = None
            tx.put('handle', h)
        return self.result(req)

    def Open(self, tx, user, session, req):
        need(req.mode in READ_MODES + WRITE_MODES, 'UNSUPPORTED_MODE')
        creating = req.mode in (ctl.W, ctl.W_PLUS, ctl.X, ctl.X_PLUS)
        if creating:
            # Existing w requires traversal + file permissions; creation additionally needs parent wx.
            try:
                node = self.q.resolve(tx, user, req.path)
            except Fault as exc:
                if exc.reason != 'NOT_FOUND':
                    raise
                node = None
            parent, name = self.q.parent(tx, user, req.path) if node is None else (tx.get('node', node['parent']), node['name'])
            need(not node or req.mode not in (ctl.X, ctl.X_PLUS), 'ALREADY_EXISTS')
            need(not self.reserved(tx, parent['id'], name), 'LOCK_BUSY')
            if node:
                need(node['kind'] == 'file', 'IS_DIRECTORY')
                self.app.auth.require(tx, user, node, 6 if req.mode in READ_MODES else 2)
                old = tx.get('snapshot', node['snapshot'])
                owner = dict(id=uid(), file=node['id'], session=session['id'])
                lock = self.app.leases.acquire(tx, owner, whole=True, size=True, automatic=True)
                tx.delete('lock', lock['id'])  # Truncation is completely published in this same transaction.
                epoch, version = int(old['ref']['content_epoch']) + 1, int(old['ref']['file_version']) + 1
            else:
                node = new_node(name, parent['id'], user['id'], directory=False, mode=0o600)
                node['block_size'] = self.app.cfg['block_size_bytes']
                epoch, version = 1, 1
            root = uid()
            ref = c.SnapshotRef(file_id=node['id'], content_epoch=epoch, file_version=version,
                manifest_root=root, block_size_bytes=node['block_size'],
                manifest_sha256=manifest_hash([]), file_sha256=hashlib.sha256(b'').digest())
            tx.put('snapshot', dict(id=root, file=node['id'], ref=asdict(ref), blocks=[]))
            node['snapshot'] = root
            self.bump(tx, node)
            self.bump(tx, parent)
        else:
            node = self.q.resolve(tx, user, req.path)
            need(node['kind'] == 'file', 'IS_DIRECTORY')
            self.app.auth.require(tx, user, node, 6 if req.mode == ctl.R_PLUS else 4)
        ancestors, parent_id = [], node['parent']
        while parent_id:
            ancestors.append(parent_id)
            parent_id = tx.get('node', parent_id)['parent']
        h = dict(id=uid(), file=node['id'], snapshot=node['snapshot'], user=user['id'], session=session['id'],
                 revision=1, closed=False, ancestors=ancestors, mode=req.mode, busy=None)
        self.app.leases.refresh_handle(h, initial=True)
        tx.put('handle', h)
        return self.app.handle_message(tx, h)

    def RenewHandle(self, tx, user, session, req):
        h, _ = self.q.handle(tx, user, session, req.handle_id)
        self.app.leases.refresh_handle(h)
        tx.put('handle', h)
        op = tx.get('upload', h.get('busy', ''))
        if op and op.get('kind') == 'write' and op['state'] == c.PREPARING:
            op['expires'] = h['expires']
            tx.put('upload', op)
        return self.app.handle_message(tx, h)

    def Close(self, tx, user, session, req):
        h = tx.get('handle', req.handle_id)
        need(h and h['user'] == user['id'] and h['session'] == session['id'], 'STALE_HANDLE')
        if h['closed']:
            return self.result(req, h['revision'])
        need(not h.get('busy'), 'HANDLE_BUSY')
        h.update(closed=True, revision=h['revision'] + 1)
        tx.put('handle', h)
        for lock in tx.all('lock'):
            if lock['handle'] == h['id'] and lock['session'] == session['id']:
                tx.delete('lock', lock['id'])
        return self.result(req, h['revision'])

    def Lock(self, tx, user, session, req):
        h, snap, _, _ = self.q.writable(tx, user, session, req.handle_id)
        need(not h.get('busy'), 'HANDLE_BUSY')
        need(req.wait_timeout_ms <= 5000)
        if req.whole_file:
            need(not req.HasField('offset') and not req.HasField('length'))
            indices = []
        else:
            need(req.HasField('offset') and req.HasField('length') and req.length > 0)
            end = checked_range(req.offset, req.length, MAX_DELTA)
            size = int(snap['ref']['block_size_bytes'])
            indices = range(req.offset // size, (end - 1) // size + 1)
        lock = self.app.leases.acquire(tx, h, indices, whole=req.whole_file, size=req.whole_file)
        return self.app.leases.message(lock)

    def RenewLock(self, tx, user, session, req):
        self.q.writable(tx, user, session, req.fence.handle_id)
        lock = self.app.leases.validate(tx, session, req.fence)
        lock['deadline'] = self.app.leases.clock() + self.app.leases.lock_seconds
        tx.put('lock', lock)
        return self.app.leases.message(lock)

    def Unlock(self, tx, user, session, req):
        lock = self.app.leases.validate(tx, session, req.fence)
        need(not lock['active'], 'LOCK_BUSY')
        tx.delete('lock', lock['id'])
        return self.result(req)

    def write_operation(self, tx, user, session, reference):
        op = tx.get('upload', reference.operation_id)
        need(op and op.get('kind') == 'write' and op['user'] == user['id'] and op['session'] == session['id'], 'PERMISSION_DENIED')
        need(op['operation'] == asdict(reference), 'IDEMPOTENCY_MISMATCH')
        need(op['state'] == c.PREPARING and op['control_epoch'] == self.app.leases.epoch, 'OPERATION_EXPIRED')
        h, snap, node, current = self.q.writable(tx, user, session, op['handle'])
        need(h.get('busy') == op['id'] and h['revision'] == op['handle_revision'], 'HANDLE_BUSY')
        for value in op['fences']:
            self.app.leases.validate(tx, session, proto(c.Fence, value))
        return op, h, node, current

    def BeginWrite(self, tx, user, session, req):
        h, snap, node, current = self.q.writable(tx, user, session, req.handle_id)
        need(not h.get('busy'), 'HANDLE_BUSY')
        need(asdict(req.base) == snap['ref'], 'VERSION_CONFLICT')
        need(req.HasField('offset') and req.HasField('length') and len(req.delta_sha256) == 32)
        end = checked_range(req.offset, req.length, MAX_DELTA)
        need(req.offset <= req.base.size_bytes, 'SPARSE_WRITE_UNSUPPORTED')
        need(end <= self.app.cfg['max_file_bytes'], 'LIMIT_EXCEEDED')
        size, growing = req.base.block_size_bytes, end > req.base.size_bytes
        need(not growing or int(current['ref'].get('size_bytes', 0)) == req.base.size_bytes, 'VERSION_CONFLICT')
        parts, cursor = list(req.parts), 0
        need(len(parts) <= 5)
        for part in parts:
            absolute = req.offset + cursor
            expected = min(req.length - cursor, size - absolute % size)
            need(expected > 0 and part.block_index == absolute // size and part.block_offset == absolute % size and
                 part.delta_offset == cursor and part.length == expected and len(part.delta_sha256) == 32)
            cursor += part.length
        need(cursor == req.length and (req.length > 0 or req.delta_sha256 == hashlib.sha256(b'').digest()))
        for part in parts:
            index = part.block_index
            base = snap['blocks'][index] if index < len(snap['blocks']) else None
            latest = current['blocks'][index] if index < len(current['blocks']) else None
            need(base == latest, 'VERSION_CONFLICT')
        op_id = uid()
        reference = c.OperationRef(operation_id=op_id, request_id=req.context.request_id, intent_sha256=req.context.intent_sha256)
        locks, covered, has_size = [], set(), False
        need(len(req.fences) <= 6)
        for fence in req.fences:
            lock = self.app.leases.validate(tx, session, fence)
            need(lock['handle'] == h['id'], 'PERMISSION_DENIED')
            locks.append(lock)
            covered.update(p.block_index for p in parts) if lock['whole'] else covered.update(lock['indices'])
            has_size |= lock['size']
        # Recognize this owner's explicit locks even when SDK did not send a redundant token.
        for lock in tx.all('lock'):
            if self.app.leases.live(lock) and lock['handle'] == h['id'] and lock['session'] == session['id'] and not lock['automatic']:
                if lock['id'] not in [x['id'] for x in locks]:
                    locks.append(lock)
                    covered.update(p.block_index for p in parts) if lock['whole'] else covered.update(lock['indices'])
                    has_size |= lock['size']
        missing = sorted({p.block_index for p in parts} - covered)
        if missing or growing and not has_size:
            locks.append(self.app.leases.acquire(tx, h, missing, size=growing and not has_size, automatic=True))
        fences = [self.app.leases.message(x) for x in locks]
        op = dict(id=op_id, kind='write', operation=asdict(reference), request_id=req.context.request_id,
            user=user['id'], session=session['id'], parent=node['parent'], name=node['name'], file=node['id'],
            base=h['snapshot'], version=node['revision'], block_size=size, total=max(req.base.size_bytes, end),
            epoch=req.base.content_epoch, state=c.PREPARING, expires=h['expires'], max_expires=h['expires'],
            reserved=0, allocations={}, pages={}, sealed=None, handle=h['id'], handle_revision=h['revision'],
            control_epoch=self.app.leases.epoch, offset=req.offset, length=req.length, growing=growing,
            base_size=req.base.size_bytes, locks=[x['id'] for x in locks], fences=[asdict(x) for x in fences], parts=[], begin=asdict(req))
        tx.put('upload', op)
        planned = []
        for part in parts:
            index = part.block_index
            base = proto(c.BlockRef, snap['blocks'][index]) if index < len(snap['blocks']) else c.BlockRef(file_id=node['id'], block_index=index)
            replacement = c.BlockRef(file_id=node['id'], block_index=index, block_version_id=uid(),
                size_bytes=max(base.size_bytes, part.block_offset + part.length))
            # Prefer the confirmed local base. No client ever obtains its bytes to build a patch.
            if base.block_version_id:
                candidates = [tx.get('datanode', x['node']) for x in tx.all('location') if x['block'] == base.block_version_id]
                candidates = [x for x in candidates if self.app.state(x) == 'READY']
                need(candidates, 'DATA_UNAVAILABLE')
                chosen = None
                cost = storage_cost(replacement.size_bytes)
                for candidate in candidates:
                    used, reserved = self.app.usage(tx, candidate)
                    if used + reserved + cost <= candidate['capacity'] and reserved + cost + 1048576 <= candidate['free']:
                        chosen = candidate
                        break
                if chosen is None:
                    # Destination without the base: explicit, authorized E4 S/S copy task.
                    base_cost = storage_cost(base.size_bytes)
                    for candidate in sorted(tx.all('datanode'), key=lambda x: x['id']):
                        used, reserved = self.app.usage(tx, candidate)
                        if (self.app.state(candidate) == 'READY' and candidate not in candidates and
                            used + reserved + cost + base_cost <= candidate['capacity'] and
                            reserved + cost + base_cost + 1048576 <= candidate['free']):
                            chosen = candidate
                            break
                    need(chosen, 'NO_SPACE')
                    source = candidates[0]
                    location = self.app.location(tx, base.block_version_id, source['id'])
                    task = self.app.new_task('copy', asdict(base), source['id'], chosen['id'])
                    task.update(source=source['location'], destination=chosen['location'],
                        receipt=location['receipt'], reserved=base_cost, write_operation=op_id)
                    tx.put('task', task)
                tx.put('assignment', dict(id=replacement.block_version_id, node=chosen['id'], operation=op_id,
                    generation=int(chosen['location']['boot_generation']), reserved=cost))
            plan = self.app.plan(replacement, user, op, tx=tx)
            target = tx.get('datanode', plan.locations[0].node_id)
            plan.block.CopyFrom(base)
            plan.patch, plan.replacement_block_version_id = True, replacement.block_version_id
            plan.block_offset, plan.delta_offset, plan.delta_length = part.block_offset, part.delta_offset, part.length
            plan.grants[0].action = c.PATCH_DATA
            plan.grants[0].capability = self.app.capability(user, op, replacement, target, 'patch')
            op['allocations'][str(index)] = asdict(replacement)
            op['parts'].append(dict(part=asdict(part), base=asdict(base), replacement=asdict(replacement), plan=asdict(plan)))
            planned.append(plan)
            tx.put('upload', op)  # Subsequent reservations observe earlier parts of this operation.
        for lock in locks:
            lock['active'].append(op_id)
            tx.put('lock', lock)
        if req.length:
            h['busy'] = op_id
            tx.put('handle', h)
        else:
            op.update(state=c.COMMITTED, result=asdict(c.CommitResult(operation=reference, state=c.COMMITTED,
                snapshot=req.base, accepted_bytes=0, target_replicas=1, minimum_durable=1)))
            self.app.leases.release_operation(tx, op)
        tx.put('upload', op)
        return ctl.WritePlan(operation=reference, blocks=planned, fences=fences, base=req.base)

    def CommitWrite(self, tx, user, session, req):
        op, h, node, current = self.write_operation(tx, user, session, req.operation)
        need(req.handle_id == h['id'] and req.expected_handle_revision == h['revision'], 'VERSION_CONFLICT')
        need([intent(ctl.FenceRequest(fence=x)) for x in req.fences] ==
             [intent(ctl.FenceRequest(fence=proto(c.Fence, x))) for x in op['fences']], 'LOCK_EXPIRED')
        need(len(req.changes) == len(op['parts']), 'VERSION_CONFLICT')
        blocks = list(current['blocks'])
        for part, change in zip(op['parts'], req.changes):
            base, replacement = proto(c.BlockRef, part['base']), change.replacement
            index = base.block_index
            latest = blocks[index] if index < len(blocks) else asdict(c.BlockRef(file_id=node['id'], block_index=index))
            need(latest == part['base'] and asdict(change.base) == part['base'], 'VERSION_CONFLICT')
            expected = proto(c.BlockRef, part['replacement'])
            need(replacement.block_version_id == expected.block_version_id and replacement.file_id == expected.file_id and
                 replacement.block_index == index and replacement.size_bytes == expected.size_bytes, 'VERSION_CONFLICT')
            record = tx.get('block', replacement.block_version_id)
            assignment = tx.get('assignment', replacement.block_version_id)
            dn = tx.get('datanode', assignment['node'])
            need(record and record['ref'] == asdict(replacement) and self.app.location(tx, replacement.block_version_id, dn['id']) and
                 self.app.state(dn) in ('READY', 'SUSPECT') and assignment['generation'] == int(dn['location']['boot_generation']), 'DATA_UNAVAILABLE')
            need(len(change.receipts) == 1 and asdict(change.receipts[0]) == record['receipt'], 'CHECKSUM_MISMATCH')
            if index == len(blocks):
                blocks.append(asdict(replacement))
            else:
                blocks[index] = asdict(replacement)
        current_size = int(current['ref'].get('size_bytes', 0))
        need(not op['growing'] or current_size == op['base_size'], 'VERSION_CONFLICT')
        root = uid()
        ref = c.SnapshotRef(file_id=node['id'], content_epoch=op['epoch'],
            file_version=int(current['ref']['file_version']) + 1, manifest_root=root,
            size_bytes=max(current_size, op['total']), block_size_bytes=op['block_size'],
            manifest_sha256=manifest_hash([proto(c.BlockRef, x) for x in blocks]))
        tx.put('snapshot', dict(id=root, file=node['id'], ref=asdict(ref), blocks=blocks))
        node['snapshot'] = root
        self.bump(tx, node)
        h.update(snapshot=root, revision=h['revision'] + 1)
        tx.put('handle', h)
        result = c.CommitResult(operation=req.operation, state=c.COMMITTED, snapshot=ref,
            accepted_bytes=op['length'], target_replicas=1, minimum_durable=1)
        op.update(state=c.COMMITTED, result=asdict(result), reserved=0)
        tx.put('upload', op)
        self.app.leases.release_operation(tx, op)
        return result

    def AbortWrite(self, tx, user, session, req):
        op = tx.get('upload', req.operation.operation_id)
        need(op and op.get('kind') == 'write' and op['user'] == user['id'] and op['session'] == session['id'], 'PERMISSION_DENIED')
        need(op['operation'] == asdict(req.operation), 'IDEMPOTENCY_MISMATCH')
        need(op['state'] != c.COMMITTED, 'VERSION_CONFLICT')
        op.update(state=c.ABORTED, reserved=0)
        tx.put('upload', op)
        self.app.leases.release_operation(tx, op)
        return self.result(req)

    def BeginUpload(self, tx, user, session, req):
        plan = super().BeginUpload(tx, user, session, req)
        op = tx.get('upload', plan.operation.operation_id)
        owner = dict(id=op['id'], file=op['file'], session=session['id'])
        lock = self.app.leases.acquire(tx, owner, whole=True, size=True, automatic=True)
        # Full transfers renew with RenewUpload; unlike RF3 range leases they may last 5 minutes.
        lock['deadline'] = self.app.leases.clock() + 300
        lock['active'] = [op['id']]
        tx.put('lock', lock)
        op['locks'] = [lock['id']]
        op['full_fence'] = asdict(self.app.leases.message(lock))
        tx.put('upload', op)
        return plan

    def operation(self, tx, user, session, reference, fence=None):
        op = super().operation(tx, user, session, reference, fence)
        need(op.get('kind') != 'write', 'PERMISSION_DENIED')
        if op.get('full_fence'):
            self.app.leases.validate(tx, session, proto(c.Fence, op['full_fence']))
        return op

    def RenewUpload(self, tx, user, session, req):
        result = super().RenewUpload(tx, user, session, req)
        op = tx.get('upload', req.operation.operation_id)
        lock = self.app.leases.validate(tx, session, proto(c.Fence, op['full_fence']))
        lock['deadline'] = self.app.leases.clock() + max(0, (op['expires'] - now()) / 1000)
        tx.put('lock', lock)
        return result

    def CommitUpload(self, tx, user, session, req):
        op = tx.get('upload', req.operation.operation_id)
        previous = tx.get('snapshot', op['base']) if op['base'] else None
        result = super().CommitUpload(tx, user, session, req)
        result.snapshot.file_version = int(previous['ref']['file_version']) + 1 if previous else 1
        snapshot = tx.get('snapshot', result.snapshot.manifest_root)
        snapshot['ref'] = asdict(result.snapshot)
        tx.put('snapshot', snapshot)
        op = tx.get('upload', req.operation.operation_id)
        op['result'] = asdict(result)
        tx.put('upload', op)
        self.app.leases.release_operation(tx, tx.get('upload', req.operation.operation_id))
        return result

    def AbortUpload(self, tx, user, session, req):
        result = super().AbortUpload(tx, user, session, req)
        self.app.leases.release_operation(tx, tx.get('upload', req.operation.operation_id))
        return result

    def remove(self, tx, user, session, req, directory):
        result = super().remove(tx, user, session, req, directory)
        for op in tx.all('upload'):
            if op['state'] != c.PREPARING:
                self.app.leases.release_operation(tx, op)
        return result
