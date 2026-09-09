"""Compatibilidad real, instancia propia y RBAC restringido a un prefijo único."""
from contextlib import contextmanager
import json
import threading
import time
from uuid import uuid4

import grpc
import pytest

from dfsha.common.etcd_probe_client import EtcdProbeClient, prefix_end
from dfsha.common.rpc import channel, controlled_error
from dfsha._vendor.etcd.api.authpb import auth_pb2 as auth
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb, rpc_pb2_grpc
from dfsha._vendor.etcd.server.etcdserver.api.v3lock.v3lockpb import v3lock_pb2 as lock_pb
from runtime import etcd_process, wait_until

pytestmark = [pytest.mark.integration, pytest.mark.etcd]


@pytest.fixture(scope="module")
def etcd(run_dir, certs):
    prefix = f"/dfsha-stage2/{uuid4()}/".encode()
    leases = []
    with etcd_process(run_dir / "etcd", certs) as (process, target, data):
        with EtcdProbeClient(target, certs, "etcd-root") as admin:
            def ready():
                if process.poll() is not None:
                    raise RuntimeError(f"etcd terminó: consultar {run_dir / 'etcd/etcd.log'}")
                try:
                    admin.kv.Range(pb.RangeRequest(key=prefix), timeout=0.5)
                    return True
                except grpc.RpcError:
                    return False
            wait_until(ready, 20)
            for name in ("root", "dfsha-probe", "dfsha-denied"):
                admin.auth.UserAdd(pb.AuthUserAddRequest(name=name,
                    options=auth.UserAddOptions(no_password=True)), timeout=3)
            admin.auth.UserGrantRole(pb.AuthUserGrantRoleRequest(user="root", role="root"), timeout=3)
            admin.auth.RoleAdd(pb.AuthRoleAddRequest(name="dfsha-probe"), timeout=3)
            admin.auth.RoleGrantPermission(pb.AuthRoleGrantPermissionRequest(name="dfsha-probe",
                perm=auth.Permission(permType=auth.Permission.READWRITE, key=prefix,
                                     range_end=prefix_end(prefix))), timeout=3)
            admin.auth.UserGrantRole(pb.AuthUserGrantRoleRequest(user="dfsha-probe", role="dfsha-probe"), timeout=3)
            admin.auth.AuthEnable(pb.AuthEnableRequest(), timeout=3)
            with EtcdProbeClient(target, certs, "etcd-probe") as client:
                try:
                    yield {"client": client, "admin": admin, "prefix": prefix,
                           "target": target, "leases": leases, "data": data}
                finally:
                    # Nunca DeleteRange global; solo el prefijo exclusivo de esta ejecución.
                    client.kv.DeleteRange(pb.DeleteRangeRequest(key=prefix, range_end=prefix_end(prefix)), timeout=3)
                    remaining = client.kv.Range(pb.RangeRequest(key=prefix, range_end=prefix_end(prefix)), timeout=3)
                    assert not remaining.kvs
                    for lease in leases:
                        try:
                            admin.lease.LeaseRevoke(pb.LeaseRevokeRequest(ID=lease), timeout=3)
                        except grpc.RpcError as error:
                            if error.code() != grpc.StatusCode.NOT_FOUND:
                                raise
                    for name in ("dfsha-probe", "dfsha-denied"):
                        admin.auth.UserDelete(pb.AuthUserDeleteRequest(name=name), timeout=3)
                    admin.auth.RoleDelete(pb.AuthRoleDeleteRequest(role="dfsha-probe"), timeout=3)
                    # root/rol integrado permanecen en este WAL aislado, sin proceso activo al salir.
                    (run_dir / "etcd/cleanup.json").write_text(json.dumps({"prefix": prefix.decode(),
                        "remaining_keys": 0, "test_users_and_role_deleted": True}), encoding="utf-8")


def test_put_get_and_conditional_transactions(etcd, record_property):
    client, key = etcd["client"], etcd["prefix"] + b"kv"
    client.kv.Put(pb.PutRequest(key=key, value=b"first"), timeout=3)
    value = client.kv.Range(pb.RangeRequest(key=key), timeout=3).kvs[0]
    assert value.value == b"first"
    compare = pb.Compare(key=key, target=pb.Compare.MOD, result=pb.Compare.EQUAL,
                         mod_revision=value.mod_revision)
    request = pb.TxnRequest(compare=[compare], success=[pb.RequestOp(
        request_put=pb.PutRequest(key=key, value=b"second"))])
    assert client.kv.Txn(request, timeout=3).succeeded
    assert not client.kv.Txn(request, timeout=3).succeeded
    assert client.kv.Range(pb.RangeRequest(key=key), timeout=3).kvs[0].value == b"second"
    record_property("transaction", "put/get; CAS accepted; stale CAS rejected; value unchanged")


def grant(etcd, ttl):
    lease = etcd["client"].lease.LeaseGrant(pb.LeaseGrantRequest(TTL=ttl), timeout=3)
    assert lease.ID and lease.TTL >= ttl and not lease.error
    etcd["leases"].append(lease.ID)
    return lease.ID


