"""E6: política persistente y reconciliación de copias, sin contenido en control."""
import hashlib
import json
from pathlib import Path
import time

import grpc
from dfsha.common import node_rpc
from dfsha.common.domain import need, now, uid, asdict, proto, Fault
from dfsha.control.distributed import DistributedControl, storage_cost
from dfsha.control.access import AccessQueries, AccessCommands, WRITE_MODES
from dfsha.v1 import common_pb2 as c, nodes_pb2 as n, nodes_pb2_grpc as ng

ACTIVE = ('ACCEPTED', 'RUNNING')


class ProtectionQueries(AccessQueries):
    def GetProtection(self, tx, user, session, req):
        need(1 <= (req.page.limit or 64) <= 64)
        if req.operation_id:
            op = tx.get('upload', req.operation_id)
            need(op and op['user'] == user['id'], 'PERMISSION_DENIED')
            file_id = op['file']
            refs = list(op['allocations'].values())
        else:
            op = None
            node = self.resolve(tx, user, req.path)
            need(node['kind'] == 'file', 'IS_DIRECTORY')
            self.app.auth.require(tx, user, node, 4)
            file_id = node['id']
            if req.snapshot_id:
                h = next((h for h in tx.all('handle') if h['file'] == file_id and h['snapshot'] == req.snapshot_id and
                    h['user'] == user['id'] and h['session'] == session['id'] and not h['closed'] and self.app.leases.live(h)), None)
                need(h, 'STALE_HANDLE')
            snapshot = tx.get('snapshot', req.snapshot_id or node['snapshot'])
            refs = snapshot['blocks']
        policy = self.app.policy(tx, file_id)
        try:
            cursor = int(req.page.cursor or '0')
        except ValueError:
            raise Fault('INVALID_ARGUMENT') from None
        need(0 <= cursor <= len(refs))
        limit = req.page.limit or 64
        rows = [self.app.protection(tx, ref, policy) for ref in refs[cursor:cursor+limit]]
        status = 'UNAVAILABLE' if any(not x.eligible for x in rows) else 'DEGRADED' if any(x.eligible < policy['r'] for x in rows) else 'NORMAL'
        return n.ProtectionStatus(file_id=file_id, target_replicas=policy['r'], minimum_durable=policy['w'],
            policy_revision=policy['revision'], policy_state=policy['state'], failure_profile=self.app.cfg['failure_profile'],
            blocks=rows, state=status, durable_ready=all(x.confirmed >= policy['w'] and x.eligible >= policy['w'] for x in rows),
            next_cursor=str(cursor+limit) if cursor+limit < len(refs) else '', operation_state=op['state'] if op else c.OPERATION_STATE_UNSPECIFIED)


