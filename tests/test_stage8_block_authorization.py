"""Capabilities remain scoped in protected HA; write-only patches do not reveal bases."""
from copy import deepcopy
import hashlib

import grpc
import pytest

from dfsha.client.sdk import Client
from dfsha.common.rpc import channel
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl, data_pb2 as d, data_pb2_grpc as dg
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as ep
from ha_runtime import HACluster
from measure_stage6 import full
from test_hito2 import resolve


def rejected(call, code):
    with pytest.raises(grpc.RpcError) as caught:
        call()
    assert caught.value.code() == code


def test_scoped_capabilities_write_only_and_revoked_lease(run_dir, tmp_path, record_property):
    with HACluster(run_dir/'block-security-e8', protected=True) as lab:
        admin = lab.client()
        admin.create_user('writer', 'writer-password')
        admin.create_user('outsider', 'outsider-password')
        admin.shutdown()
        owner, outsider = Client(lab.public_targets, lab.certs), Client(lab.public_targets, lab.certs)
        owner.login('writer', 'writer-password')
        outsider.login('outsider', 'outsider-password')
        try:
            path = '/home/writer/only-write'
            handle = owner.open(path, 'w')
            assert owner.write(handle, 0, b'original-content') == 16
            owner.chmod(path, 0o200)
            before = deepcopy(owner.traffic)
            assert owner.write(handle, 0, b'NEW') == 3
            rejected(lambda: owner.read(handle, 0, 3), grpc.StatusCode.PERMISSION_DENIED)
            assert all(row.get('client_read_bytes', 0) == before.get(node, {}).get('client_read_bytes', 0)
                       for node, row in owner.traffic.items())
            assert sum(row.get('client_write_bytes', 0)-before.get(node, {}).get('client_write_bytes', 0)
                       for node, row in owner.traffic.items()) == 3
            owner.close(handle)
            owner.chmod(path, 0o600)
            full(owner, path)
            handle = owner.open(path)
            assert owner.read(handle, 0, 16) == b'NEWginal-content'
            plan = resolve(owner, handle).blocks[0]
            request = owner.prepare(d.GetBlockRequest(handle_id=handle.handle_id, snapshot=handle.snapshot,
                block=plan.block, offset=plan.grants[0].offset, length=plan.grants[0].length,
                capability=plan.grants[0].capability))
            original = d.GetBlockRequest.FromString(request.SerializeToString())
            location = next(x for x in plan.locations if x.node_id == plan.grants[0].node_id)
            with channel(location.client_endpoint, lab.certs) as connection:
                rpc = dg.BlockServiceStub(connection).GetBlock
                request.capability = b'wrong-capability'
                rejected(lambda: list(rpc(request, metadata=owner.metadata, timeout=30)), grpc.StatusCode.PERMISSION_DENIED)
                request.CopyFrom(original)
                request.length -= 1
                rejected(lambda: list(rpc(request, metadata=owner.metadata, timeout=30)), grpc.StatusCode.PERMISSION_DENIED)
                request.CopyFrom(original)
                request.context.CopyFrom(outsider.prepare(d.GetBlockRequest()).context)
                rejected(lambda: list(rpc(request, metadata=outsider.metadata, timeout=30)), grpc.StatusCode.FAILED_PRECONDITION)
                request.CopyFrom(original)
                rejected(lambda: list(rpc(request, timeout=30)), grpc.StatusCode.UNAUTHENTICATED)
            other = next(x for x in plan.locations if x.node_id != location.node_id)
            with channel(other.client_endpoint, lab.certs) as connection:
                rejected(lambda: list(dg.BlockServiceStub(connection).GetBlock(original, metadata=owner.metadata, timeout=30)),
                         grpc.StatusCode.PERMISSION_DENIED)
            operation = owner.last_operation.operation_id
            rejected(lambda: outsider.operation(operation), grpc.StatusCode.NOT_FOUND)
            # Actual etcd lease revocation, while the old local deadline is still in the future.
            store = lab.metadata()
            try:
                with store.transaction() as tx:
                    stored = tx.get('handle', handle.handle_id)
                store.rpc(store.lease.LeaseRevoke, ep.LeaseRevokeRequest(ID=stored['lease']))
            finally:
                store.channel.close()
            with channel(location.client_endpoint, lab.certs) as connection:
                rejected(lambda: list(dg.BlockServiceStub(connection).GetBlock(original, metadata=owner.metadata, timeout=30)),
                         grpc.StatusCode.FAILED_PRECONDITION)
            fresh = owner.open(path)
            assert owner.read(fresh, 0, 16) == b'NEWginal-content'
            owner.close(fresh)
            record_property('write_only_delta_bytes', 3)
            record_property('content_sha256', hashlib.sha256(b'NEWginal-content').hexdigest())
            record_property('rejections', 'tampered capability; wider action than grant; wrong session; absent session; wrong destination; foreign result; revoked lease')
        finally:
            owner.shutdown()
            outsider.shutdown()
