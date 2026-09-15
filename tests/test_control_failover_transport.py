"""Real TLS channels; bounded cancellation retries only for a read query."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import grpc
import pytest
from dfsha.common.failover import FailoverChannel
from dfsha.common.rpc import channel
from dfsha.v1 import nodes_pb2 as n, common_pb2 as c


@pytest.mark.parametrize('method,code,application,retried', [
    ('GetProtection', grpc.StatusCode.CANCELLED, False, True),
    ('GetProtection', grpc.StatusCode.PERMISSION_DENIED, False, False),
    ('GetProtection', grpc.StatusCode.CANCELLED, True, False),
    ('PromoteProtection', grpc.StatusCode.CANCELLED, False, False),
])
def test_cancelled_query_failover_is_scoped(certs, method, code, application, retried):
    calls = [0, 0]
    service = 'dfsha.v1.ClusterAdministrationService'
    expected = n.ProtectionStatus(state='DEGRADED', target_replicas=3, minimum_durable=2)
    with ExitStack() as cleanup:
        channels = []
        for index in range(2):
            def handler(request, context, index=index):
                calls[index] += 1
                if index == 0:
                    if application:
                        context.set_trailing_metadata((('dfsha-error-bin', c.ErrorDetail(reason=c.OPERATION_EXPIRED).SerializeToString()),))
                    context.abort(code, code.name)
                return expected
            server = grpc.server(ThreadPoolExecutor(max_workers=2))
            server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(service, {
                method: grpc.unary_unary_rpc_method_handler(handler,
                    request_deserializer=n.ProtectionRequest.FromString,
                    response_serializer=n.ProtectionStatus.SerializeToString)}),))
            credentials = grpc.ssl_server_credentials((((certs/'server.key').read_bytes(), (certs/'server.crt').read_bytes()),))
            port = server.add_secure_port('127.0.0.1:0', credentials)
            server.start()
            cleanup.callback(lambda server=server: server.stop(0).wait(5))
            channels.append(channel(f'localhost:{port}', certs))
        transport = cleanup.enter_context(FailoverChannel(channels))
        invoke = transport.unary_unary('/'+service+'/'+method,
            request_serializer=n.ProtectionRequest.SerializeToString,
            response_deserializer=n.ProtectionStatus.FromString)
        if retried:
            assert invoke(n.ProtectionRequest(operation_id='same-intent'), timeout=5) == expected
            assert calls == [1, 1]
        else:
            with pytest.raises(grpc.RpcError) as error:
                invoke(n.ProtectionRequest(operation_id='same-intent'), timeout=5)
            assert error.value.code() == code
            assert calls == [1, 0]
