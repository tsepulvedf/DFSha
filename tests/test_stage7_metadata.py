"""Adaptador autoritativo contra un clúster etcd real; no acredita todavía control HA."""
import time
import uuid
import pytest
from ha_runtime import EtcdCluster
from runtime import wait_until
from dfsha.control.etcd_metadata import EtcdMetadataStore, PAGE_BYTES
from dfsha.common.domain import Fault
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb


@pytest.fixture
def shared(run_dir):
    with EtcdCluster(run_dir/('etcd7-'+str(uuid.uuid4()))) as cluster:
        a, b = EtcdMetadataStore(cluster.config()), EtcdMetadataStore(cluster.config())
        try:
            yield cluster, a, b
        finally:
            a.channel.close()
            b.channel.close()


def test_paged_atomic_metadata_and_quorum(shared, record_property):
    cluster, a, b = shared
    payload = 'data'*100000
    with a.transaction(True) as tx:
        tx.put('snapshot', dict(id='snapshot', blocks=[payload]*5))
        tx.put('node', dict(id='file', snapshot='snapshot', alive=True, parent='root', name='file'))
    with b.transaction() as tx:
        assert tx.get('snapshot', tx.get('node', 'file')['snapshot'])['blocks'] == [payload]*5
    with pytest.raises(RuntimeError):
        with a.transaction(True) as tx:
            tx.put('node', dict(id='file', snapshot='incomplete'))
            raise RuntimeError('induced before publication')
    with b.transaction() as tx:
        assert tx.get('node', 'file')['snapshot'] == 'snapshot'
    status = cluster.status()
    record_property('membership', str(status))
    leader = next(i for i, x in enumerate(status) if x['member'] == x['leader'])
    cluster.members[leader].stop()
    def majority():
        try:
            with b.transaction(True) as tx:
                tx.put('node', dict(id='after-leader-loss'))
            return True
        except Fault:
            return False
    wait_until(majority, seconds=15)
    second = next(i for i in range(3) if i != leader)
    cluster.members[second].stop()
    start = time.monotonic()
    with pytest.raises(Fault, match='SERVICE_UNAVAILABLE'):
        with a.transaction(True) as tx:
            tx.put('node', dict(id='forbidden-minority'))
    assert time.monotonic()-start < 10
    cluster.members[second].start()
    wait_until(majority, seconds=15)
    with b.transaction() as tx:
        assert tx.get('node', 'forbidden-minority') is None


def test_shared_lease_expiry_and_publication_fence(shared):
    _, a, b = shared
    with a.transaction(True) as tx:
        handle = dict(id=str(uuid.uuid4()), deadline=time.time()+1)
        tx.put('handle', handle)
    with b.transaction() as tx:
        assert b.lease_live(tx.get('handle', handle['id']))
    wait_until(lambda: not b.lease_live(handle), seconds=8)
    with pytest.raises(Fault, match='LOCK_EXPIRED'):
        with b.transaction(True) as tx:
            old = tx.get('handle', handle['id'])
            old['deadline'] = time.time()+120
            tx.put('handle', old)
    with a.transaction(True) as tx:
        guard = dict(id=str(uuid.uuid4()), deadline=time.time()+1)
        tx.put('handle', guard)
    with pytest.raises(Fault, match='VERSION_CONFLICT'):
        with a.transaction(True) as tx:
            assert a.lease_live(tx.get('handle', guard['id']))
            tx.put('node', dict(id='fenced-publication'))
            # Independent client observes actual etcd expiry while the prepared
            # writer still holds its metadata gate. Its final Txn must reject.
            wait_until(lambda: not b.lease_live(guard), seconds=8)
    with b.transaction() as tx:
        assert tx.get('node', 'fenced-publication') is None


