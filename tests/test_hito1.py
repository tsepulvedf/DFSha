"""Comportamiento de RF1/RF2 sobre procesos distintos y TLS real."""
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import grpc
import pytest
from dfsha.client.sdk import Client
from dfsha.common.domain import CHUNK, PROFILES, Fault
from dfsha.common.rpc import channel, controlled_error
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl, data_pb2 as data, data_pb2_grpc as dg
from hito1_runtime import Hito1Process
from runtime import ROOT, PROCESS_FLAGS


@pytest.fixture
def h1(run_dir, certs):
    with Hito1Process(run_dir / ('h1-' + str(uuid4())), certs) as server:
        yield server


@pytest.fixture
def admin(h1):
    client = Client(h1.target, h1.certs)
    client.login('admin', 'development-password')
    yield client
    client.shutdown()


def error(reason, action):
    with pytest.raises(grpc.RpcError) as caught:
        action()
    assert controlled_error(caught.value)['reason'] == reason


def make_file(path, size):
    digest = hashlib.sha256()
    pattern = bytes(range(256)) * 1024
    with Path(path).open('wb') as stream:
        left = size
        while left:
            chunk = pattern[:min(CHUNK, left)]
            stream.write(chunk)
            digest.update(chunk)
            left -= len(chunk)
    return digest.hexdigest()


def test_rf1_paths_permissions_pagination_cwd(admin, h1):
    alice = admin.create_user('alice', 'alice-password')
    other = Client(h1.target, h1.certs)
    other.login('alice', 'alice-password')
    assert other.pwd() == admin.pwd() == '/'
    other.cd('/home/alice')
    assert admin.pwd() == '/'
    other.mkdir('café')
    assert other.stat('cafe\u0301').name == 'café'
    other.mkdir('b')
    page = other.ls_page('.', limit=1)
    assert len(page.entries) == 1 and page.next_cursor
    other.mkdir('a')
    error('LIST_CHANGED', lambda: other.ls_page('.', limit=1, cursor=page.next_cursor))
    assert [e.name for e in other.ls()] == ['a', 'b', 'café']
    error('PERMISSION_DENIED', lambda: other.mkdir('/forbidden'))
    error('PERMISSION_DENIED', lambda: other.stat('/home/admin'))
    error('DIRECTORY_NOT_EMPTY', lambda: admin.rmdir('/home/alice'))
    error('ROOT_PROTECTED', lambda: admin.rmdir('/'))
    error('IS_DIRECTORY', lambda: other.rm('a'))
    error('INVALID_ARGUMENT', lambda: other.mkdir('bad\\name'))
    other.cd('a')
    admin.rmdir('/home/alice/a')
    admin.mkdir('/home/alice/a')
    error('CWD_GONE', lambda: other.stat('.'))
    other.cd('/home/alice')
    other.rmdir('b')
    assert other.stat('.').object_id == admin.stat('/home/alice').object_id
    other.logout()
    other.shutdown()


@pytest.mark.parametrize('size', [0, 17, 4194303, 4194304, 4194305])
def test_binary_boundaries(admin, h1, size):
    source, destination = h1.directory / 'input.bin', h1.directory / 'output.bin'
    expected = make_file(source, size)
    result = admin.put(source, '/binary')
    assert result.snapshot.block_size_bytes == 4194304
    assert result.minimum_durable == result.target_replicas == 1
    assert admin.get('/binary', destination)['sha256'] == expected
    assert source.read_bytes() == destination.read_bytes()
    error('ALREADY_EXISTS', lambda: admin.send(source, '/binary'))
    error('NOT_DIRECTORY', lambda: admin.ls_page('/binary'))


def test_overwrite_snapshot_delete_idempotency(admin, h1):
    source = h1.directory / 'source'
    source.write_bytes(b'original\x00binary')
    first = admin.send(source, '/file')
    handle = admin.open_read('/file')
    source.write_bytes(b'replacement')
    second = admin.send(source, '/file', overwrite=True)
    assert first.snapshot.file_id == second.snapshot.file_id
    assert first.snapshot.manifest_root != second.snapshot.manifest_root
    request = ctl.CommitUploadRequest()
    request.CopyFrom(admin.last_commit_request)
    assert admin.call(admin.uploads.CommitUpload, request) == second
    request.seal.revision += 1
    from dfsha.common.domain import intent
    request.context.intent_sha256 = intent(request)
    error('IDEMPOTENCY_MISMATCH', lambda: admin.call(admin.uploads.CommitUpload, request))
    admin.rm('/file')
    admin.receive_handle(handle, h1.directory / 'snapshot')
    assert (h1.directory / 'snapshot').read_bytes() == b'original\x00binary'
    admin.close(handle)
    error('NOT_FOUND', lambda: admin.stat('/file'))
    admin.send(source, '/file')
    assert admin.stat('/file').object_id != first.snapshot.file_id