class ProtectionCommands(AccessCommands):
    def capture_policy(self, tx, op):
        policy = self.app.policy(tx, op['file'], create=not op.get('base'))
        need(policy['state'] != 'PROMOTING', 'LOCK_BUSY')
        op['policy'] = dict(policy)
        tx.put('upload', op)

    def BeginUpload(self, tx, user, session, req):
        result = super().BeginUpload(tx, user, session, req)
        self.capture_policy(tx, tx.get('upload', result.operation.operation_id))
        result.minimum_durable = self.app.policy(tx, result.file_id)['w']
        return result

    def BeginWrite(self, tx, user, session, req):
        h, _ = self.q.handle(tx, user, session, req.handle_id)
        need(self.app.policy(tx, h['file'])['state'] != 'PROMOTING', 'LOCK_BUSY')
        result = super().BeginWrite(tx, user, session, req)
        op = tx.get('upload', result.operation.operation_id)
        self.capture_policy(tx, op)
        result.minimum_durable = self.app.policy(tx, op['file'])['w']
        if op['state'] == c.COMMITTED:
            self.app.policy_result(tx, op, proto(c.CommitResult, op['result']))
        return result

    def Open(self, tx, user, session, req):
        if req.mode in WRITE_MODES:
            try:
                node = self.q.resolve(tx, user, req.path)
            except Fault as exc:
                if exc.reason != 'NOT_FOUND':
                    raise
            else:
                need(self.app.policy(tx, node['id'])['state'] != 'PROMOTING', 'LOCK_BUSY')
        result = super().Open(tx, user, session, req)
        self.app.policy(tx, result.snapshot.file_id, create=True)
        return result

    def CommitUpload(self, tx, user, session, req):
        op = tx.get('upload', req.operation.operation_id)
        self.app.validate_policy(tx, op)
        result = super().CommitUpload(tx, user, session, req)
        return self.app.policy_result(tx, tx.get('upload', op['id']), result)

    def CommitWrite(self, tx, user, session, req):
        op = tx.get('upload', req.operation.operation_id)
        self.app.validate_policy(tx, op)
        result = super().CommitWrite(tx, user, session, req)
        return self.app.policy_result(tx, tx.get('upload', op['id']), result)

    def PromoteProtection(self, tx, user, session, req):
        need(user['admin'], 'PERMISSION_DENIED')
        node = self.q.resolve(tx, user, req.path)
        need(node['kind'] == 'file', 'IS_DIRECTORY')
        policy = self.app.policy(tx, node['id'])
        need(req.expected_policy_revision == policy['revision'], 'VERSION_CONFLICT')
        if policy['r'] == 3 and policy['state'] != 'PROMOTION_BLOCKED':
            return self.result(req, policy['revision'])
        policy.update(r=3, w=2, revision=policy['revision']+1, state='PROMOTING', until=now()+300000)
        tx.put('policy', policy)
        for op in tx.all('upload'):
            if op['file'] == node['id'] and op['state'] == c.PREPARING:
                op.update(state=c.ABORTED, reserved=0)
                tx.put('upload', op)
                self.app.leases.release_operation(tx, op)
        return self.result(req, policy['revision'])


