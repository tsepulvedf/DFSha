"""Actual etcd RBAC and auxiliary TLS scope; rejected work has no KV side effect."""
import http.client
import json
import ssl
from urllib.parse import urlparse

import grpc
import pytest

from dfsha.common.etcd_probe_client import EtcdProbeClient
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb
from ha_runtime import HACluster


def request(target, certs, identity=None, path='/health'):
    ctx = ssl.create_default_context(cafile=str(certs/'ca.crt'))
    if identity:
        ctx.load_cert_chain(str(certs/(identity+'.crt')), str(certs/(identity+'.key')))
    connection = http.client.HTTPSConnection(target, context=ctx, timeout=3)
    try:
        connection.request('GET', path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_protected_etcd_rbac_peer_roles_and_auxiliary_scope(run_dir, record_property):
    with HACluster(run_dir/'etcd-security-e8', protected=True) as lab:
        target, certs = lab.etcd.targets[0], lab.authority
        probe = (lab.etcd.prefix+'/forbidden-test').encode()
        with EtcdProbeClient(target, certs, 'etcd-root') as admin:
            assert admin.auth.AuthStatus(pb.AuthStatusRequest(), timeout=3).enabled
            for identity, key in ((lab.node_ids[0], probe), (lab.control_ids[0], b'/outside-dfsha')):
                with EtcdProbeClient(target, certs, identity) as actor:
                    with pytest.raises(grpc.RpcError) as denied:
                        actor.kv.Put(pb.PutRequest(key=key, value=b'forbidden'), timeout=3)
                    assert denied.value.code() in (grpc.StatusCode.PERMISSION_DENIED, grpc.StatusCode.UNAUTHENTICATED)
                assert not admin.kv.Range(pb.RangeRequest(key=key), timeout=3).kvs
        with pytest.raises((ssl.SSLError, ConnectionError, http.client.RemoteDisconnected)):
            request(target, certs)
        status, _ = request(target, certs, lab.node_ids[0], '/metrics')
        # Metrics are mTLS guarded, but etcd KV RBAC does not cover this route.
        assert status == 200
        peer = next(arg.split('=', 1)[1] for arg in lab.etcd.members[0].args if arg.startswith('--listen-peer-urls='))
        with pytest.raises((ssl.SSLError, ConnectionError, http.client.RemoteDisconnected)):
            request(urlparse(peer).netloc, certs, lab.node_ids[0])
        assert len(lab.etcd.status()) == 3
        record_property('auxiliary_endpoints', 'loopback+mTLS; /metrics accessible to trusted CA identities, not KV RBAC')
        record_property('peer_roles', 'DataNode certificate rejected by peer CN allowlist; cluster still has three members')
