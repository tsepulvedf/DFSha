"""Protected manual launcher: private bootstrap and restart after password change."""
from contextlib import contextmanager
import json
import os
import subprocess
import sys
import tomllib
import uuid

import grpc
import pytest

from dfsha.client.sdk import Client
from runtime import ROOT, wait_until


def test_private_bootstrap_and_resume_after_admin_password_change(run_dir):
    directory = run_dir/'private-launcher'
    initial, changed = 'initial-'+uuid.uuid4().hex, 'changed-'+uuid.uuid4().hex

    @contextmanager
    def running(password, resume=False):
        ready = directory/'ready-ha.json'
        ready.unlink(missing_ok=True)
        log = run_dir/('launcher-resume.log' if resume else 'launcher-new.log')
        command = [sys.executable, str(ROOT/'scripts/run_ha_lab.py'), '--directory', str(directory),
                   '--admin-password-stdin', '--resume' if resume else '--protected']
        with log.open('wb') as output:
            process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
            process.stdin.write((password+'\n').encode())
            process.stdin.close()
            try:
                def started():
                    assert process.poll() is None, 'Launcher exited before readiness; private log preserved'
                    return ready.exists()
                wait_until(started, seconds=180)
                config = tomllib.loads((directory/'client.toml').read_text(encoding='utf-8'))['client']
                yield Client(config['public_targets'], config['certificate_dir'])
            finally:
                if directory.exists():
                    (directory/'stop-ha').touch()
                try:
                    code = process.wait(timeout=90)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                    raise
                assert code == 0
        assert initial.encode() not in log.read_bytes() and changed.encode() not in log.read_bytes()

    with running(initial) as admin:
        try:
            with pytest.raises(grpc.RpcError) as failure:
                admin.login('admin', 'development-password')
            assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
            admin.login('admin', initial)
            identity = admin.session.user_id
            admin.mkdir('/home/admin/persistent')
            admin.change_password(identity, 1, changed)
            with pytest.raises(grpc.RpcError) as revoked:
                admin.stat('/home/admin/persistent')
            assert revoked.value.code() == grpc.StatusCode.UNAUTHENTICATED
        finally:
            admin.shutdown()
    assert initial not in (directory/'ha-lab.json').read_text(encoding='utf-8')
    with running(changed, resume=True) as admin:
        try:
            with pytest.raises(grpc.RpcError) as failure:
                admin.login('admin', initial)
            assert failure.value.code() == grpc.StatusCode.UNAUTHENTICATED
            admin.login('admin', changed)
            assert admin.session.user_id == identity
            assert admin.stat('/home/admin/persistent').object_id
            assert changed not in json.dumps(json.loads((directory/'ha-lab.json').read_text()))
        finally:
            admin.shutdown()
