"""Cliente de diagnóstico independiente, con deadlines y verificación incremental."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from uuid import uuid4

import grpc

from dfsha.common.limits import CHUNK_BYTES, DIAGNOSTIC_BYTES
from dfsha.common.rpc import channel, controlled_error
from dfsha.v1 import diagnostic_pb2 as pb
from dfsha.v1 import diagnostic_pb2_grpc as rpc


def synthetic_chunks(total: int, size: int = CHUNK_BYTES):
    pattern = bytes(range(256))
    for offset in range(0, total, size):
        length = min(size, total - offset)
        yield offset, (pattern * ((length + 511) // 256))[offset % 256:offset % 256 + length]


def diagnose(target: str, cert_dir: Path, identity: str | None, total: int,
             deadline: float = 5, stream_deadline: float = 15) -> dict:
    if not 0 <= total <= DIAGNOSTIC_BYTES or not 0 < deadline <= 30 or not 0 < stream_deadline <= 30:
        raise ValueError("Límite de diagnóstico inválido")
    with channel(target, cert_dir, identity) as connection:
        stub = rpc.DiagnosticServiceStub(connection)
        health = stub.Health(pb.HealthRequest(request_id=str(uuid4())), timeout=deadline)
        expected = hashlib.sha256()
        for _, data in synthetic_chunks(total):
            expected.update(data)

        def frames():
            yield pb.DiagnosticFrame(header=pb.DiagnosticHeader(
                request_id=str(uuid4()), total_bytes=total, sha256=expected.digest()))
            for offset, data in synthetic_chunks(total):
                yield pb.DiagnosticFrame(chunk=pb.DiagnosticChunk(offset=offset, data=data))

        uploaded = stub.StreamDigest(frames(), timeout=stream_deadline)
        received = largest = 0
        downloaded = hashlib.sha256()
        for chunk in stub.GenerateStream(pb.GenerateRequest(request_id=str(uuid4()),
                         total_bytes=total, chunk_bytes=CHUNK_BYTES), timeout=stream_deadline):
            if chunk.offset != received or not 1 <= len(chunk.data) <= CHUNK_BYTES:
                raise ValueError("Stream recibido inválido")
            received += len(chunk.data)
            largest = max(largest, len(chunk.data))
            downloaded.update(chunk.data)
        if (uploaded.received_bytes != total or received != total or
                uploaded.sha256 != expected.digest() or downloaded.digest() != expected.digest()):
            raise ValueError("Integridad del diagnóstico incorrecta")
        return {"status": "EJECUTADO", "version": health.version, "listener": health.listener,
                "diagnostic_ready": health.diagnostic_ready,
                "filesystem_implemented": health.filesystem_implemented,
                "uploaded_bytes": uploaded.received_bytes, "downloaded_bytes": received,
                "sha256": expected.hexdigest(), "chunks": uploaded.chunks,
                "max_chunk_bytes": max(largest, uploaded.max_chunk_bytes)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="localhost:17443")
    parser.add_argument("--cert-dir", type=Path, default=Path(".runtime/certs"))
    parser.add_argument("--identity", choices=["client"])
    parser.add_argument("--bytes", type=int, default=8 * 1024 * 1024 + 17)
    parser.add_argument("--deadline", type=float, default=5)
    parser.add_argument("--stream-deadline", type=float, default=15)
    args = parser.parse_args()
    try:
        result = diagnose(args.target, args.cert_dir, args.identity, args.bytes,
                          args.deadline, args.stream_deadline)
    except grpc.RpcError as error:
        print(json.dumps(controlled_error(error)))
        raise SystemExit(1) from None
    print(json.dumps(result))


if __name__ == "__main__":
    main()
