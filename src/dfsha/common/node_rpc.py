"""Transporte interno: identidad del certificado, límites y errores sin secretos."""
import importlib
from pathlib import Path
import sqlite3
import grpc
from google.protobuf import message_factory
from dfsha.common.domain import Fault, need, uid
from dfsha.common.limits import GRPC_OPTIONS
from dfsha.common.rpc import abort
from dfsha.v1 import common_pb2 as c


def peer(context):
    values = context.auth_context().get('x509_common_name', ())
    need(len(values) == 1, 'UNAUTHENTICATED')
    return values[0].decode('utf-8')


def channel(target, cfg):
    certs = Path(cfg['certificate_dir'])
    identity = cfg['certificate_identity']
    return grpc.secure_channel(target, grpc.ssl_channel_credentials(
        (certs / 'ca.crt').read_bytes(), (certs / (identity + '.key')).read_bytes(),
        (certs / (identity + '.crt')).read_bytes()), options=GRPC_OPTIONS)


def context_for(cfg):
    return c.RequestContext(request_id=uid(), user_id=cfg['certificate_identity'],
                            service_epoch=cfg['service_epoch'])


def register(server, app, services):
    implemented = set()
    for module, service_name in services:
        service = importlib.import_module(f'dfsha.v1.{module}_pb2').DESCRIPTOR.services_by_name[service_name]
        handlers = {}
        for method in service.methods:
            if not hasattr(app, method.name):
                continue
            fn = getattr(app, method.name)
            def invoke(request, ctx, fn=fn, maximum=302 if method.client_streaming else app.cfg.get('control_rpc_timeout_seconds', 5)+2):
                try:
                    need(ctx.time_remaining() is not None and ctx.time_remaining() <= maximum)
                    return fn(request, ctx)
                except Fault as exc:
                    import traceback
                    from dfsha.common.telemetry import event
                    frames = traceback.extract_tb(exc.__traceback__)
                    site = frames[-2] if len(frames) > 1 else frames[-1]
                    event('node_rpc_rejected', code=fn.__name__ + ':' + exc.reason + ':' + Path(site.filename).name + ':' + str(site.lineno))
                    abort(ctx, exc.code, c.ErrorReason.Value(exc.reason))
                except grpc.RpcError as exc:
                    from dfsha.common.rpc import controlled_error
                    reason = controlled_error(exc)['reason']
                    abort(ctx, exc.code(), c.ErrorReason.Value(reason) if reason in c.ErrorReason.keys() else c.SERVICE_UNAVAILABLE)
                except (sqlite3.Error, OSError):
                    abort(ctx, grpc.StatusCode.UNAVAILABLE, c.SERVICE_UNAVAILABLE)
            def stream(request, ctx, fn=fn):
                try:
                    need(ctx.time_remaining() is not None and ctx.time_remaining() <= 302)
                    yield from fn(request, ctx)
                except Fault as exc:
                    abort(ctx, exc.code, c.ErrorReason.Value(exc.reason))
                except grpc.RpcError as exc:
                    from dfsha.common.rpc import controlled_error
                    reason = controlled_error(exc)['reason']
                    abort(ctx, exc.code(), c.ErrorReason.Value(reason) if reason in c.ErrorReason.keys() else c.SERVICE_UNAVAILABLE)
                except (sqlite3.Error, OSError):
                    abort(ctx, grpc.StatusCode.UNAVAILABLE, c.SERVICE_UNAVAILABLE)
            shape = ('stream' if method.client_streaming else 'unary') + '_' + ('stream' if method.server_streaming else 'unary')
            handlers[method.name] = getattr(grpc, shape + '_rpc_method_handler')(
                stream if method.server_streaming else invoke,
                request_deserializer=message_factory.GetMessageClass(method.input_type).FromString,
                response_serializer=lambda value: value.SerializeToString())
            implemented.add((service.full_name, method.name))
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(service.full_name, handlers),))
    return implemented
