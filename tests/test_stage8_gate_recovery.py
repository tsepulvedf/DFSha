"""Real network loss during cleanup must not keep an abandoned metadata gate alive."""
import uuid

import pytest

from dfsha.common.domain import Fault
from dfsha.control.etcd_metadata import EtcdMetadataStore
from fault_proxy import FaultProxy
from ha_runtime import EtcdCluster
from runtime import wait_until


def test_failed_cleanup_discards_cached_gate_lease(run_dir, record_property):
    with EtcdCluster(run_dir/('gate-recovery-'+str(uuid.uuid4()))) as cluster:
        proxy = FaultProxy(cluster.targets[0])
        cfg = dict(cluster.config(), etcd_endpoints=[proxy.endpoint],
                   etcd_timeout_seconds=.5, metadata_gate_lease_seconds=3,
                   metadata_gate_wait_seconds=.2)
        owner = EtcdMetadataStore(cfg)
        observer = EtcdMetadataStore(cluster.config())
        try:
            with pytest.raises(RuntimeError, match='induced before publication'):
                with owner.transaction(True) as tx:
                    old_lease = owner.local.gate_lease
                    tx.put('node', dict(id='must-not-publish'))
                    assert observer.range(owner.gate_key).lease == old_lease
                    proxy.partition()  # Real sockets closed before the cleanup RPC.
                    raise RuntimeError('induced before publication')
            assert getattr(owner.local, 'gate_lease', None) is None
            proxy.heal()
            with observer.transaction() as tx:
                assert tx.get('node', 'must-not-publish') is None

            def recovered():
                try:
                    with owner.transaction(True) as tx:
                        assert owner.local.gate_lease != old_lease
                        tx.put('node', dict(id='after-recovery'))
                    return True
                except Fault as error:
                    assert error.reason == 'SERVICE_UNAVAILABLE'
                    return False

            wait_until(recovered, seconds=15)
            with observer.transaction() as tx:
                assert tx.get('node', 'after-recovery')
                assert tx.get('node', 'must-not-publish') is None
            record_property('recovery', 'real TCP partition during cleanup; abandoned lease not renewed; publication resumes after etcd expiry')
        finally:
            proxy.heal()
            owner.channel.close()
            observer.channel.close()
            proxy.close()
