"""Registrar contratos futuros, sin respuestas que aparenten negocio implementado."""
import importlib

import grpc
from google.protobuf import message_factory

from dfsha.common.rpc import abort
from dfsha.v1 import common_pb2 as common

PUBLIC_MODULES = ("identity", "namespace", "control", "data")
INTERNAL_MODULES = ("nodes", "data")


def pending_services(internal: bool):
    for module in INTERNAL_MODULES if internal else PUBLIC_MODULES:
        descriptor = importlib.import_module(f"dfsha.v1.{module}_pb2").DESCRIPTOR
        for service in descriptor.services_by_name.values():
            if module == "data" and (service.name == "ReplicaService") != internal:
                continue
            yield service


def register(server: grpc.Server, internal: bool) -> None:
    def unimplemented(request, context):
        abort(context, grpc.StatusCode.UNIMPLEMENTED, common.NOT_IMPLEMENTED_STAGE2)

    for service in pending_services(internal):
        methods = {}
        for method in service.methods:
            request_type = message_factory.GetMessageClass(method.input_type)
            shape = ("stream" if method.client_streaming else "unary") + "_" + (
                "stream" if method.server_streaming else "unary")
            methods[method.name] = getattr(grpc, f"{shape}_rpc_method_handler")(
                unimplemented, request_deserializer=request_type.FromString,
                response_serializer=lambda response: response.SerializeToString(),
            )
        server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(service.full_name, methods),))
