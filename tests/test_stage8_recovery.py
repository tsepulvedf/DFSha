"""Protected offline HA backup and independent restoration with authorized keys."""
import hashlib
import os
import pytest

from dfsha.common.domain import Fault
from ha_runtime import HACluster
from ha_recovery import backup_protected_lab, RestoredHACluster


def test_protected_ha_backup_and_restore(run_dir, tmp_path, record_property):
    archive_key = os.urandom(32)
    source = tmp_path/'file'
    source.write_bytes(b'independent encrypted recovery'*5000)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    backup = run_dir/'secure-backup'
    with HACluster(run_dir/'secure-source', protected=True) as lab:
        admin = lab.client()
        try:
            admin.create_user('alice', 'alice-password')
            from dfsha.client.sdk import Client
            client = Client(lab.public_targets, lab.certs)
            try:
                client.login('alice', 'alice-password')
                client.send(source, '/home/alice/recovery')
            finally:
                client.shutdown()
            evidence = backup_protected_lab(lab, backup, archive_key)
        finally:
            admin.shutdown()
    with pytest.raises(Fault, match='DATA_LOSS'):
        RestoredHACluster(backup, run_dir/'wrong-recovery', archive_key=os.urandom(32))
    assert not (run_dir/'wrong-recovery').exists()
    with RestoredHACluster(backup, run_dir/'secure-restored', archive_key=archive_key) as restored:
        from dfsha.client.sdk import Client
        client = Client(restored.public_targets, restored.certs)
        try:
            client.login('alice', 'alice-password')
            client.receive('/home/alice/recovery', tmp_path/'restored-file')
            assert hashlib.sha256((tmp_path/'restored-file').read_bytes()).hexdigest() == digest
            assert client.get_acl('/home/alice/recovery').owner_id == client.session.user_id
            record_property('sha256', digest)
            record_property('backup', str(evidence))
        finally:
            client.shutdown()
