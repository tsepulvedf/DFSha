"""Shared ordinary-user authorization and references across control processes."""
from concurrent.futures import ThreadPoolExecutor
import threading
from uuid import uuid4
import grpc
import pytest
from ha_runtime import HACluster
from dfsha.client.sdk import Client
from dfsha.v1 import control_pb2 as ctl
from runtime import wait_until


def test_shared_user_revocation_and_open_truncate_gc(run_dir, tmp_path, record_property):
    with HACluster(run_dir/('auth-gc7-'+str(uuid4()))) as lab:
        admin = lab.client(0)
        alice = Client([lab.public_targets[1]], lab.certs)
        bob = Client([lab.public_targets[2]], lab.certs)
        store = lab.metadata()
        try:
            admin.create_user('alice', 'alice-password')
            admin.create_user('bob', 'bob-password')
            alice.login('alice', 'alice-password')
            bob.login('bob', 'bob-password')
            remote = '/home/alice/data'
            source = tmp_path/'ordinary-user'
            content = b'ordinary shared snapshot'*1000
            source.write_bytes(content)
            result = alice.send(source, remote)
            peer = lab.client(2, alice.session)
            try:
                handle = alice.open(remote, 'r+')
                peer.renew_handle(handle)
                assert peer.read(handle, 0, len(content)) == content
                prepared = alice.begin_write(handle, 0, b'X')
                with pytest.raises(grpc.RpcError, match='HANDLE_BUSY'):
                    peer.begin_write(handle, 0, b'Y')
                with pytest.raises(grpc.RpcError, match='HANDLE_BUSY'):
                    peer.close(handle)
                peer.call(peer.files.AbortWrite, ctl.OperationRequest(operation=prepared.operation))
                with pytest.raises(grpc.RpcError, match='PERMISSION_DENIED'):
                    bob.stat(remote)
                admin.chmod(remote, 0)
                with pytest.raises(grpc.RpcError, match='PERMISSION_DENIED'):
                    peer.read(handle, 0, 1)
                admin.chmod(remote, 0o600)
                alice.close(handle)
                # Both calls start together on different controls. The reader
                # must pin either complete root, never a collected intermediate.
                barrier = threading.Barrier(2)
                def open_reader():
                    barrier.wait(20)
                    return peer.open(remote)
                def truncate():
                    barrier.wait(20)
                    return alice.open(remote, 'w')
                with ThreadPoolExecutor(2) as pool:
                    reading = pool.submit(open_reader)
                    truncating = pool.submit(truncate)
                    reader, writer = reading.result(timeout=60), truncating.result(timeout=60)
                alice.close(writer)
                with peer.keepalive(reader):
                    value = peer.read(reader, 0, len(content))
                    assert value == (content if reader.snapshot.size_bytes else b'')
                    # Remove the namespace while the remote handle stays valid.
                    alice.rm(remote)
                    assert peer.read(reader, 0, len(content)) == value
                peer.close(reader)
                def collected():
                    with store.transaction() as tx:
                        return any(row['ref']['file_id'] == result.snapshot.file_id for row in tx.all('retired'))
                assert wait_until(collected, seconds=90)
                record_property('reader_snapshot_bytes', reader.snapshot.size_bytes)
                record_property('authorization', 'CN0 creates/revokes; ordinary session on CN1; CN2 checks current rights')
                record_property('gc', 'concurrent open/truncate across CNs; rm preserves valid snapshot; retirement after close')
            finally:
                peer.shutdown()
        finally:
            admin.shutdown()
            alice.shutdown()
            bob.shutdown()
            store.channel.close()
