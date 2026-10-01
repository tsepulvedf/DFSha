"""Finite authentication work and secret-free bounded audit, with observed costs."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
import threading
import time

import pytest

from dfsha.common.domain import Fault
from dfsha.control.auth import PASSWORDS, auth_slot, password_hash, matches
from dfsha.common import telemetry
from measure_hito1 import memory


def test_argon2_bounded_concurrency_and_effective_parameters(record_property):
    barrier = threading.Barrier(3)
    release = threading.Event()
    def hold():
        with auth_slot():
            barrier.wait(timeout=5)
            assert release.wait(5)
    with ThreadPoolExecutor(2) as pool:
        held = [pool.submit(hold) for _ in range(2)]
        barrier.wait(timeout=5)
        try:
            with pytest.raises(Fault, match='LIMIT_EXCEEDED'):
                password_hash('bounded-password')
        finally:
            release.set()
        for result in held:
            result.result()
        start = time.perf_counter()
        hashes = list(pool.map(password_hash, ['bounded-password']*2))
        elapsed = time.perf_counter()-start
    assert PASSWORDS.memory_cost == 19456 and PASSWORDS.time_cost == 2 and PASSWORDS.parallelism == 1
    assert all(value.startswith('$argon2id$v=19$m=19456,t=2,p=1$') for value in hashes)
    assert matches(hashes[0], 'bounded-password') and not matches(hashes[0], 'incorrect-password')
    record_property('argon2_cost', json.dumps(dict(simultaneous=2, seconds=elapsed,
        memory=memory(os.getpid()), memory_kib_per_hash=19456, time_cost=2, parallelism=1)))


def test_audit_rejects_secrets_and_rotates(tmp_path):
    logger = telemetry.LOGGER
    previous, level, propagate = list(logger.handlers), logger.level, logger.propagate
    logger.handlers = []
    try:
        telemetry.configure(tmp_path/'audit/events.jsonl')
        handler = logger.handlers[0]
        assert handler.maxBytes == 5*1048576 and handler.backupCount == 3
        handler.maxBytes = 240  # Exercise the same rotation handler with a small isolated limit.
        with pytest.raises(ValueError, match='Campo de log'):
            telemetry.event('audit', password='must-not-be-logged')
        for _ in range(30):
            telemetry.event('audit', actor='user-id', action='Read', resource='file-id', code='OK')
        handler.flush()
        files = list((tmp_path/'audit').iterdir())
        assert len(files) == 4
        assert all(b'must-not-be-logged' not in p.read_bytes() for p in files)
    finally:
        for handler in logger.handlers:
            handler.close()
        logger.handlers, logger.level, logger.propagate = previous, level, propagate