def test_corruption_block_auth_and_credentials(admin, h1):
    source = h1.directory / 'source'
    source.write_bytes(b'protected content')
    result = admin.send(source, '/file')
    handle = admin.open_read('/file')
    allocation = admin.call(admin.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
        snapshot=handle.snapshot, offset=0, length=handle.snapshot.size_bytes, page=c.PageRequest(limit=64))).blocks[0]
    request = admin.prepare(data.GetBlockRequest(handle_id=handle.handle_id, snapshot=handle.snapshot,
                                                block=allocation.block, capability=b'x' * 32))
    with channel(h1.target, h1.certs) as conn:
        error('PERMISSION_DENIED', lambda: list(dg.BlockServiceStub(conn).GetBlock(request, metadata=admin.metadata, timeout=30)))
    bad = Client(h1.target, h1.certs)
    error('UNAUTHENTICATED', lambda: bad.login('admin', 'wrong-password'))
    error('UNAUTHENTICATED', lambda: bad.login('missing', 'wrong-password'))
    bad.shutdown()
    block_path = h1.directory / 'blocks' / result.snapshot.file_id / (allocation.block.block_version_id + '.blk')
    payload = bytearray(block_path.read_bytes())
    assert b'protected content' not in payload
    payload[-1] ^= 1
    block_path.write_bytes(payload)
    target = h1.directory / 'existing'
    target.write_bytes(b'keep existing')
    error('DATA_LOSS', lambda: admin.receive_handle(handle, target, overwrite=True))
    assert target.read_bytes() == b'keep existing'
    assert not list(h1.directory.glob('.dfsha-*.part'))
    admin.close(handle)


def test_restart_profile_preservation_and_missing_key(admin, h1):
    source = h1.directory / 'source'
    expected = make_file(source, 4194305)
    admin.create_user('saved', 'saved-password')
    admin.mkdir('/tree')
    result = admin.send(source, '/tree/file')
    handle = admin.open_read('/tree/file')
    h1.stop()
    h1.block_size = 67108864
    h1.start()
    assert admin.stat('/tree/file').snapshot.block_size_bytes == 4194304
    assert admin.receive_handle(handle, h1.directory / 'restored')['sha256'] == expected
    admin.close(handle)
    assert admin.send(source, '/tree/file', overwrite=True).snapshot.block_size_bytes == 4194304
    assert admin.send(source, '/new').snapshot.block_size_bytes == 67108864
    h1.stop()
    key = h1.directory / 'secrets/master.key'
    original = key.read_bytes()
    key.unlink()
    with pytest.raises(RuntimeError, match='MASTER_KEY_MISSING_OR_INVALID'):
        h1.start()
    assert not key.exists()
    key.write_bytes(b'z' * 32)
    with pytest.raises(RuntimeError, match='MASTER_KEY_MISMATCH'):
        h1.start()
    key.write_bytes(original)
    h1.start()
    saved = Client(h1.target, h1.certs)
    saved.login('saved', 'saved-password')
    saved.shutdown()


