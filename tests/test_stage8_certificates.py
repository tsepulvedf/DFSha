"""Rolling leaf replacement and expired leaf rejection on real TLS connections."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import socket
import ssl
import tomllib

import grpc
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization

from dfsha.common import node_rpc
from dfsha.common.domain import uid
from dfsha.common.rpc import channel
from dfsha.v1 import diagnostic_pb2 as d, diagnostic_pb2_grpc as dg, namespace_pb2 as ns
from ha_runtime import HACluster
from hito2_runtime import write_toml
from issue_certificate import issue
from runtime import wait_until


def test_expired_server_certificate_is_rejected(certs):
    leaf = x509.load_pem_x509_certificate((certs/'server.crt').read_bytes())
    ca = x509.load_pem_x509_certificate((certs/'ca.crt').read_bytes())
    signer = serialization.load_pem_private_key((certs/'ca.key').read_bytes(), password=None)
    now = datetime.now(timezone.utc)
    builder = (x509.CertificateBuilder().subject_name(leaf.subject).issuer_name(ca.subject)
        .public_key(leaf.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(days=2)).not_valid_after(now-timedelta(days=1)))
    for extension in leaf.extensions:
        builder = builder.add_extension(extension.value, extension.critical)
    expired = builder.sign(signer, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
    calls = []
    with ThreadPoolExecutor(1) as pool:
        server = grpc.server(pool)
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler('dfsha.v1.DiagnosticService', {
            'Health': grpc.unary_unary_rpc_method_handler(lambda req, ctx: calls.append(True) or d.HealthResponse(),
                request_deserializer=d.HealthRequest.FromString, response_serializer=lambda value: value.SerializeToString())}),))
        port = server.add_secure_port('127.0.0.1:0', grpc.ssl_server_credentials([((certs/'server.key').read_bytes(), expired)]))
        server.start()
        try:
            with channel(f'127.0.0.1:{port}', certs) as connection:
                with pytest.raises(grpc.RpcError) as error:
                    dg.DiagnosticServiceStub(connection).Health(d.HealthRequest(request_id=uid()), timeout=2)
                assert error.value.code() == grpc.StatusCode.UNAVAILABLE
            assert not calls
        finally:
            server.stop(0).wait(3)


def test_rolling_peer_and_datanode_certificates_then_quorum_loss(run_dir, tmp_path, record_property):
    with HACluster(run_dir/'certificates-e8', protected=True) as lab:
        client = lab.client()
        try:
            source = tmp_path/'source'
            source.write_bytes(b'rotation without losing quorum'*1000)
            client.send(source, '/home/admin/retained')
            handle = client.open('/home/admin/retained')
            with client.keepalive(handle):
                serials = []
                for index, member in enumerate(lab.etcd.members):
                    identity = f'etcd-member-{index}'
                    output = run_dir/('renewed-etcd-'+str(index))
                    leaf = issue(lab.authority, output, identity, common_name=f'dfsha-etcd-member-{index}')
                    member.stop()
                    for flag, suffix in (('--cert-file=', '.crt'), ('--key-file=', '.key'),
                                         ('--peer-cert-file=', '.crt'), ('--peer-key-file=', '.key')):
                        member.args = [flag+str(output/(identity+suffix)) if arg.startswith(flag) else arg for arg in member.args]
                    member.start()
                    def ready():
                        try:
                            return lab.etcd.status()
                        except grpc.RpcError:
                            return None
                    wait_until(ready, seconds=30)
                    ctx = ssl.create_default_context(cafile=str(lab.authority/'ca.crt'))
                    cn = lab.control_ids[0]
                    ctx.load_cert_chain(str(lab.authority/(cn+'.crt')), str(lab.authority/(cn+'.key')))
                    host, port = member.target.rsplit(':', 1)
                    with socket.create_connection((host, int(port)), timeout=3) as raw:
                        with ctx.wrap_socket(raw, server_hostname=host) as transport:
                            assert x509.load_der_x509_certificate(transport.getpeercert(binary_form=True)).serial_number == leaf['serial']
                    assert client.read(handle, 0, 8) == b'rotation'
                    serials.append(leaf['serial'])
                node = lab.nodes[0]
                cfg = tomllib.loads(node.config.read_text(encoding='utf-8'))['datanode']
                issued = run_dir/'renewed-datanode'
                issue(lab.authority, issued, cfg['certificate_identity'])
                node.stop()
                cfg['certificate_dir'] = issued.as_posix()
                write_toml(node.config, 'datanode', cfg)
                node.start()
                lab.wait_ready(3, client)
                assert client.read(handle, 0, 8) == b'rotation'
                lab.etcd.members[0].stop()
                lab.etcd.members[1].stop()
                for action in ('Stat', 'Mkdir'):
                    req = client.prepare(ns.PathRequest(path=client.path('/home/admin/forbidden-minority')))
                    with pytest.raises(grpc.RpcError) as error:
                        getattr(client.namespace, action)(req, metadata=client.metadata, timeout=4)
                    assert error.value.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)
                lab.etcd.members[0].start()
                lab.etcd.members[1].start()
                wait_until(ready, seconds=30)
                with pytest.raises(grpc.RpcError, match='NOT_FOUND'):
                    client.stat('/home/admin/forbidden-minority')
                assert client.read(handle, 0, 8) == b'rotation'
                record_property('new_peer_serials_verified_by_tls', json.dumps(serials))
                record_property('quorum', 'two members down: no read authorization or namespace publication; restored majority preserves snapshot')
            client.close(handle)
        finally:
            client.shutdown()
