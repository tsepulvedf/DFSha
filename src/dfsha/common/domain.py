"""Valores y errores compartidos; sin transporte, disco ni estado global mutable."""
import base64
import hashlib
import json
import time
import unicodedata
from uuid import UUID, uuid4

import grpc
from google.protobuf.json_format import MessageToDict, ParseDict

CHUNK = 262144
PROFILES = (4194304, 67108864, 134217728)
DEADLINES = dict(zip(PROFILES, (30, 120, 240)))


class Fault(Exception):
    def __init__(self, reason, code=None):
        super().__init__(reason)
        self.reason = reason
        self.code = code or {
            'UNAUTHENTICATED': grpc.StatusCode.UNAUTHENTICATED,
            'PERMISSION_DENIED': grpc.StatusCode.PERMISSION_DENIED,
            'NOT_FOUND': grpc.StatusCode.NOT_FOUND,
            'ALREADY_EXISTS': grpc.StatusCode.ALREADY_EXISTS,
            'IDEMPOTENCY_MISMATCH': grpc.StatusCode.ALREADY_EXISTS,
            'INVALID_ARGUMENT': grpc.StatusCode.INVALID_ARGUMENT,
            'LIMIT_EXCEEDED': grpc.StatusCode.RESOURCE_EXHAUSTED,
            'UNSUPPORTED_MODE': grpc.StatusCode.INVALID_ARGUMENT,
            'VERSION_CONFLICT': grpc.StatusCode.ABORTED,
            'LIST_CHANGED': grpc.StatusCode.ABORTED,
            'LOCK_BUSY': grpc.StatusCode.ABORTED,
            'DATA_UNAVAILABLE': grpc.StatusCode.UNAVAILABLE,
            'DEADLINE_EXCEEDED': grpc.StatusCode.DEADLINE_EXCEEDED,
            'NO_SPACE': grpc.StatusCode.RESOURCE_EXHAUSTED,
            'DATA_LOSS': grpc.StatusCode.DATA_LOSS,
            'CHECKSUM_MISMATCH': grpc.StatusCode.DATA_LOSS,
            'SERVICE_UNAVAILABLE': grpc.StatusCode.UNAVAILABLE,
        }.get(reason, grpc.StatusCode.FAILED_PRECONDITION)


def need(condition, reason='INVALID_ARGUMENT'):
    if not condition:
        raise Fault(reason)


def uid():
    return str(uuid4())


def uuid(value):
    try:
        need(str(UUID(value)) == value)
    except (ValueError, TypeError, AttributeError):
        raise Fault('INVALID_ARGUMENT') from None
    return value


def now():
    return int(time.time() * 1000)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()


def asdict(message):
    return MessageToDict(message, preserving_proto_field_name=True)


def proto(cls, value):
    return ParseDict(value, cls())


def intent(message):
    # Context, credentials and server expiry are not an instruction. Omitted proto3
    # defaults have one canonical representation via MessageToDict on both ends.
    def clean(obj):
        if isinstance(obj, dict):
            return {k: clean(v) for k, v in obj.items() if k not in
                    {'context', 'password', 'capability', 'expires_at_unix_ms'}}
        if isinstance(obj, list):
            return [clean(v) for v in obj]
        return unicodedata.normalize('NFC', obj) if isinstance(obj, str) else obj
    return hashlib.sha256(canonical(clean(asdict(message)))).digest()


def manifest_hash(blocks):
    return hashlib.sha256(canonical([asdict(b) for b in blocks])).digest()


def b64(value):
    return base64.b64encode(value).decode()
