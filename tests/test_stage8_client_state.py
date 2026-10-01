import json
import os
import subprocess
import sys

import pytest

from dfsha.client import state
from dfsha.common.domain import Fault
from ha_runtime import HACluster
from runtime import PROCESS_FLAGS, ROOT


def test_session_cache_requires_external_key_and_rejects_tampering(tmp_path):
    path, key = tmp_path/'cache/session', tmp_path/'secrets/cache.key'
    state.initialize_key(key, path)
    original = key.read_bytes()
    state.initialize_key(key, path)
    assert key.read_bytes() == original
    value = {'session': {'token': 'sensitive-test-token'}, 'cwd': '/private-name'}
    state.save(path, value, key, True)
    assert state.load(path, key, True) == value
    assert b'sensitive-test-token' not in path.read_bytes()
    with pytest.raises(Fault, match='PERMISSION_DENIED'):
        state.load(path, required=True)
    wrong = tmp_path/'wrong.key'
    wrong.write_bytes(os.urandom(32))
    with pytest.raises(Fault, match='DATA_LOSS'):
        state.load(path, wrong, True)
    raw = bytearray(path.read_bytes())
    raw[-1] ^= 1
    path.write_bytes(raw)
    with pytest.raises(Fault, match='DATA_LOSS'):
        state.load(path, key, True)
    key.unlink()
    with pytest.raises(Fault, match='ALREADY_EXISTS'):
        state.initialize_key(key, path)
    assert not key.exists()


def test_ordinary_cli_ha_uses_encrypted_session_and_logout(run_dir):
    with HACluster(run_dir/'cli-cache-e8', protected=True) as lab:
        admin = lab.client()
        admin.create_user('cliuser', 'cliuser-password')
        admin.shutdown()
        cache, key = run_dir/'cli-cache/session', run_dir/'client-secrets/session.key'
        base = [sys.executable, '-m', 'dfsha.client.cli', '--config', str(lab.directory/'client.toml'),
                '--session-file', str(cache), '--session-key-file', str(key)]
        def call(args, input=None):
            return subprocess.run(base+args, cwd=ROOT, input=input, capture_output=True, text=True,
                encoding='utf-8', timeout=45, creationflags=PROCESS_FLAGS)
        assert call(['init-session-key']).returncode == 0
        login = call(['login', 'cliuser', '--password-stdin'], 'cliuser-password\n')
        assert login.returncode == 0, login.stderr
        saved = state.load(cache, key, True)
        assert saved['session']['user_id']
        assert b'cliuser-password' not in cache.read_bytes()
        assert call(['mkdir', '/home/cliuser/created']).returncode == 0
        assert call(['stat', '/home/cliuser/created']).returncode == 0
        assert call(['logout']).returncode == 0
        assert not cache.exists()
