"""Canal con endpoints explícitos y presupuesto total; nunca cambia la solicitud."""
import threading
import time
import grpc


class FailoverChannel:
    def __init__(self, channels):
        if not channels:
            raise ValueError('Se requiere al menos un endpoint')
        self.channels = channels
        self.index = 0
        self.guard = threading.Lock()
        self.closed = False
        self.sent_bytes = self.received_bytes = 0

    def unary_unary(self, method, **options):
        calls = [c.unary_unary(method, **options) for c in self.channels]

        def invoke(request, timeout=None, **kwargs):
            deadline = time.monotonic() + (timeout or 5)
            with self.guard:
                start = self.index
            error = None
            for attempt in range(len(calls)):
                index = (start + attempt) % len(calls)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                # Leave time for alternatives without cutting every healthy call
                # to one third of its contract deadline.
                budget = min(remaining, max(1, (timeout or 5)*.7)) if attempt < len(calls)-1 else remaining
                try:
                    with self.guard:
                        self.sent_bytes += request.ByteSize()
                    response = calls[index](request, timeout=budget, **kwargs)
                    with self.guard:
                        self.index = index
                        self.received_bytes += response.ByteSize()
                    return response
                except grpc.RpcError as exc:
                    # A server shutdown can cancel an in-flight read. Retry only
                    # this side-effect-free query, never an arbitrary mutation,
                    # application cancellation, or caller-initiated channel close.
                    cancelled_read = (exc.code() == grpc.StatusCode.CANCELLED and
                        method == '/dfsha.v1.ClusterAdministrationService/GetProtection' and
                        not self.closed and not any(k == 'dfsha-error-bin' for k, _ in (exc.trailing_metadata() or ())))
                    if exc.code() not in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED) and not cancelled_read:
                        raise
                    error = exc
            if error:
                raise error
            raise RuntimeError('Presupuesto de comunicación agotado')
        return invoke

    def unary_stream(self, method, **options):
        def invoke(request, **kwargs):
            return self.channels[self.index].unary_stream(method, **options)(request, **kwargs)
        return invoke

    def stream_stream(self, method, **options):
        def invoke(request, **kwargs):
            return self.channels[self.index].stream_stream(method, **options)(request, **kwargs)
        return invoke

    def stream_unary(self, method, **options):
        def invoke(request, **kwargs):
            return self.channels[self.index].stream_unary(method, **options)(request, **kwargs)
        return invoke

    def close(self):
        with self.guard:
            self.closed = True
        for channel in self.channels:
            channel.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
