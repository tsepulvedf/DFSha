"""Servicio sintético con memoria de aplicación O(fragmento), no un DFS."""
import hashlib

import grpc

from dfsha import __version__
from dfsha.common.limits import CHUNK_BYTES, DIAGNOSTIC_BYTES
from dfsha.common.rpc import abort, require_uuid
from dfsha.common.telemetry import event
from dfsha.v1 import common_pb2 as common
from dfsha.v1 import diagnostic_pb2 as pb
from dfsha.v1 import diagnostic_pb2_grpc as rpc


class Diagnostic(rpc.DiagnosticServiceServicer):
    def __init__(self, listener: str):
        self.listener = listener

    def Health(self, request, context):
        self.require_deadline(context)
        require_uuid(context, request.request_id)
        event("health", listener=self.listener, request_id=request.request_id)
        return pb.HealthResponse(request_id=request.request_id, version=__version__,
                                 listener=self.listener, diagnostic_ready=True,
                                 filesystem_implemented=False, metadata_backend="sqlite-planned")

    def StreamDigest(self, request_iterator, context):
        self.require_deadline(context)
        first = next(request_iterator, None)
        if first is None or first.WhichOneof("frame") != "header":
            abort(context, grpc.StatusCode.INVALID_ARGUMENT, common.INVALID_ARGUMENT)
        header = first.header
        require_uuid(context, header.request_id)
        if header.total_bytes > DIAGNOSTIC_BYTES:
            abort(context, grpc.StatusCode.RESOURCE_EXHAUSTED, common.LIMIT_EXCEEDED)
        if len(header.sha256) != 32:
            abort(context, grpc.StatusCode.INVALID_ARGUMENT, common.INVALID_ARGUMENT)
        received = count = largest = 0
        digest = hashlib.sha256()
        for frame in request_iterator:
            if not context.is_active():
                abort(context, grpc.StatusCode.DEADLINE_EXCEEDED, common.DEADLINE_EXCEEDED)
            if frame.WhichOneof("frame") != "chunk" or frame.chunk.offset != received:
                abort(context, grpc.StatusCode.INVALID_ARGUMENT, common.INVALID_ARGUMENT)
            chunk = frame.chunk.data
            if not 1 <= len(chunk) <= CHUNK_BYTES:
                abort(context, grpc.StatusCode.RESOURCE_EXHAUSTED, common.LIMIT_EXCEEDED)
            received += len(chunk)
            if received > header.total_bytes:
                abort(context, grpc.StatusCode.INVALID_ARGUMENT, common.INVALID_ARGUMENT)
            digest.update(chunk)
            count += 1
            largest = max(largest, len(chunk))
        if received != header.total_bytes:
            abort(context, grpc.StatusCode.INVALID_ARGUMENT, common.INVALID_ARGUMENT)
        if digest.digest() != header.sha256:
            abort(context, grpc.StatusCode.DATA_LOSS, common.CHECKSUM_MISMATCH)
        event("stream_digest", request_id=header.request_id, bytes=received, chunks=count)
        return pb.DigestResult(received_bytes=received, sha256=digest.digest(),
                               chunks=count, max_chunk_bytes=largest)

    def GenerateStream(self, request, context):
        self.require_deadline(context)
        require_uuid(context, request.request_id)
        if request.total_bytes > DIAGNOSTIC_BYTES or not 1 <= request.chunk_bytes <= CHUNK_BYTES:
            abort(context, grpc.StatusCode.RESOURCE_EXHAUSTED, common.LIMIT_EXCEEDED)
        pattern = bytes(range(256))
        for offset in range(0, request.total_bytes, request.chunk_bytes):
            if not context.is_active():
                return
            length = min(request.chunk_bytes, request.total_bytes - offset)
            data = (pattern * ((length + 511) // 256))[offset % 256:offset % 256 + length]
            yield pb.DiagnosticChunk(offset=offset, data=data)
        event("generate_stream", request_id=request.request_id, bytes=request.total_bytes)

    @staticmethod
    def require_deadline(context):
        # El transporte cancela iteradores bloqueados al vencer; no aceptar streams infinitos.
        remaining = context.time_remaining()
        if remaining is None or remaining > 30:
            abort(context, grpc.StatusCode.INVALID_ARGUMENT, common.INVALID_ARGUMENT)