def test_fault_recovery_and_lost_commit_response(admin, h1):
    source = h1.directory / 'source'
    source.write_bytes(b'old')
    admin.send(source, '/file')
    source.write_bytes(b'new')
    for point in ('after_block_persist', 'before_publish'):
        (h1.faults / point).touch()
        # Losing the control during CommitUpload is an unknown outcome, not
        # proof of abort. Recovery below still verifies the old durable version.
        expected = pytest.raises(Fault, match='OUTCOME_UNKNOWN') if point == 'before_publish' else pytest.raises(grpc.RpcError)
        with expected:
            admin.send(source, '/file', overwrite=True)
        assert h1.process.wait(timeout=10) == 93
        h1.stop()
        h1.start()
        output = h1.directory / (point + '.out')
        assert len(list((h1.directory / 'blocks').glob('*/*.blk'))) == 1
        assert not list((h1.directory / 'blocks').glob('*/*.staging'))
        admin.receive('/file', output)
        assert output.read_bytes() == b'old'
    (h1.faults / 'after_commit_drop_response').touch()
    result = admin.send(source, '/file', overwrite=True)
    assert result.snapshot.content_epoch == 2
    assert admin.stat('/file').snapshot == result.snapshot
    assert admin.call(admin.uploads.CommitUpload, admin.last_commit_request) == result


def test_interrupted_upload_space_and_future(admin, h1):
    source = h1.directory / 'source'
    source.write_bytes(b'abcdef')
    plan = admin.call(admin.uploads.BeginUpload, ctl.BeginUploadRequest(path=admin.path('/incomplete'),
        total_bytes=6, file_sha256=hashlib.sha256(b'abcdef').digest()))
    allocation = admin.call(admin.uploads.AllocateBlocks, ctl.AllocateBlocksRequest(operation=plan.operation,
        fence=plan.fence, blocks=[c.BlockRef(file_id=plan.file_id, size_bytes=6,
                                           plaintext_sha256=hashlib.sha256(b'abcdef').digest())])).blocks[0]
    header = admin.prepare(data.PutBlockHeader(operation=plan.operation, fence=plan.fence,
                                              block=allocation.block, capability=allocation.grants[0].capability))
    frames = [data.PutBlockFrame(header=header)]  # Client closes before delivering the promised content.
    with channel(h1.target, h1.certs) as conn:
        error('CHECKSUM_MISMATCH', lambda: dg.BlockServiceStub(conn).PutBlock(iter(frames), metadata=admin.metadata, timeout=30))
    error('NOT_FOUND', lambda: admin.stat('/incomplete'))
    admin.call(admin.uploads.AbortUpload, ctl.OperationRequest(operation=plan.operation))
    h1.stop()
    h1.capacity = 100
    h1.start()
    error('NO_SPACE', lambda: admin.send(source, '/too-big'))
    error('NOT_IMPLEMENTED_STAGE2', lambda: admin.call(admin.files.BeginWrite, ctl.BeginWriteRequest()))


@pytest.mark.parametrize('block_size', [67108864, 134217728])
def test_large_profiles_boundaries(run_dir, certs, block_size):
    with Hito1Process(run_dir / ('profile-' + str(block_size)), certs, block_size) as h1:
        client = Client(h1.target, certs)
        client.login('admin', 'development-password')
        for size in (block_size - 1, block_size, block_size + 1):
            source, target = h1.directory / 'source', h1.directory / 'target'
            expected = make_file(source, size)
            result = client.send(source, '/file', overwrite=True)
            assert result.snapshot.block_size_bytes == block_size
            assert client.receive('/file', target, overwrite=True)['sha256'] == expected
        client.shutdown()


def test_reservations_remove_no_resurrection_and_revocation(admin, h1):
    from dfsha.v1 import identity_pb2 as ident
    source = h1.directory / 'source'
    source.write_bytes(b'old')
    admin.send(source, '/file')
    begin = ctl.BeginUploadRequest(path=admin.path('/file'), overwrite=True, total_bytes=3,
        file_sha256=hashlib.sha256(b'new').digest(), expected_snapshot=admin.stat('/file').snapshot)
    plan = admin.call(admin.uploads.BeginUpload, begin)
    error('LOCK_BUSY', lambda: admin.send(source, '/file', overwrite=True))
    admin.rm('/file')
    new = admin.send(source, '/file')
    assert new.snapshot.file_id != plan.file_id
    error('OPERATION_EXPIRED', lambda: admin.call(admin.uploads.RenewUpload, ctl.OperationRequest(operation=plan.operation)))
    account = admin.create_user('reader', 'reader-password')
    admin.chmod('/file', 0o644)
    reader = Client(h1.target, h1.certs)
    reader.login('reader', 'reader-password')
    handle = reader.open_read('/file')
    admin.chmod('/file', 0o600)
    error('PERMISSION_DENIED', lambda: reader.receive_handle(handle, h1.directory / 'denied'))
    reader.close(handle)
    logout = reader.prepare(ident.SessionRequest(session_id=reader.session.session_id))
    reply = reader.call(reader.authentication.Logout, logout)
    assert reader.call(reader.authentication.Logout, logout) == reply
    error('UNAUTHENTICATED', lambda: reader.stat('/'))
    reader.shutdown()


