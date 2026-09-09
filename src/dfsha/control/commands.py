"""Comandos del dominio. Cada método recibe una UoW de escritura corta."""
import hashlib
import os
import re
import shutil
from dfsha.common.domain import asdict, proto, need, uid, now, manifest_hash, PROFILES
from dfsha.control.auth import password_hash, new_node
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl, identity_pb2 as ident


class Commands:
    def __init__(self, app):
        self.app, self.q = app, app.queries

    def bump(self, tx, node):
        node['revision'] += 1
        tx.put('node', node)

    def result(self, req, revision=1):
        return c.MutationResult(request_id=req.context.request_id, revision=revision)

    def reserved(self, tx, parent, name):
        return any(o['parent'] == parent and o['name'] == name and o['state'] == c.PREPARING
                   and o['expires'] > now() for o in tx.all('upload'))

    def Mkdir(self, tx, user, session, req):
        parent, name = self.q.parent(tx, user, req.path)
        need(not any(n['name'] == name for n in tx.children(parent['id'])), 'ALREADY_EXISTS')
        need(not self.reserved(tx, parent['id'], name), 'LOCK_BUSY')
        node = new_node(name, parent['id'], user['id'])
        tx.put('node', node)
        self.bump(tx, parent)
        return self.q.entry(tx, node)

    def Rmdir(self, tx, user, session, req):
        return self.remove(tx, user, session, req, True)

    def Remove(self, tx, user, session, req):
        return self.remove(tx, user, session, req, False)

    def remove(self, tx, user, session, req, directory):
        node = self.q.resolve(tx, user, req.path)
        need(node['parent'], 'ROOT_PROTECTED')
        need(node['kind'] == ('directory' if directory else 'file'),
             'NOT_DIRECTORY' if directory else 'IS_DIRECTORY')
        parent = tx.get('node', node['parent'])
        self.app.auth.require(tx, user, parent, 3)
        if directory:
            need(not tx.children(node['id']) and not any(o['parent'] == node['id'] and
                 o['state'] == c.PREPARING and o['expires'] > now() for o in tx.all('upload')), 'DIRECTORY_NOT_EMPTY')
        for op in tx.all('upload'):
            if op['file'] == node['id'] and op['state'] == c.PREPARING:
                op.update(state=c.ABORTED, reserved=0)
                tx.put('upload', op)
        node['alive'] = False
        self.bump(tx, node)
        self.bump(tx, parent)
        return self.result(req, node['revision'])

    def CreateUser(self, tx, user, session, req):
        need(user['admin'], 'PERMISSION_DENIED')
        need(re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', req.username) is not None)
        need(not any(u['username'] == req.username for u in tx.all('user')), 'ALREADY_EXISTS')
        identity = uid()
        encoded = password_hash(req.password)
        record = dict(id=identity, username=req.username, password=encoded, disabled=False, admin=False, revision=1)
        tx.put('user', record)
        tx.put('group', dict(id=identity, name=req.username, members=[identity], revision=1))
        home = self.q.walk(tx, user, '/home')
        need(not any(n['name'] == req.username for n in tx.children(home['id'])), 'ALREADY_EXISTS')
        tx.put('node', new_node(req.username, home['id'], identity))
        self.bump(tx, home)
        return ident.User(user_id=identity, username=req.username, revision=1)

    def SetUser(self, tx, user, session, req):
        need(user['admin'], 'PERMISSION_DENIED')
        target = tx.get('user', req.user_id)
        need(target, 'NOT_FOUND')
        need(not target['admin'], 'PERMISSION_DENIED')
        need(target['revision'] == req.expected_revision, 'VERSION_CONFLICT')
        target.update(disabled=req.disabled, revision=target['revision'] + 1)
        tx.put('user', target)
        return ident.User(user_id=target['id'], username=target['username'], disabled=target['disabled'], revision=target['revision'])

    def CreateGroup(self, tx, user, session, req):
        need(user['admin'], 'PERMISSION_DENIED')
        need(re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', req.name) is not None)
        need(not any(g['name'] == req.name for g in tx.all('group')), 'ALREADY_EXISTS')
        group = dict(id=uid(), name=req.name, members=[], revision=1)
        tx.put('group', group)
        return ident.Group(group_id=group['id'], name=req.name, revision=1)

    def SetGroupMembers(self, tx, user, session, req):
        need(user['admin'], 'PERMISSION_DENIED')
        group = tx.get('group', req.group_id)
        need(group, 'NOT_FOUND')
        need(group['revision'] == req.expected_revision, 'VERSION_CONFLICT')
        need(len(req.user_ids) <= 100 and len(set(req.user_ids)) == len(req.user_ids))
        need(all(tx.get('user', u) for u in req.user_ids), 'NOT_FOUND')
        group.update(members=list(req.user_ids), revision=group['revision'] + 1)
        tx.put('group', group)
        return ident.Group(group_id=group['id'], name=group['name'], user_ids=group['members'], revision=group['revision'])

    def SetAcl(self, tx, user, session, req):
        node = self.q.resolve(tx, user, req.path)
        need(user['admin'] or node['owner'] == user['id'], 'PERMISSION_DENIED')
        need(req.expected_revision == node['revision'], 'VERSION_CONFLICT')
        acl = req.acl
        need(acl.owner_permissions <= 7 and acl.group_permissions <= 7 and acl.other_permissions <= 7 and
             len(acl.entries) <= 64 and all(e.permissions <= 7 for e in acl.entries))
        need(tx.get('user', acl.owner_id) and tx.get('group', acl.group_id), 'NOT_FOUND')
        need(user['admin'] or acl.owner_id == node['owner'] and acl.group_id == node['group'], 'PERMISSION_DENIED')
        for entry in acl.entries:
            need(tx.get('group' if entry.is_group else 'user', entry.principal_id), 'NOT_FOUND')
        node.update(owner=acl.owner_id, group=acl.group_id,
                    mode=(acl.owner_permissions << 6) | (acl.group_permissions << 3) | acl.other_permissions,
                    acl=[asdict(e) for e in acl.entries])
        self.bump(tx, node)
        return self.result(req, node['revision'])

    def Logout(self, tx, user, session, req):
        need(req.session_id == session['session_id'], 'PERMISSION_DENIED')
        session['revoked'] = True
        tx.put('session', session)
        return self.result(req)

    def BeginUpload(self, tx, user, session, req):
        need(len(req.file_sha256) == 32 and req.total_bytes <= self.app.cfg['max_file_bytes'])
        parent, name = self.q.parent(tx, user, req.path)
        existing = next((n for n in tx.children(parent['id']) if n['name'] == name), None)
        need(not self.reserved(tx, parent['id'], name), 'LOCK_BUSY')
        if existing:
            need(existing['kind'] == 'file', 'IS_DIRECTORY')
            need(req.overwrite, 'ALREADY_EXISTS')
            self.app.auth.require(tx, user, existing, 2)
            snap = tx.get('snapshot', existing['snapshot'])
            need(asdict(req.expected_snapshot) == snap['ref'], 'VERSION_CONFLICT')
        else:
            need(not req.expected_snapshot.file_id, 'VERSION_CONFLICT')
        block_size = existing['block_size'] if existing else self.app.cfg['block_size_bytes']
        count = (req.total_bytes + block_size - 1) // block_size
        reserved = req.total_bytes + count * 4096 + ((req.total_bytes + 262143) // 262144) * 20
        pending = sum(o['reserved'] for o in tx.all('upload') if o['state'] == c.PREPARING)
        used = sum(b['stored_size'] for b in tx.all('block'))
        free = shutil.disk_usage(self.app.blocks.root).free
        need(reserved + pending + used <= self.app.cfg['capacity_bytes'] and
             reserved + pending + 1048576 <= free, 'NO_SPACE')
        operation_id = uid()
        operation = c.OperationRef(operation_id=operation_id, request_id=req.context.request_id,
                                   intent_sha256=req.context.intent_sha256)
        op = dict(id=operation_id, operation=asdict(operation), request_id=req.context.request_id,
            user=user['id'], session=session['id'], parent=parent['id'], name=name,
            file=existing['id'] if existing else uid(), base=existing['snapshot'] if existing else None,
            version=existing['revision'] if existing else 0, block_size=block_size, total=req.total_bytes,
            sha=req.file_sha256.hex(), state=c.PREPARING, expires=now() + 300000,
            max_expires=now() + 3600000, epoch=int(snap['ref']['content_epoch']) + 1 if existing else 1,
            reserved=reserved, allocations={}, pages={}, sealed=None)
        tx.put('upload', op)
        return self.app.upload_plan(op)

    def operation(self, tx, user, session, reference, fence=None):
        op = tx.get('upload', reference.operation_id)
        need(op and op['user'] == user['id'] and op['session'] == session['id'], 'PERMISSION_DENIED')
        need(asdict(reference) == op['operation'], 'VERSION_CONFLICT')
        need(op['state'] == c.PREPARING and op['expires'] > now(), 'OPERATION_EXPIRED')
        parent = tx.get('node', op['parent'])
        need(parent and parent['alive'], 'VERSION_CONFLICT')
        self.app.auth.require(tx, user, parent, 3)
        if op['base']:
            node = tx.get('node', op['file'])
            need(node and node['alive'] and node['snapshot'] == op['base'], 'VERSION_CONFLICT')
            self.app.auth.require(tx, user, node, 2)
        if fence is not None:
            need(fence.lock_id == op['id'] and fence.generation == op['epoch'] and
                 fence.service_epoch == self.app.system['epoch'], 'LOCK_EXPIRED')
        return op

    def RenewUpload(self, tx, user, session, req):
        op = self.operation(tx, user, session, req.operation)
        op['expires'] = min(now() + 300000, op['max_expires'])
        tx.put('upload', op)
        return self.app.upload_plan(op)

    def AllocateBlocks(self, tx, user, session, req):
        op = self.operation(tx, user, session, req.operation, req.fence)
        need(not op['sealed'], 'VERSION_CONFLICT')
        need(1 <= len(req.blocks) <= 64)
        planned = []
        for requested in req.blocks:
            index = requested.block_index
            size = min(op['block_size'], op['total'] - index * op['block_size'])
            need(size > 0 and requested.file_id == op['file'] and requested.size_bytes == size and
                 len(requested.plaintext_sha256) == 32 and not requested.block_version_id)
            previous = op['allocations'].get(str(index))
            if previous:
                block = proto(c.BlockRef, previous)
                need(block.size_bytes == size and block.plaintext_sha256 == requested.plaintext_sha256, 'VERSION_CONFLICT')
            else:
                block = c.BlockRef(file_id=op['file'], block_version_id=uid(), block_index=index,
                                   size_bytes=size, plaintext_sha256=requested.plaintext_sha256)
                op['allocations'][str(index)] = asdict(block)
            planned.append(self.app.plan(block, user, op))
        tx.put('upload', op)
        return ctl.BlockPlan(blocks=planned)

    def StageManifestPage(self, tx, user, session, req):
        op = self.operation(tx, user, session, req.operation, req.fence)
        need(not op['sealed'], 'VERSION_CONFLICT')
        count = (op['total'] + op['block_size'] - 1) // op['block_size']
        start = req.page_index * 64
        need(0 < len(req.blocks) <= 64 and req.ByteSize() <= 65536 and
             len(req.blocks) == min(64, count - start))
        for index, block in enumerate(req.blocks, start):
            need(block.block_index == index and op['allocations'].get(str(index)) == asdict(block), 'VERSION_CONFLICT')
            need(tx.get('block', block.block_version_id), 'DATA_UNAVAILABLE')
        need(manifest_hash(req.blocks) == req.page_sha256, 'CHECKSUM_MISMATCH')
        op['pages'][str(req.page_index)] = [asdict(b) for b in req.blocks]
        tx.put('upload', op)
        return ctl.PageReceipt(page_id=f'{op["id"]}:{req.page_index}', sha256=req.page_sha256, revision=1)

    def SealManifest(self, tx, user, session, req):
        op = self.operation(tx, user, session, req.operation, req.fence)
        blocks = self.app.manifest(op)
        need(req.block_count == len(blocks) and req.total_bytes == op['total'] and
             req.page_count == len(op['pages']) and req.manifest_sha256 == manifest_hash(blocks), 'CHECKSUM_MISMATCH')
        # Full content verification happens outside this transaction in transport.
        need(self.app.verified_seals.get(op['id']) == req.manifest_sha256, 'CHECKSUM_MISMATCH')
        receipt = ctl.PageReceipt(page_id=op['id'], sha256=req.manifest_sha256, revision=1)
        op['sealed'] = asdict(receipt)
        tx.put('upload', op)
        return receipt

    def CommitUpload(self, tx, user, session, req):
        op = self.operation(tx, user, session, req.operation, req.fence)
        need(op['sealed'] and op['sealed'] == asdict(req.seal), 'VERSION_CONFLICT')
        blocks = self.app.manifest(op)
        need(all(tx.get('block', b.block_version_id) for b in blocks), 'DATA_UNAVAILABLE')
        parent = tx.get('node', op['parent'])
        node = tx.get('node', op['file']) if op['base'] else None
        if not node:
            need(not any(n['name'] == op['name'] for n in tx.children(parent['id'])), 'VERSION_CONFLICT')
            node = new_node(op['name'], op['parent'], user['id'], directory=False, mode=0o600)
            node.update(id=op['file'], block_size=op['block_size'])
        snapshot_id = uid()
        ref = c.SnapshotRef(file_id=op['file'], content_epoch=op['epoch'], file_version=op['epoch'],
            manifest_root=snapshot_id, size_bytes=op['total'], manifest_sha256=req.seal.sha256,
            file_sha256=bytes.fromhex(op['sha']), block_size_bytes=op['block_size'])
        tx.put('snapshot', dict(id=snapshot_id, file=op['file'], ref=asdict(ref), blocks=[asdict(b) for b in blocks]))
        node['snapshot'] = snapshot_id
        self.bump(tx, node)
        self.bump(tx, parent)
        result = c.CommitResult(operation=req.operation, state=c.COMMITTED, snapshot=ref,
            accepted_bytes=op['total'], target_replicas=1, minimum_durable=1)
        op.update(state=c.COMMITTED, result=asdict(result), reserved=0)
        tx.put('upload', op)
        return result

    def AbortUpload(self, tx, user, session, req):
        op = tx.get('upload', req.operation.operation_id)
        need(op and op['user'] == user['id'] and op['session'] == session['id'], 'PERMISSION_DENIED')
        need(asdict(req.operation) == op['operation'], 'VERSION_CONFLICT')
        need(op['state'] != c.COMMITTED, 'VERSION_CONFLICT')
        op.update(state=c.ABORTED, reserved=0)
        tx.put('upload', op)
        return self.result(req)

    def Open(self, tx, user, session, req):
        need(req.mode == ctl.R, 'UNSUPPORTED_MODE')
        node = self.q.resolve(tx, user, req.path)
        need(node['kind'] == 'file', 'IS_DIRECTORY')
        self.app.auth.require(tx, user, node, 4)
        ancestors, parent = [], node['parent']
        while parent:
            ancestors.append(parent)
            parent = tx.get('node', parent)['parent']
        handle = dict(id=uid(), file=node['id'], snapshot=node['snapshot'], user=user['id'], session=session['id'],
                      expires=now() + 300000, revision=1, closed=False, ancestors=ancestors)
        tx.put('handle', handle)
        return self.app.handle_message(tx, handle)

    def RenewHandle(self, tx, user, session, req):
        handle, _ = self.q.handle(tx, user, session, req.handle_id)
        need(handle['revision'] == req.expected_handle_revision, 'VERSION_CONFLICT')
        handle.update(expires=now() + 300000, revision=handle['revision'] + 1)
        tx.put('handle', handle)
        return self.app.handle_message(tx, handle)

    def Close(self, tx, user, session, req):
        handle = tx.get('handle', req.handle_id)
        need(handle and handle['user'] == user['id'] and handle['session'] == session['id'], 'STALE_HANDLE')
        need(handle['revision'] == req.expected_handle_revision, 'VERSION_CONFLICT')
        handle.update(closed=True, revision=handle['revision'] + 1)
        tx.put('handle', handle)
        return self.result(req, handle['revision'])
