"""Adaptador de control E4. Reutiliza CQRS H1; sólo metadatos y recibos en este proceso."""
import hashlib
import hmac
import json
from pathlib import Path
import threading

from dfsha.common.domain import need, now, uid, uuid, asdict, proto, CHUNK, intent
from dfsha.common import node_rpc
from dfsha.control.monolith import Monolith
from dfsha.control.commands import Commands
from dfsha.control.queries import Queries
from dfsha.v1 import common_pb2 as c, nodes_pb2 as n, nodes_pb2_grpc as ng, data_pb2 as d


def storage_cost(length):
    return length + 4096 + ((length + CHUNK - 1) // CHUNK) * 20


class NoContentStore:
    """No instancia ni conoce un cifrador de contenido en el ControlNode."""
    def collect(self, retained):
        pass


class ClusterQueries(Queries):
    def ListNodes(self, tx, user, session, req):
        need(user['admin'], 'PERMISSION_DENIED')
        limit = req.page.limit or 64
        need(1 <= limit <= 64)
        records = [x for x in tx.all('datanode') if x['id'] > req.page.cursor]
        result = []
        for node in records[:limit]:
            used, reserved = self.app.usage(tx, node)
            result.append(n.NodeStatus(node=proto(c.BlockLocation, node['location']), state=self.app.state(node),
                capacity_bytes=node['capacity'], used_bytes=used, reserved_bytes=reserved, free_bytes=node['free'],
                active_streams=node.get('active', 0), last_heartbeat_unix_ms=node['seen'],
                confirmed_blocks=sum(x['node'] == node['id'] for x in tx.all('location')),
                **{key: node.get(key, 0) for key in self.app.counters}))
        return n.NodeStatusPage(nodes=result, next_cursor=records[limit-1]['id'] if len(records) > limit else '')

    def CopyStatus(self, tx, user, session, req):
        need(user['admin'], 'PERMISSION_DENIED')
        task = tx.get('task', uuid(req.task_id))
        need(task, 'NOT_FOUND')
        return proto(n.TaskStatus, task['status'])


class ClusterCommands(Commands):
    def CopyBlock(self, tx, user, session, req):
        need(user['admin'], 'PERMISSION_DENIED')
        block = tx.get('block', uuid(req.block.block_version_id))
        need(block and block['ref'] == asdict(req.block), 'NOT_FOUND')
        source = self.app.location(tx, req.block.block_version_id, req.source_node_id)
        dest = tx.get('datanode', req.destination_node_id)
        need(source and dest and self.app.state(dest) == 'READY' and
             req.source_node_id != req.destination_node_id, 'DATA_UNAVAILABLE')
        need(not self.app.location(tx, req.block.block_version_id, dest['id']), 'ALREADY_EXISTS')
        source_node = tx.get('datanode', req.source_node_id)
        need(self.app.state(source_node) == 'READY', 'DATA_UNAVAILABLE')
        used, reserved = self.app.usage(tx, dest)
        cost = storage_cost(req.block.size_bytes)
        need(used + reserved + cost <= dest['capacity'] and reserved + cost <= dest['free'], 'NO_SPACE')
        task = self.app.new_task('copy', block['ref'], source['node'], dest['id'])
        task.update(source=source_node['location'], destination=dest['location'],
                    receipt=source['receipt'], reserved=cost)
        tx.put('task', task)
        return proto(n.TaskStatus, task['status'])

    def CommitUpload(self, tx, user, session, req):
        op = self.operation(tx, user, session, req.operation, req.fence)
        for value in op['allocations'].values():
            if hasattr(self.app, 'require_durable'):
                self.app.require_durable(tx, op, proto(c.BlockRef, value))
                continue
            assignment = tx.get('assignment', value['block_version_id'])
            node = tx.get('datanode', assignment['node']) if assignment else None
            need(node and self.app.state(node) in ('READY', 'SUSPECT') and
                 int(node['location']['boot_generation']) == assignment['generation'], 'DATA_UNAVAILABLE')
        return super().CommitUpload(tx, user, session, req)


class DistributedControl(Monolith):
    serves_content = False
    counters = ('client_write_bytes', 'client_read_bytes', 'replica_write_bytes', 'replica_read_bytes')

    def __init__(self, cfg):
        self.allowed = json.loads(Path(cfg['authorized_nodes_path']).read_text(encoding='utf-8'))
        super().__init__(cfg)
        self.queries = ClusterQueries(self)
        self.commands = ClusterCommands(self)
        if cfg.get('rf3_enabled', False):
            from dfsha.control.leases import SQLiteLeaseAuthority
            from dfsha.control.access import AccessQueries, AccessCommands
            self.leases = SQLiteLeaseAuthority(self)
            self.queries = AccessQueries(self)
            self.commands = AccessCommands(self)
        self.cfg['service_epoch'] = self.system['epoch']
        self.dispatch_lock = threading.Lock()
        with self.store.transaction(True) as tx:
            for node in tx.all('datanode'):
                node.update(seen=0, reconciled=False)
                tx.put('datanode', node)

    def make_blocks(self, root, key):
        return NoContentStore()

    def reserve_upload(self, tx, total, block_size):
        return 0  # Capacity is reserved atomically per allocated block, not twice.

    def verify_seal(self, op, blocks, context):
        with self.store.transaction() as tx:
            for block in blocks:
                record = tx.get('block', block.block_version_id)
                need(record and record['ref'] == asdict(block) and any(
                    x['block'] == block.block_version_id for x in tx.all('location')), 'DATA_UNAVAILABLE')

    def state(self, node):
        if not node or now() - node['seen'] > self.cfg.get('unavailable_ms', 6000):
            return 'UNAVAILABLE'
        if not node['reconciled']:
            return 'STARTING'
        return 'SUSPECT' if now() - node['seen'] > self.cfg.get('suspect_ms', 2500) else 'READY'

    def usage(self, tx, node):
        copies = sum(int(x['receipt']['stored_size_bytes']) for x in tx.all('location') if x['node'] == node['id'])
        used = max(node.get('used', 0), copies)
        reserved = 0
        for a in tx.all('assignment'):
            op = tx.get('upload', a['operation'])
            if a['node'] == node['id'] and not self.location(tx, a['id'], a['node']) and self.operation_live(tx, op):
                reserved += a['reserved']
        reserved += sum(t.get('reserved', 0) for t in tx.all('task') if t['dest'] == node['id'] and
                        t['expires'] > now() and t['status']['state'] in ('ACCEPTED', 'RUNNING'))
        return used, reserved

    def location(self, tx, block, node):
        return tx.get('location', block + ':' + node)

    def capability(self, user, binding, block, node, action):
        return self.auth.capability(user['id'], binding['id'], block.block_version_id,
            ':'.join((action, node['id'], node['location']['boot_generation'], binding['session'])))

    def plan(self, block, user, binding, read=False, tx=None):
        if read:
            nodes = [tx.get('datanode', x['node']) for x in tx.all('location') if x['block'] == block.block_version_id]
            nodes = [x for x in nodes if self.state(x) in ('READY', 'SUSPECT')]
            need(nodes, 'DATA_UNAVAILABLE')
        else:
            assignment = tx.get('assignment', block.block_version_id)
            if not assignment:
                cost = storage_cost(block.size_bytes)
                candidates = []
                for node in tx.all('datanode'):
                    used, reserved = self.usage(tx, node)
                    if self.state(node) == 'READY' and used + reserved + cost <= node['capacity'] and reserved + cost + 1048576 <= node['free']:
                        candidates.append((int(20 * (used + reserved) / node['capacity']), node.get('active', 0), node))
                need(candidates, 'NO_SPACE')
                best = min((band, active) for band, active, _ in candidates)
                pool = sorted([x for band, active, x in candidates if (band, active) == best], key=lambda x: x['id'])
                rotation = tx.get('settings', 'placement') or dict(id='placement', last='')
                chosen = next((x for x in pool if x['id'] > rotation['last']), pool[0])
                rotation['last'] = chosen['id']
                tx.put('settings', rotation)
                assignment = dict(id=block.block_version_id, node=chosen['id'], operation=binding['id'],
                                  generation=int(chosen['location']['boot_generation']), reserved=cost)
                tx.put('assignment', assignment)
            nodes = [tx.get('datanode', assignment['node'])]
            need(self.state(nodes[0]) in ('READY', 'SUSPECT') and int(nodes[0]['location']['boot_generation']) == assignment['generation'], 'DATA_UNAVAILABLE')
        return c.PlannedBlock(block=block, locations=[proto(c.BlockLocation, x['location']) for x in nodes],
            grants=[c.BlockGrant(block=block, node_id=x['id'], length=block.size_bytes,
                action=c.READ_DATA if read else c.WRITE_DATA, expires_at_unix_ms=binding['expires'],
                capability=self.capability(user, binding, block, x, 'read' if read else 'write')) for x in nodes],
            reservation=None if read else c.StorageReservation(reservation_id=block.block_version_id,
                operation_id=binding['id'], node_id=nodes[0]['id'], bytes=assignment['reserved'], expires_at_unix_ms=binding['expires']))

    def node_peer(self, context, request, node_id):
        need(node_id in self.allowed and node_rpc.peer(context) == self.allowed[node_id]['identity'] and
             request.context.user_id == node_id and request.context.service_epoch == self.system['epoch'], 'PERMISSION_DENIED')
        uuid(request.context.request_id)

    def lease(self, node):
        return n.NodeLease(node_id=node['id'], boot_generation=int(node['location']['boot_generation']),
                           expires_at_unix_ms=node['seen'] + self.cfg.get('suspect_ms', 2500), revision=node['sequence'])

    def RegisterNode(self, req, ctx):
        self.node_peer(ctx, req, req.node.node_id)
        uuid(req.inventory_id)
        allow = self.allowed[req.node.node_id]
        need(req.node.client_endpoint == allow['client_endpoint'] and req.node.private_endpoint == allow['private_endpoint'] and
             req.node.failure_domain == allow['failure_domain'] and req.capacity_bytes == allow['capacity_bytes'] and
             req.node.boot_generation > 0, 'PERMISSION_DENIED')
        with self.store.transaction(True) as tx:
            old = tx.get('datanode', req.node.node_id)
            if old:
                need(req.node.boot_generation >= int(old['location']['boot_generation']), 'VERSION_CONFLICT')
                if req.node.boot_generation == int(old['location']['boot_generation']):
                    need(old['location'] == asdict(req.node) and old['inventory_id'] == req.inventory_id, 'VERSION_CONFLICT')
                else:
                    for a in tx.all('assignment'):
                        if a['node'] == req.node.node_id:
                            op = tx.get('upload', a['operation'])
                            if op and op['state'] == c.PREPARING:
                                op.update(state=c.ABORTED, reserved=0)
                                tx.put('upload', op)
            node = dict(id=req.node.node_id, location=asdict(req.node), capacity=req.capacity_bytes,
                        free=req.free_bytes, used=0, seen=now(), sequence=0, reconciled=False,
                        inventory_id=req.inventory_id, page=0)
            tx.put('datanode', node)
            return self.lease(node)

    def Heartbeat(self, req, ctx):
        self.node_peer(ctx, req, req.node_id)
        with self.store.transaction(True) as tx:
            node = tx.get('datanode', req.node_id)
            need(node and node['reconciled'] and int(node['location']['boot_generation']) == req.boot_generation and
                 req.sequence > node['sequence'], 'VERSION_CONFLICT')
            node.update(seen=now(), sequence=req.sequence, free=req.free_bytes, used=req.used_bytes, active=req.active_streams)
            node.update({key: getattr(req, key) for key in self.counters})
            tx.put('datanode', node)
            return self.lease(node)

    def BlockReport(self, req, ctx):
        self.node_peer(ctx, req, req.node_id)
        need(len(req.receipts) <= 64 and req.ByteSize() <= 65536)
        with self.store.transaction(True) as tx:
            node = tx.get('datanode', req.node_id)
            need(node and int(node['location']['boot_generation']) == req.boot_generation and
                 req.report_id == node['inventory_id'] and req.page_index == node['page'], 'VERSION_CONFLICT')
            for receipt in req.receipts:
                need(receipt.node_id == req.node_id and len(receipt.ciphertext_sha256) == 32)
                old = self.location(tx, receipt.block.block_version_id, req.node_id)
                if old:
                    need(old['receipt'] == asdict(receipt), 'CHECKSUM_MISMATCH')
                    old['inventory'] = req.report_id
                    tx.put('location', old)
                else:
                    # An unconfirmed object never becomes a namespace entry merely by reporting it.
                    self.retire_copy(tx, asdict(receipt.block), req.node_id)
            node.update(page=node['page'] + 1, seen=now(), reconciled=req.last_page)
            if req.last_page:
                for loc in tx.all('location'):
                    if loc['node'] == req.node_id and loc.get('inventory') != req.report_id:
                        tx.delete('location', loc['id'])
            tx.put('datanode', node)
        return c.MutationResult(request_id=req.context.request_id, revision=req.page_index + 1)

    def AuthorizeBlock(self, req, ctx):
        if req.action == c.PATCH_DATA:
            from dfsha.control.patch_authority import authorize_patch
            return authorize_patch(self, req, ctx)
        # RequestContext is the original user's context; authenticated transport identifies the DN.
        need(req.node_id in self.allowed and node_rpc.peer(ctx) == self.allowed[req.node_id]['identity'], 'PERMISSION_DENIED')
        with self.store.transaction() as tx:
            user, session = self.authenticated(tx, req.session_token, req)
            node = tx.get('datanode', req.node_id)
            need(self.state(node) in ('READY', 'SUSPECT'), 'DATA_UNAVAILABLE')
            if req.action == c.WRITE_DATA:
                header = d.PutBlockHeader(context=req.context, operation=req.operation, block=req.block, fence=req.fence, capability=req.capability)
                replay = self.replay(tx, user, header, 'PutBlock', c.DurableReceipt)
                if replay:
                    need(replay.node_id == node['id'], 'PERMISSION_DENIED')
                    return n.AuthorizationDecision(subject_id=user['id'], replay_receipt=replay, valid_until_unix_ms=session['expires'])
                binding = self.commands.operation(tx, user, session, req.operation, req.fence)
                assignment = tx.get('assignment', req.block.block_version_id)
                need(assignment and assignment['node'] == node['id'] and assignment['generation'] == int(node['location']['boot_generation']) and
                     binding['allocations'].get(str(req.block.block_index)) == asdict(req.block), 'PERMISSION_DENIED')
                size, action = binding['block_size'], 'write'
            elif req.action == c.READ_DATA:
                binding, snap = self.queries.handle(tx, user, session, req.handle_id)
                if hasattr(self, 'leases'):
                    from dfsha.control.access import READ_MODES
                    need(binding['mode'] in READ_MODES and (not binding.get('busy') or binding['busy'] == req.read_id), 'PERMISSION_DENIED')
                    if req.read_id:
                        self.queries.validate_read(tx, binding, req.read_id,
                            req.block.block_index * int(snap['ref']['block_size_bytes']) + req.offset, req.length)
                need(snap['ref'] == asdict(req.snapshot) and asdict(req.block) in snap['blocks'] and
                     self.location(tx, req.block.block_version_id, node['id']), 'PERMISSION_DENIED')
                size, action = int(snap['ref']['block_size_bytes']), 'read'
            else:
                need(False, 'PERMISSION_DENIED')
            if hasattr(self, 'leases') and req.action == c.READ_DATA:
                need(req.offset <= req.block.size_bytes and 0 < req.length <= req.block.size_bytes - req.offset)
                action = f'read:{req.offset}:{req.length}:{req.read_id}'
            else:
                need(req.offset == 0 and req.length == req.block.size_bytes, 'UNSUPPORTED_MODE')
            need(hmac.compare_digest(req.capability, self.capability(user, binding, req.block, node, action)), 'PERMISSION_DENIED')
            expiry = self.leases.expiry_hint(binding) if hasattr(self, 'leases') and req.action == c.READ_DATA else binding['expires']
            return n.AuthorizationDecision(subject_id=user['id'], authz_revision=1, block_size_bytes=size,
                valid_until_unix_ms=min(session['expires'], expiry))

    def ReportDurable(self, req, ctx):
        if req.HasField('patch'):
            from dfsha.control.patch_authority import report_patch
            return report_patch(self, req, ctx)
        receipt = req.receipt
        self.node_peer(ctx, req, receipt.node_id)
        with self.store.transaction(True) as tx:
            node = tx.get('datanode', receipt.node_id)
            need(node and receipt.boot_generation == int(node['location']['boot_generation']), 'VERSION_CONFLICT')
            user = tx.get('user', req.client_context.user_id)
            need(user and not user['disabled'] and req.client_context.service_epoch == self.system['epoch'], 'UNAUTHENTICATED')
            uuid(req.client_context.request_id)
            header = d.PutBlockHeader(context=req.client_context, operation=req.operation, block=receipt.block, fence=req.fence)
            previous = self.replay(tx, user, header, 'PutBlock', c.DurableReceipt)
            if previous:
                need(previous == receipt, 'IDEMPOTENCY_MISMATCH')
                return c.MutationResult(request_id=req.context.request_id, revision=1)
            op = tx.get('upload', receipt.operation_id)
            session = tx.get('session', op['session']) if op else None
            need(session and not session['revoked'] and session['expires'] > now(), 'UNAUTHENTICATED')
            op = self.commands.operation(tx, user, session, req.operation, req.fence)
            assignment = tx.get('assignment', receipt.block.block_version_id)
            need(assignment and assignment['node'] == node['id'] and assignment['generation'] == receipt.boot_generation and
                 assignment['operation'] == op['id'] and op['allocations'].get(str(receipt.block.block_index)) == asdict(receipt.block), 'VERSION_CONFLICT')
            need(receipt.failure_domain == node['location']['failure_domain'] and len(receipt.ciphertext_sha256) == 32 and
                 receipt.block.size_bytes < receipt.stored_size_bytes <= assignment['reserved'], 'CHECKSUM_MISMATCH')
            tx.put('block', dict(id=receipt.block.block_version_id, file=receipt.block.file_id, operation=op['id'],
                ref=asdict(receipt.block), stored_size=receipt.stored_size_bytes, receipt=asdict(receipt)))
            self.confirm_location(tx, receipt, node['inventory_id'])
            self.remember(tx, user, header, 'PutBlock', receipt)
        return c.MutationResult(request_id=req.context.request_id, revision=1)

    def confirm_location(self, tx, receipt, inventory):
        tx.put('location', dict(id=receipt.block.block_version_id + ':' + receipt.node_id,
            block=receipt.block.block_version_id, node=receipt.node_id, receipt=asdict(receipt), inventory=inventory))

    def new_task(self, kind, block, source, dest):
        identity = uid()
        return dict(id=identity, kind=kind, block=block, src=source, dest=dest, expires=now() + 300000,
                    status=asdict(n.TaskStatus(task_id=identity, state=n.ACCEPTED)))

    def task_capability(self, task):
        return self.auth.capability(task['src'], task['id'], task['block']['block_version_id'], task['dest'] + ':' + task['kind'])

    def AuthorizeInternal(self, req, ctx):
        identity = node_rpc.peer(ctx)
        with self.store.transaction() as tx:
            task = tx.get('task', req.task_id)
            need(task and task['expires'] > now() and task['status']['state'] in ('ACCEPTED', 'RUNNING') and
                 asdict(req.block) == task['block'] and hmac.compare_digest(req.task_capability, self.task_capability(task)) and
                 req.source_node_id == task['src'] and req.destination_node_id == task['dest'] and
                 req.fence.lock_id == task['id'] and req.fence.service_epoch == self.system['epoch'], 'PERMISSION_DENIED')
            expected = task['src'] if req.action == c.READ_REPLICA else task['dest']
            need(expected in self.allowed and identity == self.allowed[expected]['identity'] and req.context.user_id == expected, 'PERMISSION_DENIED')
            need((task['kind'] == 'copy' and req.action in (c.READ_REPLICA, c.STORE_REPLICA)) or
                 (task['kind'] == 'delete' and req.action == c.DELETE_RETIRED and
                  self.retired_at_node(tx, req.block.block_version_id, task['dest'])), 'PERMISSION_DENIED')
            return n.AuthorizationDecision(subject_id=expected, valid_until_unix_ms=task['expires'], authz_revision=1)

    def ReportTask(self, req, ctx):
        self.node_peer(ctx, req, req.node_id)
        with self.store.transaction(True) as tx:
            task = tx.get('task', req.task.task_id)
            node = tx.get('datanode', req.node_id)
            need(task and task['dest'] == req.node_id and node and int(node['location']['boot_generation']) == req.boot_generation, 'PERMISSION_DENIED')
            if hasattr(self, 'validate_task_report'):
                self.validate_task_report(tx, req, task, node)
            if task['status']['state'] == 'FINISHED':
                need(task['status'] == asdict(req.task), 'IDEMPOTENCY_MISMATCH')
                return c.MutationResult(request_id=req.context.request_id, revision=1)
            need(task['expires'] > now() and req.task.state in (n.FINISHED, n.FAILED), 'OPERATION_EXPIRED')
            if req.task.state == n.FINISHED and task['kind'] == 'copy':
                r = req.task.receipt
                expected = proto(c.DurableReceipt, task['receipt'])
                need(r.operation_id == task['id'] and r.node_id == node['id'] and r.boot_generation == req.boot_generation and asdict(r.block) == task['block'] and
                     r.stored_size_bytes == expected.stored_size_bytes and r.ciphertext_sha256 == expected.ciphertext_sha256 and
                     tx.get('block', r.block.block_version_id), 'CHECKSUM_MISMATCH')
                self.confirm_location(tx, r, node['inventory_id'])
            task['status'] = asdict(req.task)
            task['reserved'] = 0
            tx.put('task', task)
        return c.MutationResult(request_id=req.context.request_id, revision=1)

    def retire_block(self, tx, block):
        for loc in tx.all('location'):
            if loc['block'] == block['id']:
                self.retire_copy(tx, block['ref'], loc['node'])
                tx.delete('location', loc['id'])
        super().retire_block(tx, block)

    def retired_at_node(self, tx, block_id, node_id):
        if self.location(tx, block_id, node_id):
            return False
        assignment = tx.get('assignment', block_id)
        if assignment and assignment['node'] == node_id:
            op = tx.get('upload', assignment['operation'])
            if self.operation_live(tx, op):
                return False
        return not any(t['kind'] == 'copy' and t['dest'] == node_id and t['block']['block_version_id'] == block_id and
            t['expires'] > now() and t['status']['state'] in ('ACCEPTED', 'RUNNING') for t in tx.all('task'))

    def retire_copy(self, tx, ref, node_id):
        identity = ref['block_version_id'] + ':' + node_id
        if not tx.get('retirement', identity):
            task = self.new_task('delete', ref, '', node_id)
            tx.put('task', task)
            tx.put('retirement', dict(id=identity, task=task['id']))

    def collect(self, restart=False):
        super().collect(restart)
        with self.store.transaction(True) as tx:
            for task in tx.all('task'):
                if task.get('write_operation') and task['status']['state'] in ('ACCEPTED', 'RUNNING'):
                    op = tx.get('upload', task['write_operation'])
                    if not op or op['state'] != c.PREPARING:
                        task['status'] = asdict(n.TaskStatus(task_id=task['id'], state=n.FAILED, error_reason=c.OPERATION_EXPIRED))
                        task['reserved'] = 0
                        tx.put('task', task)
            for a in tx.all('assignment'):
                op = tx.get('upload', a['operation'])
                if op and op['state'] in (c.ABORTED, c.EXPIRED) and not self.location(tx, a['id'], a['node']):
                    ref = next((b for b in op['allocations'].values() if b['block_version_id'] == a['id']), None)
                    if ref:
                        self.retire_copy(tx, ref, a['node'])
            for task in tx.all('task'):
                if task['kind'] == 'copy' and task['status']['state'] == 'FAILED':
                    self.retire_copy(tx, task['block'], task['dest'])

    def register_internal(self, server):
        return node_rpc.register(server, self, [('nodes', 'NodeRegistryService'), ('nodes', 'InternalAuthorizationService')])

    def tick(self):
        self.collect()
        with self.store.transaction() as tx:
            tasks = [t for t in tx.all('task') if t['status']['state'] in ('ACCEPTED', 'RUNNING')][:8]
        for task in tasks:
            with self.store.transaction() as tx:
                node = tx.get('datanode', task['dest'])
            if self.state(node) != 'READY':
                continue
            if task['expires'] <= now():
                with self.store.transaction(True) as tx:
                    current = tx.get('task', task['id'])
                    if current['status']['state'] in ('ACCEPTED', 'RUNNING'):
                        if task['kind'] == 'delete':
                            current['expires'] = now() + 300000
                        else:
                            current['status'] = asdict(n.TaskStatus(task_id=task['id'], state=n.FAILED, error_reason=c.OPERATION_EXPIRED))
                        tx.put('task', current)
                continue
            fence = c.Fence(lock_id=task['id'], service_epoch=self.system['epoch'], generation=1, expires_at_unix_ms=task['expires'])
            try:
                with node_rpc.channel(node['location']['private_endpoint'], self.cfg) as channel:
                    stub = ng.StorageAdministrationServiceStub(channel)
                    if task['kind'] == 'copy':
                        receipt = proto(c.DurableReceipt, task['receipt'])
                        stub.ReplicateBlock(n.ReplicateBlockRequest(context=node_rpc.context_for(self.cfg),
                            task_id=task['id'], block=proto(c.BlockRef, task['block']), source=proto(c.BlockLocation, task['source']),
                            destination=proto(c.BlockLocation, task['destination']), task_capability=self.task_capability(task),
                            fence=fence, ciphertext_length=receipt.stored_size_bytes, ciphertext_sha256=receipt.ciphertext_sha256), timeout=2)
                    else:
                        stub.DeleteRetiredBlock(n.DeleteRetiredBlockRequest(context=node_rpc.context_for(self.cfg),
                            task_id=task['id'], block=proto(c.BlockRef, task['block']), retirement_revision=1,
                            task_capability=self.task_capability(task), fence=fence), timeout=2)
            except Exception as exc:
                # Retry next bounded maintenance pass; never claim task success from transport alone.
                from dfsha.common.telemetry import event
                event('task_dispatch_retry', code=type(exc).__name__)