def test_cli_process_and_interactive_shell(admin, h1):
    state = h1.directory / 'client/session.json'
    common = [sys.executable, '-m', 'dfsha.client.cli', '--config', str(h1.config), '--session-file', str(state)]
    login = subprocess.run(common + ['login', 'admin', '--password-stdin'], input='development-password\n',
        text=True, capture_output=True, creationflags=PROCESS_FLAGS, cwd=ROOT)
    assert login.returncode == 0, login.stderr
    assert 'token' not in login.stdout and 'password' not in login.stdout
    shell = subprocess.run(common + ['shell'], input='mkdir /cli\ncd /cli\npwd\nls\nexit\n', text=True,
                           capture_output=True, creationflags=PROCESS_FLAGS, cwd=ROOT)
    assert shell.returncode == 0, shell.stderr
    assert 'FALLIDO' not in shell.stdout and '/cli' in shell.stdout
    pwd = subprocess.run(common + ['pwd'], text=True, capture_output=True, creationflags=PROCESS_FLAGS, cwd=ROOT)
    assert pwd.returncode == 0 and '"/cli"' in pwd.stdout
    source = h1.directory / 'cli-source'
    source.write_text('Texto por CLI\n', encoding='utf-8')
    target = h1.directory / 'cli-target'
    for command in (['put', str(source), 'file'], ['get', 'file', str(target)]):
        result = subprocess.run(common + command, text=True, capture_output=True, creationflags=PROCESS_FLAGS, cwd=ROOT)
        assert result.returncode == 0, result.stderr
    assert source.read_bytes() == target.read_bytes()


def test_renewals_long_name_and_parallel_snapshot_readers(admin, h1):
    from concurrent.futures import ThreadPoolExecutor
    long_name = 'é' * 127
    admin.mkdir('/' + long_name)
    admin.mkdir('/z')
    page = admin.ls_page('/', limit=1)
    while page.next_cursor:
        assert len(page.next_cursor) <= 512
        page = admin.ls_page('/', limit=1, cursor=page.next_cursor)
    source = h1.directory / 'source'
    expected = make_file(source, 8388609)
    admin.send(source, '/shared')
    handle = admin.open_read('/shared')
    handle = admin.call(admin.files.RenewHandle, ctl.HandleRequest(handle_id=handle.handle_id,
                                                                 expected_handle_revision=handle.revision))
    clients = [Client(h1.target, h1.certs, session=admin.session) for _ in range(2)]
    try:
        with ThreadPoolExecutor(2) as pool:
            results = [pool.submit(client.receive_handle, handle, h1.directory / f'parallel-{i}')
                       for i, client in enumerate(clients)]
            source.write_bytes(b'replaced while two readers retain original')
            admin.send(source, '/shared', overwrite=True)
            assert all(result.result()['sha256'] == expected for result in results)
    finally:
        for client in clients:
            client.shutdown()
        admin.close(handle)
    from dfsha.common.domain import manifest_hash
    plan = admin.call(admin.uploads.BeginUpload, ctl.BeginUploadRequest(path=admin.path('/renewed'),
        total_bytes=0, file_sha256=hashlib.sha256(b'').digest()))
    plan = admin.call(admin.uploads.RenewUpload, ctl.OperationRequest(operation=plan.operation))
    seal = admin.call(admin.uploads.SealManifest, ctl.SealManifestRequest(operation=plan.operation,
        fence=plan.fence, manifest_sha256=manifest_hash([])), deadline=300)
    result = admin.call(admin.uploads.CommitUpload, ctl.CommitUploadRequest(operation=plan.operation, fence=plan.fence, seal=seal))
    assert result.accepted_bytes == 0
    from dfsha.v1.namespace_pb2 import PathRequest
    request = admin.prepare(PathRequest(path=admin.path('/')))
    error('INVALID_ARGUMENT', lambda: admin.namespace.Stat(request, metadata=admin.metadata, timeout=20))
