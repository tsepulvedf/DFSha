"""Canales verificados y errores estables, sin desactivar comprobaciones TLS."""
from pathlib import Path
from uuid import UUID

import grpc

from dfsha.common.limits import GRPC_OPTIONS
from dfsha.v1 import common_pb2 as common


def abort(context, code: grpc.StatusCode, reason: int, request_id: str = ""):
    detail = common.ErrorDetail(reason=reason, request_id=request_id, retryable=False)
    context.set_trailing_metadata((("dfsha-error-bin", detail.SerializeToString()),))
    context.abort(code, common.ErrorReason.Name(reason))


def require_uuid(context, value: str) -> None:
    try:
        if str(UUID(value)) != value:
            raise ValueError()
    except ValueError:
        abort(context, grpc.StatusCode.INVALID_ARGUMENT, common.INVALID_ARGUMENT)


def channel(target: str, cert_dir: Path, identity: str | None = None,
            ca_name: str = "ca") -> grpc.Channel:
    credentials = grpc.ssl_channel_credentials(
        root_certificates=(cert_dir / f"{ca_name}.crt").read_bytes(),
        private_key=(cert_dir / f"{identity}.key").read_bytes() if identity else None,
        certificate_chain=(cert_dir / f"{identity}.crt").read_bytes() if identity else None,
    )
    return grpc.secure_channel(target, credentials, options=GRPC_OPTIONS)


def controlled_error(error: grpc.RpcError) -> dict:
    reason = error.code().name
    for key, value in error.trailing_metadata() or ():
        if key == "dfsha-error-bin":
            reason = common.ErrorReason.Name(common.ErrorDetail.FromString(value).reason)
    return {"status": "FALLIDO", "code": error.code().name, "reason": reason}
