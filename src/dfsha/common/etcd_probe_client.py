"""Acceso oficial v3 para compatibilidad E2; no implementa MetadataStore/Coordinator."""
from pathlib import Path

from dfsha.common.rpc import channel
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2_grpc as etcd_grpc
from dfsha._vendor.etcd.server.etcdserver.api.v3lock.v3lockpb import v3lock_pb2_grpc


class EtcdProbeClient:
    def __init__(self, target: str, certs: Path, identity: str):
        self.channel = channel(target, certs, identity)
        self.kv = etcd_grpc.KVStub(self.channel)
        self.lease = etcd_grpc.LeaseStub(self.channel)
        self.watch = etcd_grpc.WatchStub(self.channel)
        self.auth = etcd_grpc.AuthStub(self.channel)
        self.lock = v3lock_pb2_grpc.LockStub(self.channel)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.channel.close()


def prefix_end(prefix: bytes) -> bytes:
    for index in range(len(prefix) - 1, -1, -1):
        if prefix[index] < 255:
            return prefix[:index] + bytes([prefix[index] + 1])
    return b"\0"