class ReplicatedControl(DistributedControl):
    def __init__(self, cfg):
        need(cfg.get('rf3_enabled'), 'UNSUPPORTED_MODE')
        need(cfg.get('failure_profile') in ('process-simulation', 'independent-hosts'))
        if cfg['failure_profile'] == 'independent-hosts':
            inventory = json.loads(Path(cfg['infrastructure_inventory_path']).read_text(encoding='utf-8'))
            need(inventory.get('verified_by') and inventory.get('evidence'), 'PERMISSION_DENIED')
        super().__init__(cfg)
        self.queries, self.commands = ProtectionQueries(self), None
        self.commands = ProtectionCommands(self)
        with self.store.transaction(True) as tx:
            boot = tx.get('settings', 'control-epoch')
            self.maintenance_generation = boot['generation']
            for node in tx.all('node'):
                if node['kind'] == 'file':
                    tx.put('policy', self.policy(tx, node['id']))  # Existing R1 data is never silently promoted.
            for loc in tx.all('location'):
                history = tx.get('durability', loc['block']) or dict(id=loc['block'], receipts={})
                history['receipts'].setdefault(loc['node'], loc['receipt'])
                tx.put('durability', history)
            for task in tx.all('task'):
                if task['status']['state'] in ACTIVE:
                    task['expires'] = 0
                    task['status']['state'] = 'FAILED'
                    task['reserved'] = 0
                    tx.put('task', task)
        domains = [v['failure_domain'] for v in self.allowed.values()]
        need(all(domains), 'PERMISSION_DENIED')
        if cfg['failure_profile'] == 'independent-hosts':
            need(all(inventory.get('nodes', {}).get(k) == v['failure_domain'] for k, v in self.allowed.items()), 'PERMISSION_DENIED')

    def policy(self, tx, file_id, create=False):
        p = tx.get('policy', file_id)
        if p is None:
            replicas = self.cfg.get('default_replicas', 3) if create else 1
            need(replicas in (1, 3))
            p = dict(id=file_id, r=replicas, w=2 if replicas == 3 else 1, revision=1, state='ACTIVE')
            # Queries do not create metadata. Commands explicitly persist first policy.
            if create:
                tx.put('policy', p)
        return p

    def upload_plan(self, op):
        result = super().upload_plan(op)
        result.minimum_durable = op.get('policy', {}).get('w', 1)
        return result

    def useful(self, tx):
        pins = {x['snapshot'] for x in tx.all('node') if x['alive'] and x.get('snapshot')}
        pins.update(h['snapshot'] for h in tx.all('handle') if not h['closed'] and self.leases.live(h))
        result = {}
        for snap in tx.all('snapshot'):
            if snap['id'] in pins:
                result.update({b['block_version_id']: b for b in snap['blocks']})
        for op in tx.all('upload'):
            if self.operation_live(tx, op):
                result.update({b['block_version_id']: b for b in op['allocations'].values()})
        return result

    def eligible(self, tx, block):
        result = []
        for loc in tx.all('location'):
            node = tx.get('datanode', loc['node'])
            if loc['block'] == block and loc.get('health', 'VERIFIED') == 'VERIFIED' and node and self.state(node) in ('READY', 'SUSPECT') and loc.get('inventory') == node['inventory_id']:
                result.append(loc)
        return result

    def protection(self, tx, ref, policy):
        identity = ref['block_version_id']
        locations = [x for x in tx.all('location') if x['block'] == identity]
        eligible = {x['node'] for x in self.eligible(tx, identity)}
        historical = tx.get('durability', identity) or dict(receipts={})
        domains = {self.allowed[k]['failure_domain'] for k in historical['receipts'] if k in self.allowed}
        copies = [n.CopyProtection(node=proto(c.BlockLocation, tx.get('datanode', x['node'])['location']),
            receipt=proto(c.DurableReceipt, x['receipt']), health=x.get('health', 'VERIFIED'), eligible=x['node'] in eligible) for x in locations]
        pending = sum(t['block']['block_version_id'] == identity and t['status']['state'] in ACTIVE and t['expires'] > now() for t in tx.all('task'))
        record = tx.get('block', identity)
        return n.BlockProtection(block=proto(c.BlockRef, record['ref'] if record else ref), target=policy['r'],
            confirmed=len(domains), eligible=len(eligible), copies=copies, pending_tasks=pending)

    def confirm_location(self, tx, receipt, inventory):
        need(not tx.get('retired', receipt.block.block_version_id), 'VERSION_CONFLICT')
        super().confirm_location(tx, receipt, inventory)
        record = tx.get('durability', receipt.block.block_version_id) or dict(id=receipt.block.block_version_id, receipts={})
        record['receipts'][receipt.node_id] = asdict(receipt)
        tx.put('durability', record)

    def validate_policy(self, tx, op):
        need(op, 'NOT_FOUND')
        policy = self.policy(tx, op['file'])
        need(op.get('policy', policy)['revision'] == policy['revision'] and policy['state'] != 'PROMOTING', 'VERSION_CONFLICT')

    def require_durable(self, tx, op, block):
        self.validate_policy(tx, op)
        p = self.policy(tx, op['file'])
        status = self.protection(tx, asdict(block), p)
        active_domains = {self.allowed[x['node']]['failure_domain'] for x in self.eligible(tx, block.block_version_id)}
        need(status.confirmed >= p['w'] and len(active_domains) >= p['w'], 'INSUFFICIENT_REPLICAS')

    def policy_result(self, tx, op, result):
        p = self.policy(tx, op['file'])
        result.target_replicas, result.minimum_durable = p['r'], p['w']
        snap = tx.get('snapshot', result.snapshot.manifest_root)
        for ref in snap['blocks']:
            need(self.eligible(tx, ref['block_version_id']), 'DATA_UNAVAILABLE')
        result.degraded = any(len(self.eligible(tx, b['block_version_id'])) < p['r'] for b in snap['blocks'])
        op['result'] = asdict(result)
        tx.put('upload', op)
        return result

    def plan(self, block, user, binding, read=False, tx=None):
        result = super().plan(block, user, binding, read=read, tx=tx)
        if read:
            eligible = {x['node'] for x in self.eligible(tx, block.block_version_id)}
            pairs = [(loc, grant) for loc, grant in zip(result.locations, result.grants) if loc.node_id in eligible]
            if not pairs:
                known = [x for x in tx.all('location') if x['block'] == block.block_version_id]
                history = tx.get('durability', block.block_version_id) or dict(receipts={})
                lost = bool(known) and len(known) == len(history['receipts']) and all(x.get('health') in ('CORRUPT', 'MISSING') for x in known)
                need(False, 'DATA_LOSS' if lost else 'DATA_UNAVAILABLE')
            rotation = block.block_index % len(pairs)
            pairs = pairs[rotation:] + pairs[:rotation]
            del result.locations[:]
            del result.grants[:]
            result.locations.extend(x[0] for x in pairs)
            result.grants.extend(x[1] for x in pairs)
        else:
            policy = self.policy(tx, binding['file'], create=not binding.get('base'))
            self.reserve_replicas(tx, block, binding, policy)
        return result

    def reserve_replicas(self, tx, block, op, policy):
        primary = tx.get('assignment', block.block_version_id)
        existing = tx.get('replica-plan', block.block_version_id)
        if existing:
            return
        domains = {self.allowed[primary['node']]['failure_domain']}
        destinations = []
        cost = storage_cost(block.size_bytes)
        candidates = []
        for node in tx.all('datanode'):
            used, reserved = self.usage(tx, node)
            if self.state(node) == 'READY' and used+reserved+cost <= node['capacity'] and reserved+cost+1048576 <= node['free']:
                candidates.append(((used+reserved)/node['capacity'], node.get('active', 0), node['id'], node))
        for _, _, _, node in sorted(candidates):
            domain = self.allowed[node['id']]['failure_domain']
            if domain not in domains and len(domains) < policy['r']:
                domains.add(domain)
                destinations.append(node['id'])
        need(len(domains) >= policy['w'], 'INSUFFICIENT_REPLICAS')
        tx.put('replica-plan', dict(id=block.block_version_id, operation=op['id'], destinations=destinations, reserved=cost))

    def usage(self, tx, node):
        used, reserved = super().usage(tx, node)
        for plan in tx.all('replica-plan'):
            if node['id'] in plan['destinations'] and self.operation_live(tx, tx.get('upload', plan['operation'])) and not self.location(tx, plan['id'], node['id']):
                if not any(t['dest'] == node['id'] and t['block']['block_version_id'] == plan['id'] and t['status']['state'] in ACTIVE and t['expires'] > now() for t in tx.all('task')):
                    reserved += plan['reserved']
        return used, reserved

    def new_task(self, kind, block, source, dest):
        task = super().new_task(kind, block, source, dest)
        task.update(owner=getattr(self, 'leases', None).epoch if hasattr(self, 'leases') else '',
            generation=getattr(self, 'maintenance_generation', 0), attempts=0, next_run=now(), automatic=True)
        return task

    def task_capability(self, task):
        return self.auth.capability(task['src'], task['id'], task['block']['block_version_id'],
            ':'.join((task['dest'], task['kind'], task.get('owner', ''), str(task.get('generation', 0)))))

    def AuthorizeInternal(self, req, ctx):
        with self.store.transaction() as tx:
            task = tx.get('task', req.task_id)
            need(task and task.get('owner') == self.leases.epoch and task.get('generation') == req.fence.generation, 'LOCK_EXPIRED')
            need(task['kind'] == 'delete' or req.block.block_version_id in self.useful(tx), 'VERSION_CONFLICT')
            for key in ('source', 'destination'):
                if key in task:
                    node = tx.get('datanode', task[key]['node_id'])
                    need(node and node['location']['boot_generation'] == task[key]['boot_generation'], 'VERSION_CONFLICT')
        return super().AuthorizeInternal(req, ctx)

    def validate_task_report(self, tx, req, task, node):
        need(task and task.get('owner') == self.leases.epoch and req.fence.generation == task.get('generation') and req.fence.lock_id == task['id'], 'LOCK_EXPIRED')
        need(task['kind'] == 'delete' or task['block']['block_version_id'] in self.useful(tx), 'VERSION_CONFLICT')
        need(task['status']['state'] in ACTIVE or task['status'] == asdict(req.task), 'OPERATION_EXPIRED')
        if task['kind'] == 'copy':
            need(node['location'] == task['destination'], 'VERSION_CONFLICT')
            source = tx.get('datanode', task['src'])
            need(source and source['location']['boot_generation'] == task['source']['boot_generation'], 'VERSION_CONFLICT')

    def retire_block(self, tx, block):
        tx.put('retired', dict(id=block['id'], ref=block['ref'], retired_at=now()))
        super().retire_block(tx, block)

    def retire_copy(self, tx, ref, node_id):
        identity = ref['block_version_id']+':'+node_id
        previous = tx.get('retirement', identity)
        task = tx.get('task', previous['task']) if previous else None
        if not task or task['status']['state'] == 'FAILED' or task.get('owner') != getattr(getattr(self, 'leases', None), 'epoch', ''):
            task = self.new_task('delete', ref, '', node_id)
            loc = self.location(tx, ref['block_version_id'], node_id)
            task['expected_receipt_id'] = loc['receipt']['receipt_id'] if loc else ''
            tx.put('task', task)
            tx.put('retirement', dict(id=identity, task=task['id']))

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
                record = tx.get('block', receipt.block.block_version_id)
                task = tx.get('task', receipt.operation_id)
                recovered = record and task and task['kind'] == 'copy' and task['dest'] == req.node_id and task['block'] == asdict(receipt.block) and receipt.block.block_version_id in self.useful(tx) and record['receipt']['ciphertext_sha256'] == asdict(receipt)['ciphertext_sha256']
                if recovered and not tx.get('retired', receipt.block.block_version_id):
                    self.confirm_location(tx, receipt, req.report_id)
                elif old and old['receipt'] == asdict(receipt) and not tx.get('retired', receipt.block.block_version_id):
                    old.update(inventory=req.report_id, health='VERIFIED', checked_at=now())
                    tx.put('location', old)
                elif not old:
                    self.retire_copy(tx, asdict(receipt.block), req.node_id)
                    retired = tx.get('retirement', receipt.block.block_version_id+':'+req.node_id)
                    deletion = tx.get('task', retired['task'])
                    deletion['expected_receipt_id'] = receipt.receipt_id
                    tx.put('task', deletion)
            node.update(page=node['page']+1, seen=now(), reconciled=req.last_page)
            if req.last_page:
                for loc in tx.all('location'):
                    if loc['node'] == req.node_id and loc.get('inventory') != req.report_id:
                        loc['health'] = 'MISSING'
                        tx.put('location', loc)
            tx.put('datanode', node)
        return c.MutationResult(request_id=req.context.request_id, revision=req.page_index+1)

    def collect(self, restart=False):
        if not hasattr(self, 'leases'):
            return super().collect(restart)
        with self.store.transaction(True) as tx:
            useful = self.useful(tx)
            for task in tx.all('task'):
                unavailable = any(self.state(tx.get('datanode', task[key]['node_id'])) == 'UNAVAILABLE' or
                    tx.get('datanode', task[key]['node_id'])['location']['boot_generation'] != task[key]['boot_generation']
                    for key in ('source', 'destination') if key in task)
                if task['kind'] == 'copy' and task['status']['state'] in ACTIVE and (task['block']['block_version_id'] not in useful or
                    task.get('owner') != self.leases.epoch or task['expires'] <= now() or unavailable):
                    task['status']['state'], task['reserved'], task['expires'] = 'FAILED', 0, 0
                    tx.put('task', task)
        # Base GC handles pins and tombstones; do not run E4's failed-copy deletion policy.
        from dfsha.control.monolith import Monolith
        Monolith.collect(self, restart)

    def reconcile(self):
        with self.store.transaction(True) as tx:
            useful = self.useful(tx)
            for identity, ref in useful.items():
                record = tx.get('block', identity)
                if not record or tx.get('retired', identity):
                    continue
                p = self.policy(tx, ref['file_id'])
                eligible = self.eligible(tx, identity)
                domains = {self.allowed[x['node']]['failure_domain'] for x in eligible}
                active = [t for t in tx.all('task') if t['kind'] == 'copy' and t['block']['block_version_id'] == identity and
                    t['status']['state'] in ACTIVE and t['expires'] > now()]
                domains.update(self.allowed[t['dest']]['failure_domain'] for t in active)
                if not eligible or len(domains) >= p['r']:
                    continue
                planned = tx.get('replica-plan', identity) or dict(destinations=[])
                candidates = []
                for node in tx.all('datanode'):
                    if self.state(node) != 'READY' or self.allowed[node['id']]['failure_domain'] in domains:
                        continue
                    used, reserved = self.usage(tx, node)
                    reservation = planned['destinations'] and node['id'] in planned['destinations'] and self.operation_live(tx, tx.get('upload', planned['operation']))
                    cost = storage_cost(int(record['ref']['size_bytes']))
                    if used+reserved+(0 if reservation else cost) <= node['capacity'] and reserved+cost <= node['free']:
                        candidates.append((int(20*(used+reserved)/node['capacity']), node.get('active', 0), node['id'], node))
                for _, _, _, node in sorted(candidates):
                    if len(domains) >= p['r']:
                        break
                    domain = self.allowed[node['id']]['failure_domain']
                    if domain in domains:
                        continue
                    retry = tx.get('repair-retry', identity+':'+node['id']) or dict(id=identity+':'+node['id'], attempts=0, next_run=0)
                    if retry['next_run'] > now():
                        continue
                    source = eligible[0]
                    source_node = tx.get('datanode', source['node'])
                    task = self.new_task('copy', record['ref'], source['node'], node['id'])
                    old = self.location(tx, identity, node['id'])
                    task.update(source=source_node['location'], destination=node['location'], receipt=source['receipt'],
                        reserved=cost, replace_receipt=old['receipt']['receipt_id'] if old and old.get('health') in ('CORRUPT', 'MISSING') else '')
                    tx.put('task', task)
                    retry.update(attempts=retry['attempts']+1, next_run=now()+min(30000, 1000*2**min(retry['attempts'], 5)))
                    tx.put('repair-retry', retry)
                    domains.add(domain)
            for p in tx.all('policy'):
                if p['state'] == 'PROMOTING':
                    refs = [b for b in useful.values() if b['file_id'] == p['id']]
                    if all(len(self.eligible(tx, b['block_version_id'])) >= p['r'] for b in refs):
                        p['state'] = 'ACTIVE'
                    elif now() >= p['until']:
                        p['state'] = 'PROMOTION_BLOCKED'
                    tx.put('policy', p)

    def scrub(self):
        with self.store.transaction() as tx:
            locations = [x for x in tx.all('location') if x.get('health', 'VERIFIED') == 'VERIFIED' and
                self.state(tx.get('datanode', x['node'])) == 'READY' and x.get('checked_at', 0)+self.cfg.get('scrub_interval_ms', 30000) < now()]
            if not locations:
                return
            loc = min(locations, key=lambda x: x.get('checked_at', 0))
            node = tx.get('datanode', loc['node'])
        health = 'VERIFIED'
        r = proto(c.DurableReceipt, loc['receipt'])
        try:
            with node_rpc.channel(node['location']['private_endpoint'], self.cfg) as channel:
                actual = ng.StorageAdministrationServiceStub(channel).VerifyReceipt(n.VerifyReceiptRequest(
                    context=node_rpc.context_for(self.cfg), operation_id=r.operation_id, receipt_id=r.receipt_id, block=r.block,
                    expected_boot_generation=int(node['location']['boot_generation']), verify_content=True), timeout=5)
                if actual != r:
                    return  # Concurrent inventory reconciliation requires another pass.
        except grpc.RpcError as exc:
            if exc.code() == grpc.StatusCode.DATA_LOSS:
                health = 'CORRUPT'
            elif exc.code() == grpc.StatusCode.NOT_FOUND:
                health = 'MISSING'
            else:
                return  # Timeout is suspicion, not proof of destroyed content.
        with self.store.transaction(True) as tx:
            current = self.location(tx, loc['block'], loc['node'])
            if current and current['receipt'] == loc['receipt']:
                current.update(health=health, checked_at=now())
                tx.put('location', current)
                if health != 'VERIFIED':
                    tx.put('copy-health-event', dict(id=uid(), block=loc['block'], node=loc['node'], receipt=loc['receipt'],
                        health=health, observed_at=now(), evidence='authenticated VerifyReceipt'))

    def clean_orphan_copy(self):
        with self.store.transaction() as tx:
            useful = self.useful(tx)
            tasks = [t for t in tx.all('task') if t['kind'] == 'copy' and t['status']['state'] == 'FAILED' and
                not t.get('cleanup_checked') and t['block']['block_version_id'] not in useful and
                self.state(tx.get('datanode', t['dest'])) == 'READY']
            if not tasks:
                return
            task = tasks[0]
            node = tx.get('datanode', task['dest'])
        try:
            with node_rpc.channel(node['location']['private_endpoint'], self.cfg) as channel:
                status = ng.StorageAdministrationServiceStub(channel).GetTask(n.GetTaskRequest(
                    context=node_rpc.context_for(self.cfg), task_id=task['id']), timeout=2)
        except grpc.RpcError:
            return
        with self.store.transaction(True) as tx:
            if status.state == n.FINISHED and asdict(status.receipt.block) == task['block'] and task['block']['block_version_id'] not in self.useful(tx):
                self.retire_copy(tx, task['block'], task['dest'])
                retirement = tx.get('retirement', task['block']['block_version_id']+':'+task['dest'])
                deletion = tx.get('task', retirement['task'])
                deletion['expected_receipt_id'] = status.receipt.receipt_id
                tx.put('task', deletion)
            if status.state in (n.FINISHED, n.FAILED):
                current = tx.get('task', task['id'])
                current['cleanup_checked'] = True
                tx.put('task', current)

    def tick(self):
        self.collect()
        self.scrub()
        self.reconcile()
        self.clean_orphan_copy()
        with self.store.transaction() as tx:
            active = sorted([t for t in tx.all('task') if t['status']['state'] in ACTIVE and t['expires'] > now()], key=lambda t: t['id'])
            # One copy at a time across the laboratory prevents cyclic source/destination
            # admission deadlocks for 128 MiB. Client admission remains bounded separately.
            copies = [t for t in active if t['kind'] == 'copy' and not (self.cfg.get('test_fault_dir') and
                ((Path(self.cfg['test_fault_dir']) / ('hold-copy-'+t['dest'])).exists() or
                 (Path(self.cfg['test_fault_dir']) / ('hold-block-'+t['block']['block_version_id'])).exists()))]
            running = [t for t in copies if t.get('dispatched')]
            tasks = (running or copies)[:1] + [t for t in active if t['kind'] == 'delete'][:1]
        for task in tasks:
            if task.get('next_run', 0) > now():
                continue
            if self.cfg.get('test_fault_dir') and (Path(self.cfg['test_fault_dir']) / ('hold-copy-'+task['dest'])).exists() and task['kind'] == 'copy':
                continue
            with self.store.transaction() as tx:
                node = tx.get('datanode', task['dest'])
            if self.state(node) != 'READY':
                continue
            fence = c.Fence(lock_id=task['id'], service_epoch=self.system['epoch'], generation=task['generation'], expires_at_unix_ms=task['expires'])
            try:
                with node_rpc.channel(node['location']['private_endpoint'], self.cfg) as channel:
                    stub = ng.StorageAdministrationServiceStub(channel)
                    if task['kind'] == 'copy':
                        receipt = proto(c.DurableReceipt, task['receipt'])
                        stub.ReplicateBlock(n.ReplicateBlockRequest(context=node_rpc.context_for(self.cfg), task_id=task['id'],
                            block=receipt.block, source=proto(c.BlockLocation, task['source']), destination=proto(c.BlockLocation, task['destination']),
                            task_capability=self.task_capability(task), fence=fence, ciphertext_length=receipt.stored_size_bytes,
                            ciphertext_sha256=receipt.ciphertext_sha256, replace_receipt_id=task.get('replace_receipt', '')), timeout=2)
                    else:
                        stub.DeleteRetiredBlock(n.DeleteRetiredBlockRequest(context=node_rpc.context_for(self.cfg), task_id=task['id'],
                            block=proto(c.BlockRef, task['block']), retirement_revision=1, task_capability=self.task_capability(task),
                            fence=fence, expected_receipt_id=task.get('expected_receipt_id', '')), timeout=2)
            except grpc.RpcError:
                pass
            with self.store.transaction(True) as tx:
                current = tx.get('task', task['id'])
                current['attempts'] = current.get('attempts', 0)+1
                current['dispatched'] = True
                current['next_run'] = now()+min(10000, 500*2**min(current['attempts'], 4))
                tx.put('task', current)
