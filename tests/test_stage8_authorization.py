"""Real HA identities, groups and transactional revocation in the protected profile."""
import grpc
import pytest
import hashlib

from dfsha.client.sdk import Client
from dfsha.v1 import common_pb2 as c
from dfsha.v1 import control_pb2 as ctl
from ha_runtime import HACluster
from runtime import wait_until
from dfsha.common.domain import now


def denied(call, code=grpc.StatusCode.PERMISSION_DENIED):
    with pytest.raises(grpc.RpcError) as failure:
        call()
    assert failure.value.code() == code


def test_groups_shared_revocation_password_and_prepared_commit(run_dir, tmp_path, record_property):
    with HACluster(run_dir/'auth-e8', protected=True) as lab:
        admin = lab.client(0)
        alice = Client(lab.public_targets, lab.certs)
        bob = Client(lab.public_targets, lab.certs)
        peer = None
        try:
            user = admin.create_user('alice', 'alice-password')
            other = admin.create_user('bob', 'bob-password')
            alice.login('alice', 'alice-password')
            bob.login('bob', 'bob-password')
            peer = Client([lab.public_targets[2]], lab.certs, alice.session)
            file = '/home/alice/document'
            source = tmp_path/'source'
            source.write_bytes(b'private-content'*100)
            alice.send(source, file)
            denied(lambda: bob.stat(file))
            denied(lambda: admin.open(file))  # Policy administration is not content-read authority.
            denied(lambda: bob.create_group('forbidden'))
            denied(lambda: bob.set_user(user.user_id, user.revision, True))
            team = admin.create_group('readers')
            team = admin.set_group_members(team.group_id, team.revision, [other.user_id])
            acl = alice.get_acl('/home/alice')
            acl.entries.add(principal_id=team.group_id, is_group=True, permissions=1)
            alice.set_acl('/home/alice', acl)
            acl = alice.get_acl(file)
            acl.entries.add(principal_id=team.group_id, is_group=True, permissions=4)
            alice.set_acl(file, acl)
            reader = bob.open(file)
            assert bob.read(reader, 0, 7) == b'private'
            denied(lambda: list(bob.ls('/home/alice')))  # Consume the streaming SDK iterator.
            denied(lambda: bob.mkdir('/home/alice/forbidden'))
            team = admin.set_group_members(team.group_id, team.revision, [])
            denied(lambda: bob.read(reader, 0, 1))
            bob.close(reader)
            handle = alice.open(file, 'r+')
            plan = alice.begin_write(handle, 0, b'X')
            with alice.write_keepalive(handle, plan):
                changes = alice.prepare_blocks(handle, plan, b'X')
                alice.wait_durable(plan.operation.operation_id)
                before = handle.snapshot.SerializeToString()
                alice.chmod(file, 0o400)
                denied(lambda: peer.commit_write(handle, plan, changes))
                assert handle.snapshot.SerializeToString() == before
                peer.call(peer.files.AbortWrite, ctl.OperationRequest(operation=plan.operation))
                assert peer.read(handle, 0, 7) == b'private'
            alice.close(handle)
            changed = admin.change_password(user.user_id, user.revision, 'new-alice-password')
            denied(lambda: peer.stat(file), grpc.StatusCode.UNAUTHENTICATED)
            denied(lambda: alice.login('alice', 'alice-password'), grpc.StatusCode.UNAUTHENTICATED)
            alice.login('alice', 'new-alice-password')
            assert alice.stat(file).size_bytes == source.stat().st_size
            disabled = admin.set_user(user.user_id, changed.revision, True)
            denied(lambda: alice.stat(file), grpc.StatusCode.UNAUTHENTICATED)
            admin.set_user(user.user_id, disabled.revision, False)
            denied(lambda: alice.stat(file), grpc.StatusCode.UNAUTHENTICATED)
            alice.login('alice', 'new-alice-password')
            store = lab.metadata()
            try:
                # Shorten only this isolated fixture's authoritative deadline.
                # Real wall time passes; no monkeypatch or client clock decides it.
                with store.transaction(True) as tx:
                    session = tx.get('session', hashlib.sha256(alice.session.token).hexdigest())
                    session['expires'] = now()+2000
                    tx.put('session', session)
                other_control = Client([lab.public_targets[1]], lab.certs, alice.session)
                try:
                    def expired():
                        try:
                            other_control.stat(file)
                            return False
                        except grpc.RpcError as failure:
                            assert failure.code() == grpc.StatusCode.UNAUTHENTICATED
                            return True
                    wait_until(expired, seconds=15)
                finally:
                    other_control.shutdown()
            finally:
                store.channel.close()
            record_property('revocation', 'group membership; W2-before-commit; password; disable/enable; across CNs')
            record_property('session_expiry', 'real time after shortened authoritative fixture deadline; rejected through another CN')
        finally:
            if peer:
                peer.shutdown()
            admin.shutdown()
            alice.shutdown()
            bob.shutdown()
