"""Encrypted local CLI state; external key, bounded input and atomic publication."""
import json
import os
from pathlib import Path
import tempfile

from dfsha.common.domain import need
from dfsha.common.protected import MetadataCipher
from dfsha.control.auth import protect

MAX_STATE = 4*1048576
CONTEXT = b'dfsha-client-state-v1'


def initialize_key(path, state):
    path, state = Path(path).resolve(), Path(state).resolve()
    need(not path.is_relative_to(state.parent), 'INVALID_ARGUMENT')
    if path.exists():
        need(path.is_file() and len(path.read_bytes()) == 32, 'DATA_LOSS')
        return  # Explicit idempotence, never regenerate a missing key for a cache.
    need(not state.exists(), 'ALREADY_EXISTS')
    path.parent.mkdir(parents=True, exist_ok=True)
    protect(path.parent)
    with path.open('xb') as out:
        out.write(os.urandom(32))
        out.flush()
        os.fsync(out.fileno())
    protect(path)


def cipher(key_file, required):
    need(not required or key_file is not None, 'PERMISSION_DENIED')
    if key_file is None:
        return None
    return MetadataCipher.configured({'metadata_key_path': str(key_file)})


def load(path, key_file=None, required=False):
    codec = cipher(key_file, required)
    path = Path(path)
    if not path.exists():
        return {}
    need(path.stat().st_size <= MAX_STATE, 'LIMIT_EXCEEDED')
    raw = path.read_bytes()
    if codec:
        raw = codec.open(raw, CONTEXT)
    return json.loads(raw)


def save(path, state, key_file=None, required=False):
    codec = cipher(key_file, required)
    raw = json.dumps(state, ensure_ascii=False).encode('utf-8')
    if codec:
        raw = codec.seal(raw, CONTEXT)
    need(len(raw) <= MAX_STATE, 'LIMIT_EXCEEDED')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    protect(path.parent)
    descriptor, temporary = tempfile.mkstemp(prefix='.session-', dir=path.parent)
    try:
        with os.fdopen(descriptor, 'wb') as out:
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
        protect(path)
    finally:
        Path(temporary).unlink(missing_ok=True)