def test_lease_creation_and_real_expiry(etcd, record_property):
    client, key = etcd["client"], etcd["prefix"] + b"ephemeral"
    lease = grant(etcd, 1)
    client.kv.Put(pb.PutRequest(key=key, value=b"leased", lease=lease), timeout=3)
    assert client.kv.Range(pb.RangeRequest(key=key), timeout=3).kvs[0].lease == lease
    start = time.monotonic()
    wait_until(lambda: not client.kv.Range(pb.RangeRequest(key=key), timeout=1).kvs, 8)
    assert client.lease.LeaseTimeToLive(pb.LeaseTimeToLiveRequest(ID=lease), timeout=3).TTL == -1
    record_property("observed_expiry_seconds", round(time.monotonic() - start, 3))


def test_lock_unlock_and_obsolete_ownership_rejected(etcd, record_property):
    client = etcd["client"]
    resource = etcd["prefix"] + b"locks/resource"
    first = client.lock.Lock(lock_pb.LockRequest(name=resource, lease=grant(etcd, 20)), timeout=3)
    owner = client.kv.Range(pb.RangeRequest(key=first.key), timeout=3).kvs[0]
    guarded_key = etcd["prefix"] + b"guarded"

    def transaction(value):
        return pb.TxnRequest(compare=[pb.Compare(key=first.key, target=pb.Compare.CREATE,
                   result=pb.Compare.EQUAL, create_revision=owner.create_revision)],
                   success=[pb.RequestOp(request_put=pb.PutRequest(key=guarded_key, value=value))])

    assert client.kv.Txn(transaction(b"valid-owner"), timeout=3).succeeded
    client.lock.Unlock(lock_pb.UnlockRequest(key=first.key), timeout=3)
    second = client.lock.Lock(lock_pb.LockRequest(name=resource, lease=grant(etcd, 20)), timeout=3)
    current = client.kv.Range(pb.RangeRequest(key=second.key), timeout=3).kvs[0]
    assert second.key != first.key and current.create_revision > owner.create_revision
    assert not client.kv.Txn(transaction(b"obsolete-owner"), timeout=3).succeeded
    assert client.kv.Range(pb.RangeRequest(key=guarded_key), timeout=3).kvs[0].value == b"valid-owner"
    client.lock.Unlock(lock_pb.UnlockRequest(key=second.key), timeout=3)
    assert not client.kv.Range(pb.RangeRequest(key=second.key), timeout=3).kvs
    record_property("fencing", "create_revision compared inside Txn; obsolete owner rejected")


def test_watch_receives_real_event(etcd, record_property):
    client, key = etcd["client"], etcd["prefix"] + b"watched"
    stop = threading.Event()

    def requests():
        yield pb.WatchRequest(create_request=pb.WatchCreateRequest(key=key))
        stop.wait(5)

    stream = client.watch.Watch(requests(), timeout=5)
    try:
        created = next(stream)
        assert created.created and not created.canceled
        committed = client.kv.Put(pb.PutRequest(key=key, value=b"event"), timeout=3)
        notification = next(stream)
        assert notification.events[0].kv.value == b"event"
        assert notification.events[0].kv.mod_revision == committed.header.revision
        record_property("watch_revision", committed.header.revision)
    finally:
        stop.set()
        stream.cancel()


def test_mtls_identity_and_rbac_are_enforced(etcd, certs):
    # Auth activada comprobada a través del administrador por certificado CN=root.
    assert etcd["admin"].auth.AuthStatus(pb.AuthStatusRequest(), timeout=3).enabled
    with EtcdProbeClient(etcd["target"], certs, "etcd-denied") as denied:
        with pytest.raises(grpc.RpcError) as caught:
            denied.kv.Range(pb.RangeRequest(key=etcd["prefix"]), timeout=3)
        assert caught.value.code() == grpc.StatusCode.PERMISSION_DENIED
    # La única consulta fuera del prefijo es negativa y no escribe datos.
    with pytest.raises(grpc.RpcError) as caught:
        etcd["client"].kv.Range(pb.RangeRequest(key=b"/dfsha-stage2/forbidden"), timeout=3)
    assert caught.value.code() == grpc.StatusCode.PERMISSION_DENIED
    for identity, ca in ((None, "ca"), ("rogue-client", "ca"), ("etcd-probe", "rogue-ca")):
        with channel(etcd["target"].replace("localhost", "127.0.0.1"), certs, identity, ca) as connection:
            with pytest.raises(grpc.RpcError) as caught:
                rpc_pb2_grpc.KVStub(connection).Range(pb.RangeRequest(key=etcd["prefix"]), timeout=5)
            assert caught.value.code() == grpc.StatusCode.UNAVAILABLE


def test_unavailable_service_has_controlled_error(certs, run_dir, record_property):
    with etcd_process(run_dir / "etcd-unavailable", certs) as (process, target, _):
        with EtcdProbeClient(target.replace("localhost", "127.0.0.1"), certs, "etcd-root") as client:
            grpc.channel_ready_future(client.channel).result(timeout=20)
            # Parada de NUESTRA instancia; no confundir puerto abierto de otro proceso.
            process.terminate()
            process.wait(timeout=10)
            started = time.monotonic()
            with pytest.raises(grpc.RpcError) as caught:
                client.kv.Range(pb.RangeRequest(key=b"/dfsha-stage2/unavailable"), timeout=2)
            report = controlled_error(caught.value)
            # Un transporte roto puede detectarse antes o después del plazo.
            assert report["code"] in {"UNAVAILABLE", "DEADLINE_EXCEEDED"}
            assert report["status"] == "FALLIDO" and time.monotonic() - started < 5
            record_property("controlled_unavailability", json.dumps(report))