def test_watch_disconnect_and_compaction_rebuild(shared):
    from dfsha.control.etcd_watch import RootWatch
    from dfsha.common.etcd_probe_client import EtcdProbeClient
    cluster, a, _ = shared
    watcher = RootWatch(a)
    watcher.start()
    try:
        wait_until(lambda: watcher.rebuilds == 1, seconds=10)
        with a.transaction(True) as tx:
            tx.put('node', dict(id='first'))
        wait_until(lambda: watcher.events > 0, seconds=10)
        watcher.pause()
        assert watcher.disconnected.wait(5)
        for index in range(3):
            with a.transaction(True) as tx:
                tx.put('node', dict(id=str(index)))
        revision = a.range(a.root_key).mod_revision
        with EtcdProbeClient(cluster.targets[0], cluster.certs, 'etcd-root') as admin:
            admin.kv.Compact(pb.CompactionRequest(revision=revision, physical=True), timeout=5)
        watcher.resume()
        wait_until(lambda: watcher.compactions > 0 and watcher.rebuilds >= 2, seconds=15)
        with a.transaction() as tx:
            assert tx.get('node', '2')
    finally:
        watcher.close()


def test_partition_one_authority_client_without_stopping_etcd(shared, record_property):
    from fault_proxy import FaultProxy
    cluster, a, _ = shared
    proxies = [FaultProxy(target) for target in cluster.targets]
    cfg = cluster.config()
    cfg['etcd_endpoints'] = [p.endpoint for p in proxies]
    isolated = EtcdMetadataStore(cfg)
    try:
        with isolated.transaction(True) as tx:
            tx.put('node', dict(id='partition', version=1))
        start = time.monotonic()
        for proxy in proxies:
            proxy.partition()
        with pytest.raises(Fault, match='SERVICE_UNAVAILABLE'):
            with isolated.transaction(True) as tx:
                tx.put('node', dict(id='partition', version=2))
        elapsed = time.monotonic()-start
        assert elapsed < 10
        with a.transaction(True) as tx:
            assert tx.get('node', 'partition')['version'] == 1
            tx.put('node', dict(id='partition', version=3))
        for proxy in proxies:
            proxy.heal()
        def recovered():
            try:
                with isolated.transaction() as tx:
                    return tx.get('node', 'partition')['version'] == 3
            except Fault:
                return False
        wait_until(recovered, seconds=15)
        assert all(m.process.poll() is None for m in cluster.members)
        record_property('partition_error_seconds', elapsed)
        record_property('transport_bytes', str([(p.up_bytes, p.down_bytes) for p in proxies]))
    finally:
        isolated.channel.close()
        for proxy in proxies:
            proxy.close()


def test_etcd_snapshot_restore_new_cluster(shared, run_dir, record_property):
    from etcd_backup import snapshot, restore
    cluster, a, _ = shared
    with a.transaction(True) as tx:
        tx.put('node', dict(id='restored-file', version=17, digest='metadata-only-test'))
    source_revision = a.range(a.root_key).mod_revision
    path = run_dir/('snapshot-'+str(uuid.uuid4())+'.db')
    status = snapshot(cluster, path)
    restored = EtcdCluster(run_dir/('restore-'+str(uuid.uuid4())), cluster.certs, cluster.identities)
    restored.prefix = cluster.prefix
    restore(path, restored)
    with restored:
        b = EtcdMetadataStore(restored.config())
        try:
            with b.transaction() as tx:
                assert tx.get('node', 'restored-file')['version'] == 17
            assert b.range(b.root_key).mod_revision >= source_revision
            assert restored.membership[0]['revision'] >= source_revision+1000000000
            assert restored.membership[0]['cluster'] != cluster.membership[0]['cluster']
            with b.transaction(True) as tx:
                tx.put('node', dict(id='restored-file', version=18))
            with a.transaction() as tx:
                assert tx.get('node', 'restored-file')['version'] == 17
            record_property('snapshot_status', str(status))
            record_property('restored_membership', str(restored.membership))
        finally:
            b.channel.close()


def test_etcd_application_identity_is_prefix_restricted(shared):
    cluster, _, _ = shared
    cfg = cluster.config()
    cfg['etcd_prefix'] = '/dfsha/ha/unauthorized-'+str(uuid.uuid4())
    unauthorized = EtcdMetadataStore(cfg)
    try:
        with pytest.raises(Fault, match='PERMISSION_DENIED'):
            unauthorized.range(unauthorized.root_key)
    finally:
        unauthorized.channel.close()
