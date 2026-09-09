"""Coordinación y admisión locales sustituibles; no simulan un clúster."""
from contextlib import contextmanager
import threading
import time
from dfsha.common.domain import Fault, PROFILES


class LocalCoordinator:
    def __init__(self):
        self.lock = threading.RLock()
        self.condition = threading.Condition()
        self.units = 4

    @contextmanager
    def admit(self, block_size, seconds=5):
        weight = (1, 2, 4)[PROFILES.index(block_size)]
        until = time.monotonic() + seconds
        with self.condition:
            while self.units < weight:
                left = until - time.monotonic()
                if left <= 0:
                    raise Fault('SERVICE_UNAVAILABLE')
                self.condition.wait(left)
            self.units -= weight
        try:
            yield
        finally:
            with self.condition:
                self.units += weight
                self.condition.notify_all()


class LocalPlacement:
    def __init__(self, node_id):
        self.node_id = node_id
        self.endpoint = ''

    def location(self):
        from dfsha.v1.common_pb2 import BlockLocation
        return BlockLocation(node_id=self.node_id, boot_generation=1,
            client_endpoint=self.endpoint, failure_domain='local-host')
