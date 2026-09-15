"""Tres controles activos: estado y propiedad en etcd, sin fallback SQLite."""
import time
import threading
from uuid import uuid4
from dfsha.common.domain import need, now, Fault
from dfsha.control.etcd_metadata import EtcdMetadataStore, compare
from dfsha.control.leases import SQLiteLeaseAuthority
from dfsha.control.replication import ReplicatedControl, ACTIVE
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb


class EtcdLeaseAuthority(SQLiteLeaseAuthority):
    def __init__(self, app):
        self.app, self.clock = app, time.time
        self.lock_seconds = app.cfg.get('lock_lease_seconds', 30)
        self.handle_seconds = app.cfg.get('handle_lease_seconds', 120)
        with app.store.transaction() as tx:
            shared = tx.get('settings', 'control-epoch')
            need(shared, 'NOT_FOUND')
            self.epoch = shared['epoch']

    def live(self, record):
        return (record.get('control_epoch') == self.epoch and
            record.get('maximum', float('inf')) > self.clock() and
            record.get('deadline', 0) > self.clock() and self.app.store.lease_live(record))


class HAControl(ReplicatedControl):
    lease_authority_class = EtcdLeaseAuthority

    def __init__(self, cfg):
        self.ha_ready = False
        self.instance = str(uuid4())
        self.maintenance_lease = None
        self.maintenance_value = None
        self.next_maintenance = 0
        super().__init__(cfg)
        import hashlib
        from dfsha.control.etcd_metadata import encode
        administrative_digest = hashlib.sha256(encode(self.allowed)).hexdigest()
        with self.store.transaction(True) as tx:
            previous = tx.get('settings', 'administrative-nodes')
            need(not previous or previous['sha256'] == administrative_digest, 'PERMISSION_DENIED')
            if not previous:
                tx.put('settings', dict(id='administrative-nodes', sha256=administrative_digest))
        self.leader_key = self.store.prefix+b'maintenance-owner'
        self.ha_ready = True
        from dfsha.control.etcd_watch import RootWatch
        self.root_watch = RootWatch(self.store)
        self.root_watch.start()
        self.maintenance_stop = threading.Event()
        self.maintenance_renewal = threading.Thread(target=self.renew_maintenance, daemon=True,
            name='maintenance-lease-renewal')
        self.maintenance_renewal.start()

    def renew_maintenance(self):
        # Replication/scrubbing may outlast the owner TTL. Renewal is independent
        # of the work; every publication still compares the lease-backed owner.
        while not self.maintenance_stop.wait(3):
            lease, value = self.maintenance_lease, self.maintenance_value
            if lease and value:
                try:
                    current = self.store.range(self.leader_key)
                    if current and current.value == value:
                        self.store.keepalive(lease)
                except Fault:
                    pass  # Expiry removes authority; never recreate this owner.

    def make_metadata(self, cfg):
        return EtcdMetadataStore(cfg)

    def state(self, node):
        if not node or node.get('deadline', 0) <= time.time() or not self.store.lease_live(node):
            return 'UNAVAILABLE'
        if not node['reconciled']:
            return 'STARTING'
        return 'SUSPECT' if now()-node['seen'] >= self.cfg.get('suspect_ms', 12000) else 'READY'

    def retained_snapshots(self, tx):
        return {x['snapshot'] for x in tx.all('migration-pin')}

    def useful(self, tx):
        result = super().useful(tx)
        for identity in self.retained_snapshots(tx):
            snapshot = tx.get('snapshot', identity)
            if snapshot:
                result.update({b['block_version_id']: b for b in snapshot['blocks']})
        return result

    def maintenance(self, tx):
        leader = tx.get('settings', 'maintenance')
        need(leader and self.store.lease_live(leader), 'SERVICE_UNAVAILABLE')
        return leader

    def new_task(self, kind, block, source, dest):
        task = super().new_task(kind, block, source, dest)
        tx = self.store.local.unit
        leader = self.maintenance(tx)
        task.update(generation=leader['generation'], maintenance_owner=leader['lease_owner'])
        return task

    def check_task_owner(self, tx, task):
        leader = self.maintenance(tx)
        need(task and task.get('generation') == leader['generation'] and
            task.get('maintenance_owner') == leader['lease_owner'], 'LOCK_EXPIRED')

    def validate_task_report(self, tx, req, task, node):
        self.check_task_owner(tx, task)
        super().validate_task_report(tx, req, task, node)

    def AuthorizeInternal(self, req, ctx):
        with self.store.transaction() as tx:
            self.check_task_owner(tx, tx.get('task', req.task_id))
        return super().AuthorizeInternal(req, ctx)

    def collect(self, restart=False):
        if not self.ha_ready:
            return
        with self.store.transaction(True) as tx:
            leader = self.maintenance(tx)
            for task in tx.all('task'):
                if task['status']['state'] in ACTIVE and task.get('generation') != leader['generation']:
                    task.update(expires=0, reserved=0)
                    task['status']['state'] = 'FAILED'
                    tx.put('task', task)
        return super().collect(False)

    def take_maintenance(self):
        current = self.store.range(self.leader_key)
        if current and self.maintenance_value == current.value:
            self.store.keepalive(self.maintenance_lease)
            self.install_maintenance_generation()
            return True
        if current:
            return False
        lease = self.store.grant(15)
        value = (self.instance+':'+str(uuid4())).encode()
        result = self.store.rpc(self.store.kv.Txn, pb.TxnRequest(compare=[pb.Compare(key=self.leader_key,
            target=pb.Compare.CREATE, result=pb.Compare.EQUAL, create_revision=0)], success=[pb.RequestOp(
                request_put=pb.PutRequest(key=self.leader_key, value=value, lease=lease))]))
        if not result.succeeded:
            return False
        self.maintenance_lease, self.maintenance_value = lease, value
        self.install_maintenance_generation()
        return True

    def install_maintenance_generation(self):
        lease, value = self.maintenance_lease, self.maintenance_value
        with self.store.transaction() as tx:
            previous = tx.get('settings', 'maintenance')
            if previous and previous['lease_owner'] == value.decode():
                return
        # A crash/timeout after election but before this publication is retried
        # without inventing another owner or repeatedly incrementing generation.
        self.store.local.required_guards = {self.leader_key: value}
        try:
            with self.store.transaction(True) as tx:
                previous = tx.get('settings', 'maintenance') or {'generation': 0}
                if previous.get('lease_owner') == value.decode():
                    return
                tx.put('settings', dict(id='maintenance', generation=previous['generation']+1,
                    lease=lease, lease_key=self.leader_key.decode(), lease_owner=value.decode(),
                    instance=self.instance, control_id=self.cfg['certificate_identity']))
        finally:
            self.store.local.required_guards = {}

    def tick(self):
        if not self.take_maintenance():
            return
        if time.monotonic() < self.next_maintenance:
            return
        self.next_maintenance = time.monotonic()+3
        self.store.local.required_guards = {self.leader_key: self.maintenance_value}
        try:
            super().tick()
        finally:
            self.store.local.required_guards = {}

    def stop_ha(self):
        self.maintenance_stop.set()
        self.maintenance_renewal.join(7)
        self.root_watch.close()
        self.store.channel.close()

    def health(self):
        try:
            root = self.store.range(self.store.root_key)
            return dict(metadata_available=root is not None, metadata_revision=root.mod_revision if root else 0,
                control_instance=self.instance, metadata_backend='etcd')
        except Fault:
            return dict(metadata_available=False, control_instance=self.instance, metadata_backend='etcd')
