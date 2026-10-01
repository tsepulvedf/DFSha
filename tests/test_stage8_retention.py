import hashlib
import os

import pytest

from dfsha.common.domain import Fault
from dfsha.control.etcd_metadata import encode
from ha_runtime import HACluster
from ha_recovery import backup_protected_lab
from metadata_retention import collect_pages, release_pin


def test_offline_retention_keeps_live_snapshot_and_replay_results(run_dir, tmp_path, record_property):
    with HACluster(run_dir/'retention-e8', protected=True) as lab:
        client = lab.client()
        store = lab.metadata()
        try:
            source = tmp_path/'source'
            source.write_bytes(b'retained metadata and blocks'*500)
            upload = client.send(source, '/home/admin/data')
            handle = client.open('/home/admin/data')
            with store.transaction(True) as tx:
                snap = tx.get('snapshot', tx.get('handle', handle.handle_id)['snapshot'])
                tx.put('migration-pin', dict(id=snap['id'], snapshot=snap['id']))
                tx.put('retention-fixture', dict(id='superseded', value='old'))
            with store.transaction(True) as tx:
                tx.put('retention-fixture', dict(id='superseded', value='new'))
            with pytest.raises(Fault, match='LOCK_BUSY'):
                collect_pages(lab)
            backup_protected_lab(lab, run_dir/'retention-backup', os.urandom(32))
            snapshot_digest = hashlib.sha256(encode(snap)).hexdigest()
            with pytest.raises(Fault, match='VERSION_CONFLICT'):
                release_pin(lab, snap['id'], '0'*64)
            with store.transaction() as tx:
                assert tx.get('migration-pin', snap['id'])
            result = release_pin(lab, snap['id'], snapshot_digest)
            assert release_pin(lab, snap['id'], snapshot_digest) == result
            report = collect_pages(lab)
            assert report['deleted'] > 0 and report['retained'] > 0
            # New process cache: pages must really be present and decryptable.
            fresh = lab.metadata()
            try:
                with fresh.transaction() as tx:
                    assert tx.get('snapshot', snap['id']) == snap
                    assert tx.get('upload', upload.operation.operation_id)['state'] == 2  # COMMITTED
                    assert tx.get('retention-fixture', 'superseded')['value'] == 'new'
                    assert tx.all('ledger')
            finally:
                fresh.channel.close()
            for control in lab.controls:
                control.start()
            for node in lab.nodes[:3]:
                node.start()
            lab.wait_ready(3, client)
            client.receive('/home/admin/data', tmp_path/'download')
            assert (tmp_path/'download').read_bytes() == source.read_bytes()
            record_property('retention', str(report))
        finally:
            client.shutdown()
            store.channel.close()
