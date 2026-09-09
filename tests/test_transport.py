from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import grpc
from google.protobuf import message_factory
import pytest

from dfsha.common.limits import CHUNK_BYTES, GRPC_OPTIONS, MESSAGE_BYTES
from dfsha.common.rpc import channel, controlled_error
from dfsha.control.pending import pending_services
from dfsha.v1 import diagnostic_pb2 as pb
from dfsha.v1 import diagnostic_pb2_grpc as rpc
from runtime import PROCESS_FLAGS, ROOT

pytestmark = pytest.mark.integration


@pytest.mark.parametrize("internal", [False, True])
def test_separate_client_process_tls_and_bounded_stream(server, certs, internal, record_property):
    command = [sys.executable, "-m", "dfsha.client.diagnostic", "--target",
               server["internal_target" if internal else "public_target"], "--cert-dir", str(certs)]
    if internal:
        command.extend(["--identity", "client"])
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=40,
                            creationflags=PROCESS_FLAGS)
    assert result.returncode == 0, result.stderr + result.stdout
    report = json.loads(result.stdout)
    assert report["uploaded_bytes"] == report["downloaded_bytes"] == 8 * 1024 * 1024 + 17
    assert report["max_chunk_bytes"] <= CHUNK_BYTES
    # Oráculo independiente del generador incremental del cliente/servidor.
    expected = hashlib.sha256(bytes(range(256)) * 32768 + bytes(range(17))).hexdigest()
    assert report["sha256"] == expected
    assert report["diagnostic_ready"] and not report["filesystem_implemented"]
    record_property("diagnostic", json.dumps(report))


@pytest.mark.parametrize("target,identity,ca", [
    ("public_target", None, "rogue-ca"),
    ("internal_target", None, "ca"),
    ("internal_target", "rogue-client", "ca"),
])
def test_tls_rejects_untrusted_or_missing_certificate(server, certs, target, identity, ca):
    # SAN IP válido; evita que el intento IPv6 agote el plazo antes del rechazo TLS.
    with channel(server[target].replace("localhost", "127.0.0.1"), certs, identity, ca) as connection:
        with pytest.raises(grpc.RpcError) as caught:
            rpc.DiagnosticServiceStub(connection).Health(pb.HealthRequest(request_id=str(uuid4())), timeout=5)
        assert caught.value.code() == grpc.StatusCode.UNAVAILABLE


def test_tls_rejects_wrong_server_san(certs):
    pool = ThreadPoolExecutor(max_workers=1)
    server = grpc.server(pool)
    creds = grpc.ssl_server_credentials([((certs / "wrong-name-server.key").read_bytes(),
                                          (certs / "wrong-name-server.crt").read_bytes())])
    port = server.add_secure_port("127.0.0.1:0", creds)
    server.start()
    try:
        with channel(f"127.0.0.1:{port}", certs) as connection:
            with pytest.raises(grpc.RpcError) as caught:
                rpc.DiagnosticServiceStub(connection).Health(pb.HealthRequest(request_id=str(uuid4())), timeout=2)
            assert caught.value.code() == grpc.StatusCode.UNAVAILABLE
    finally:
        server.stop(0).wait(2)
        pool.shutdown()


@pytest.mark.parametrize("case,code,reason", [
    ("missing_header", grpc.StatusCode.INVALID_ARGUMENT, "INVALID_ARGUMENT"),
    ("offset", grpc.StatusCode.INVALID_ARGUMENT, "INVALID_ARGUMENT"),
    ("oversized", grpc.StatusCode.RESOURCE_EXHAUSTED, "LIMIT_EXCEEDED"),
    ("checksum", grpc.StatusCode.DATA_LOSS, "CHECKSUM_MISMATCH"),
    ("short", grpc.StatusCode.INVALID_ARGUMENT, "INVALID_ARGUMENT"),
])
def test_stream_rejects_invalid_input(server, certs, case, code, reason):
    data = b"abc" if case != "oversized" else b"a" * (CHUNK_BYTES + 1)
    header = pb.DiagnosticFrame(header=pb.DiagnosticHeader(request_id=str(uuid4()),
        total_bytes=len(data), sha256=b"\0" * 32 if case == "checksum" else hashlib.sha256(data).digest()))
    chunk = pb.DiagnosticFrame(chunk=pb.DiagnosticChunk(offset=1 if case == "offset" else 0, data=data))
    frames = [chunk] if case == "missing_header" else [header] if case == "short" else [header, chunk]
    with channel(server["public_target"], certs) as connection:
        with pytest.raises(grpc.RpcError) as caught:
            rpc.DiagnosticServiceStub(connection).StreamDigest(iter(frames), timeout=3)
        assert caught.value.code() == code
        assert controlled_error(caught.value)["reason"] == reason


def test_transport_message_limit(server, certs):
    with channel(server["public_target"], certs) as connection:
        with pytest.raises(grpc.RpcError) as caught:
            rpc.DiagnosticServiceStub(connection).Health(pb.HealthRequest(request_id="a" * MESSAGE_BYTES), timeout=3)
        assert caught.value.code() == grpc.StatusCode.RESOURCE_EXHAUSTED


def test_client_deadline_interrupts_stream(server, certs):
    def slow():
        yield pb.DiagnosticFrame(header=pb.DiagnosticHeader(request_id=str(uuid4()), total_bytes=1,
                                                            sha256=hashlib.sha256(b"a").digest()))
        time.sleep(0.5)
        yield pb.DiagnosticFrame(chunk=pb.DiagnosticChunk(data=b"a"))
    with channel(server["public_target"], certs) as connection:
        with pytest.raises(grpc.RpcError) as caught:
            rpc.DiagnosticServiceStub(connection).StreamDigest(slow(), timeout=0.1)
        assert caught.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED


FUTURE = [(internal, service, method) for internal in (False, True)
          for service in pending_services(internal) for method in service.methods]


@pytest.mark.parametrize("internal,service,method", FUTURE,
                         ids=[f"{s.name}.{m.name}" for _, s, m in FUTURE])
def test_all_future_rpcs_are_unimplemented(server, certs, internal, service, method):
    with channel(server["internal_target" if internal else "public_target"], certs,
                 "client" if internal else None) as connection:
        shape = ("stream" if method.client_streaming else "unary") + "_" + (
            "stream" if method.server_streaming else "unary")
        invoke = getattr(connection, shape)(f"/{service.full_name}/{method.name}",
                    request_serializer=lambda value: value.SerializeToString(),
                    response_deserializer=message_factory.GetMessageClass(method.output_type).FromString)
        request = message_factory.GetMessageClass(method.input_type)()
        with pytest.raises(grpc.RpcError) as caught:
            result = invoke(iter([request]) if method.client_streaming else request, timeout=3)
            if method.server_streaming:
                next(result)
        assert caught.value.code() == grpc.StatusCode.UNIMPLEMENTED
        assert controlled_error(caught.value)["reason"] == "NOT_IMPLEMENTED_STAGE2"
