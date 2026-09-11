"""RF3 contra cuatro procesos reales. Ningún mock acredita transporte o concurrencia."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading
import uuid
import pytest
import grpc
from runtime import wait_until
from dfsha.client.sdk import Client
from hito2_runtime import Cluster
from dfsha.common.domain import Fault
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl


@pytest.fixture
def cluster(run_dir):
    lab = Cluster(run_dir / ('rf3-' + str(uuid.uuid4())), rf3=True)
    lab.start()
    try:
        yield lab
    finally:
        lab.stop()


def rejected(action, reason):
    with pytest.raises((grpc.RpcError, Fault)) as failure:
        action()
    assert reason in str(failure.value)


def test_modes_ranges_and_atomic_patch(cluster, tmp_path):
    client = cluster.client()
    try:
        rejected(lambda: client.open('/missing'), 'NOT_FOUND')
        rejected(lambda: client.open('/missing', 'r+'), 'NOT_FOUND')
        rejected(lambda: client.open('/file', 'a'), 'UNSUPPORTED_MODE')
        h = client.open('/file', 'x+')
        assert client.read(h, 0, 0) == b''
        assert client.read(h, 500, 2) == b''
        rejected(lambda: client.open('/file', 'x'), 'ALREADY_EXISTS')
        assert client.write(h, 0, b'hello') == 5
        assert client.read(h, 0, 50) == b'hello'
        old = client.open('/file')
        assert client.write(h, 2, b'XY') == 2
        assert client.read(h, 0, 10) == b'heXYo'
        assert client.read(old, 0, 10) == b'hello'
        rejected(lambda: client.write(h, 6, b'bad'), 'SPARSE_WRITE_UNSUPPORTED')
        rejected(lambda: client.write(h, -1, b'bad'), 'INVALID_ARGUMENT')
        rejected(lambda: client.write(h, 0, b'z' * (16*1024*1024+1)), 'LIMIT_EXCEEDED')
        version = h.snapshot.file_version
        assert client.write(h, 1, b'') == 0 and h.snapshot.file_version == version
        write_only = client.open('/file', 'w')
        rejected(lambda: client.read(write_only, 0, 1), 'PERMISSION_DENIED')
        rejected(lambda: client.write(h, 0, b'z'), 'VERSION_CONFLICT')
        assert client.read(old, 0, 10) == b'hello'
        assert client.write(write_only, 0, b'secret') == 6
        destination = tmp_path / 'received'
        client.receive('/file', destination)
        assert destination.read_bytes() == b'secret'
        exclusive = client.open('/only-x', 'x')
        assert client.write(exclusive, 0, b'x') == 1
        client.close(exclusive)
        truncating = client.open('/only-x', 'w+')
        assert client.read(truncating, 0, 5) == b''
        plan = client.begin_write(truncating, 0, b'new')
        client.renew_lock(plan.fences[0])
        changes = client.prepare_blocks(truncating, plan, b'new')
        client.commit_write(truncating, plan, changes)
        assert client.read(truncating, 0, 5) == b'new'
        client.close(truncating)
        for handle in (h, old, write_only):
            client.close(handle)
            client.close(handle)
    finally:
        client.shutdown()


def test_parallel_disjoint_merge_and_conflict(cluster, tmp_path, record_property):
    client = cluster.client()
    other = cluster.client()
    size = 4194304
    source = tmp_path / 'source'
    source.write_bytes(b'A' * size + b'B' * size)
    try:
        client.send(source, '/parallel')
        a, b, reader = client.open('/parallel', 'r+'), other.open('/parallel', 'r+'), client.open('/parallel')
        barrier = threading.Barrier(2)
        ready = threading.Barrier(2)
        def prepare(sdk, handle, offset, delta):
            plan = sdk.begin_write(handle, offset, delta)
            barrier.wait(15)
            changes = sdk.prepare_blocks(handle, plan, delta)
            ready.wait(15)
            return plan, changes
        with ThreadPoolExecutor(2) as pool:
            fa = pool.submit(prepare, client, a, 0, b'a' * 4096)
            fb = pool.submit(prepare, other, b, size, b'b' * 4096)
            pa, ca = fa.result(timeout=30)
            pb, cb = fb.result(timeout=30)
        rejected(lambda: client.close(a), 'HANDLE_BUSY')
        client.commit_write(a, pa, ca)
        other.commit_write(b, pb, cb)
        assert client.read(reader, 0, 1) == b'A'
        assert client.read(a, size, 1) == b'B'
        assert other.read(b, 0, 1) == b'a'
        fresh = client.open('/parallel', 'r+')
        assert client.read(fresh, 0, 4096) == b'a' * 4096
        assert client.read(fresh, size, 4096) == b'b' * 4096
        lock = client.lock(fresh, 0, 1)
        rejected(lambda: other.lock(b, 2, 1), 'LOCK_CONFLICT')
        client.unlock(lock)
        block_b = other.lock(b, size, 1)
        rejected(lambda: client.begin_write(fresh, size-1, b'xy'), 'LOCK_CONFLICT')
        block_a = client.lock(fresh, 0, 1)  # Failed multi-block acquisition left no partial ownership.
        rejected(lambda: other.lock(b, whole_file=True), 'LOCK_CONFLICT')
        rejected(lambda: other.unlock(block_a), 'PERMISSION_DENIED')
        client.unlock(block_a)
        other.unlock(block_b)
        # An old handle cannot overwrite a newer version even after it acquires a new lock.
        stale_lock = client.lock(a, size, 1)
        rejected(lambda: client.begin_write(a, size, b'z', fences=[stale_lock]), 'VERSION_CONFLICT')
        client.unlock(stale_lock)
        record_property('parallel_preparation', 'two barriers; both durable preparations before either commit; [A1,B1]')
        record_property('delta_bytes', 8192)
        record_property('control_content_bytes', 0)
        for handle, sdk in ((a, client), (b, other), (reader, client), (fresh, client)):
            sdk.close(handle)
    finally:
        client.shutdown()
        other.shutdown()


def test_multiblock_atomic_abort_and_idempotency(cluster, tmp_path):
    client = cluster.client()
    size = 4194304
    source = tmp_path / 'source'
    source.write_bytes(b'A' * size + b'B' * size)
    try:
        client.send(source, '/cross')
        h = client.open('/cross', 'r+')
        plan = client.begin_write(h, size-2, b'1234')
        changes = client.prepare_blocks(h, plan, b'1234')
        client.call(client.files.AbortWrite, ctl.OperationRequest(operation=plan.operation))
        rejected(lambda: client.commit_write(h, plan, changes), 'OPERATION_EXPIRED')
        assert client.read(h, size-2, 4) == b'AABB'
        identity = str(uuid.uuid4())
        (cluster.faults / 'after_commit_drop_response').touch()
        assert client.write(h, size-2, b'1234', request_id=identity) == 4
        version = h.snapshot.file_version
        assert client.write(h, size-2, b'1234', request_id=identity) == 4
        assert h.snapshot.file_version == version
        rejected(lambda: client.write(h, size-2, b'5678', request_id=identity), 'IDEMPOTENCY_MISMATCH')
        assert client.read(h, size-2, 4) == b'1234'
        client.close(h)
    finally:
        client.shutdown()


def test_fencing_successor_restart_and_persistent_result(run_dir, tmp_path):
    lab = Cluster(run_dir / ('leases-' + str(uuid.uuid4())), rf3=True, lease_seconds=4)
    with lab:
        a, b = lab.client(), lab.client()
        try:
            h = a.open('/fence', 'x+')
            a.write(h, 0, b'base')
            old = a.open('/fence', 'r+')
            successor = b.open('/fence', 'r+')
            plan = a.begin_write(old, 0, b'old!')
            prepared = a.prepare_blocks(old, plan, b'old!')
            # Server waits for the authoritative monotonic lease to expire; no fixed demo sleep.
            fence = b.lock(successor, 0, 1, wait_ms=5000)
            b.write(successor, 0, b'new!', fences=[fence])
            rejected(lambda: a.commit_write(old, plan, prepared), 'OPERATION_EXPIRED')
            rejected(lambda: a.unlock(plan.fences[0]), 'LOCK_EXPIRED')
            rejected(lambda: a.renew_lock(plan.fences[0]), 'LOCK_EXPIRED')
            assert b.read(successor, 0, 4) == b'new!'
            b.unlock(fence)
            identity = str(uuid.uuid4())
            assert b.write(successor, 1, b'E', request_id=identity) == 1
            committed = b.operation(request_id=identity)
            lab.control.stop()
            lab.control.start()
            lab.wait_ready(3, b)
            rejected(lambda: b.read(successor, 0, 4), 'STALE_HANDLE')
            assert b.operation(request_id=identity).result == committed.result
            assert b.write(successor, 1, b'E', request_id=identity) == 1
            reopened = b.open('/fence')
            assert b.read(reopened, 0, 4) == b'nEw!'
            b.close(reopened)
        finally:
            a.shutdown()
            b.shutdown()


def test_growth_read_serialization_tombstone_and_permissions(cluster, tmp_path):
    admin, other = cluster.client(), cluster.client()
    try:
        size = 4194304
        source = tmp_path / 'base'
        source.write_bytes(b'A' * size + b'B' * size)
        admin.send(source, '/growth')
        a, b = admin.open('/growth', 'r+'), other.open('/growth', 'r+')
        extension = admin.begin_write(a, 2*size, b'end')
        delta = other.begin_write(b, 0, b'first')
        da, db = admin.prepare_blocks(a, extension, b'end'), other.prepare_blocks(b, delta, b'first')
        admin.commit_write(a, extension, da)
        other.commit_write(b, delta, db)
        assert b.snapshot.size_bytes == 2*size+3
        assert other.read(b, 2*size, 3) == b'end'
        stale_size = admin.open('/growth', 'r+')
        fresh = other.open('/growth', 'r+')
        other.write(fresh, fresh.snapshot.size_bytes, b'more')
        rejected(lambda: admin.write(stale_size, stale_size.snapshot.size_bytes, b'bad'), 'VERSION_CONFLICT')
        iterator = other.iter_read(fresh, 0, 4194304)
        assert next(iterator)
        rejected(lambda: other.close(fresh), 'HANDLE_BUSY')
        rejected(lambda: other.begin_write(fresh, 0, b'x'), 'HANDLE_BUSY')
        iterator.close()
        prepared = other.begin_write(fresh, 0, b'gone')
        changes = other.prepare_blocks(fresh, prepared, b'gone')
        reader = admin.open('/growth')
        admin.rm('/growth')
        replacement = admin.open('/growth', 'x+')
        assert replacement.snapshot.file_id != reader.snapshot.file_id
        rejected(lambda: other.commit_write(fresh, prepared, changes), 'OPERATION_EXPIRED')
        assert admin.read(reader, 0, 5) == b'first'
        admin.create_user('alice', 'alice-password')
        alice = Client(cluster.target, cluster.certs)
        alice.login('alice', 'alice-password')
        try:
            owned = alice.open('/home/alice/private', 'x+')
            alice.write(owned, 0, b'secret')
            admin.chmod('/home/alice/private', 0o200)
            rejected(lambda: alice.open('/home/alice/private', 'r+'), 'PERMISSION_DENIED')
            only_write = alice.open('/home/alice/private', 'w')
            assert alice.write(only_write, 0, b'private') == 7
            rejected(lambda: alice.read(only_write, 0, 1), 'PERMISSION_DENIED')
            pending = alice.begin_write(only_write, 0, b'X')
            received = alice.prepare_blocks(only_write, pending, b'X')
            admin.chmod('/home/alice/private', 0)
            rejected(lambda: alice.commit_write(only_write, pending, received), 'PERMISSION_DENIED')
            alice.call(alice.files.AbortWrite, ctl.OperationRequest(operation=pending.operation))
        finally:
            alice.shutdown()
    finally:
        admin.shutdown()
        other.shutdown()


@pytest.mark.parametrize('size', [4194304, 67108864, 134217728])
def test_profile_boundary_small_delta(run_dir, size, record_property):
    from test_hito1 import make_file
    lab = Cluster(run_dir / ('profile-rf3-' + str(uuid.uuid4())), rf3=True, block_size=size)
    with lab:
        client = lab.client()
        try:
            source = lab.directory / 'source'
            make_file(source, size + 1)
            with source.open('rb') as stream:
                stream.seek(size - 2)
                old_bytes = stream.read(3)
            client.send(source, '/boundary')
            handle, reader = client.open('/boundary', 'r+'), client.open('/boundary')
            traffic = sum(x['client_write_bytes'] for x in client.traffic.values())
            assert client.write(handle, size-2, b'123456') == 6
            assert handle.snapshot.size_bytes == size+4
            assert client.read(handle, size-3, 7)[1:] == b'123456'
            assert client.read(reader, size-2, 3) == old_bytes
            assert sum(x['client_write_bytes'] for x in client.traffic.values()) - traffic == 6
            record_property('block_size_bytes', size)
            record_property('delta_client_write_bytes', 6)
            client.close(handle)
            client.close(reader)
        finally:
            client.shutdown()


def test_remote_base_copy_capacity_and_partial_authorization(run_dir, record_property):
    from dfsha.control.metadata import SQLiteMetadataStore
    from dfsha.common.domain import asdict
    from dfsha.common.rpc import channel
    from dfsha.v1 import data_pb2 as d, data_pb2_grpc as dg
    import tomllib
    lab = Cluster(run_dir / ('remote-base-' + str(uuid.uuid4())), rf3=True,
                  capacities=[6*1024*1024, 32*1024*1024, 32*1024*1024, 32*1024*1024])
    # Seed only round-robin tie-breaker; registration, quotas, storage and S/S are real.
    cfg = tomllib.loads(lab.control.config.read_text(encoding='utf-8'))['server']
    ordered = sorted(lab.node_ids[:3])
    source_id = lab.node_ids[0]
    previous_id = ordered[ordered.index(source_id)-1]
    with SQLiteMetadataStore(cfg['sqlite_path']).transaction(True) as tx:
        tx.put('settings', dict(id='placement', last=previous_id))
    with lab:
        client = lab.client()
        try:
            source = lab.directory / 'source'
            source.write_bytes(b'A' * 4194304)
            client.send(source, '/remote')
            h = client.open('/remote', 'r+')
            before = client.call(client.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=h.handle_id,
                snapshot=h.snapshot, offset=0, length=4194304, page=c.PageRequest(limit=1)))
            assert before.blocks[0].locations[0].node_id == source_id
            plan = client.begin_write(h, 20, b'patch')
            target = plan.blocks[0].locations[0]
            assert target.node_id != source_id
            changes = client.prepare_blocks(h, plan, b'patch')
            client.commit_write(h, plan, changes)
            lab.nodes[0].stop()
            assert client.read(h, 15, 15) == b'AAAAApatchAAAAA'
            # Partial permission cannot be stretched into a whole-block download.
            resolved = client.call(client.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=h.handle_id,
                snapshot=h.snapshot, offset=20, length=5, page=c.PageRequest(limit=1)))
            p = resolved.blocks[0]
            request = client.prepare(d.GetBlockRequest(handle_id=h.handle_id, snapshot=h.snapshot, block=p.block,
                offset=0, length=p.block.size_bytes, capability=p.grants[0].capability))
            with channel(p.locations[0].client_endpoint, client.cert_dir) as transport:
                rejected(lambda: list(dg.BlockServiceStub(transport).GetBlock(request, metadata=client.metadata, timeout=30)), 'PERMISSION_DENIED')
            cfg = tomllib.loads(lab.nodes[lab.node_ids.index(target.node_id)].config.read_text(encoding='utf-8'))['datanode']
            with SQLiteMetadataStore(cfg['sqlite_path']).transaction() as tx:
                traffic = tx.get('settings', 'traffic')
            assert traffic['replica_write_bytes'] > 4194304
            assert traffic['client_write_bytes'] == 5
            record_property('remote_base', 'source stopped; destination serves patched object')
            record_property('replica_ciphertext_bytes', traffic['replica_write_bytes'])
            record_property('client_delta_bytes', 5)
            client.close(h)
        finally:
            client.shutdown()


def test_patch_failures_and_restart_before_publication(cluster):
    from dfsha.common.rpc import channel
    from dfsha.v1 import data_pb2 as d, data_pb2_grpc as dg
    client = cluster.client()
    try:
        h = client.open('/faults', 'x+')
        client.write(h, 0, b'original-data')
        interrupted = client.begin_write(h, 0, b'XY')
        part = interrupted.blocks[0]
        header = client.prepare(d.PatchBlockHeader(operation=interrupted.operation, base=part.block,
            new_block_version_id=part.replacement_block_version_id, block_offset=0, delta_length=2,
            delta_sha256=hashlib.sha256(b'XY').digest(), fence=interrupted.fences[0], capability=part.grants[0].capability))
        with channel(part.locations[0].client_endpoint, client.cert_dir) as transport:
            frames = [d.PatchBlockFrame(header=header), d.PatchBlockFrame(chunk=d.DataChunk(offset=0, data=b'X'))]
            rejected(lambda: dg.BlockServiceStub(transport).PatchBlock(iter(frames), metadata=client.metadata, timeout=30), 'CHECKSUM_MISMATCH')
        client.call(client.files.AbortWrite, ctl.OperationRequest(operation=interrupted.operation))
        with channel(part.locations[0].client_endpoint, client.cert_dir) as transport:
            rejected(lambda: dg.BlockServiceStub(transport).PatchBlock(iter(frames), metadata=client.metadata, timeout=30), 'OPERATION_EXPIRED')
        assert client.read(h, 0, 13) == b'original-data'
        rejected(lambda: client.begin_write(h, (1 << 63)-1, b'xx'), 'INVALID_ARGUMENT')
        rejected(lambda: client.read(h, -1, 1), 'INVALID_ARGUMENT')
        rejected(lambda: client.lock(h, 0, 0), 'INVALID_ARGUMENT')
        other = client.open('/faults', 'r+')
        plan = client.begin_write(h, 0, b'X')
        rejected(lambda: client.begin_write(other, 1, b'Y'), 'LOCK_CONFLICT')
        node_index = cluster.node_ids.index(plan.blocks[0].locations[0].node_id)
        (cluster.nodes[node_index].directory / 'faults/no_space').touch()
        rejected(lambda: client.prepare_blocks(h, plan, b'X'), 'NO_SPACE')
        client.call(client.files.AbortWrite, ctl.OperationRequest(operation=plan.operation))
        assert client.read(h, 0, 13) == b'original-data'
        plan = client.begin_write(h, 0, b'Z')
        changes = client.prepare_blocks(h, plan, b'Z')
        rejected(lambda: client.unlock(plan.fences[0]), 'LOCK_BUSY')
        (cluster.faults / 'before_publish').touch()
        rejected(lambda: client.commit_write(h, plan, changes), 'OUTCOME_UNKNOWN')
        cluster.control.stop()
        cluster.control.start()
        cluster.wait_ready(3, client)
        assert client.operation(plan.operation.operation_id).state == c.ABORTED
        fresh = client.open('/faults', 'r+')
        assert client.read(fresh, 0, 13) == b'original-data'
        resolved = client.call(client.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=fresh.handle_id,
            snapshot=fresh.snapshot, offset=0, length=13, page=c.PageRequest(limit=1))).blocks[0]
        request = client.prepare(d.GetBlockRequest(handle_id=fresh.handle_id, snapshot=fresh.snapshot,
            block=resolved.block, offset=0, length=13))  # Missing capability.
        with channel(resolved.locations[0].client_endpoint, client.cert_dir) as transport:
            rejected(lambda: list(dg.BlockServiceStub(transport).GetBlock(request, metadata=client.metadata, timeout=30)), 'PERMISSION_DENIED')
        node = cluster.nodes[cluster.node_ids.index(resolved.locations[0].node_id)]
        physical = node.directory / 'blocks' / resolved.block.file_id / (resolved.block.block_version_id + '.blk')
        with physical.open('r+b') as stream:
            stream.seek(-1, 2)
            value = stream.read(1)
            stream.seek(-1, 2)
            stream.write(bytes([value[0] ^ 1]))
        rejected(lambda: client.read(fresh, 0, 1), 'DATA_LOSS')
        corrupt = client.begin_write(fresh, 0, b'A')
        rejected(lambda: client.prepare_blocks(fresh, corrupt, b'A'), 'DATA_LOSS')
        client.call(client.files.AbortWrite, ctl.OperationRequest(operation=corrupt.operation))
        node.stop()
        wait_until(lambda: any(x.node.node_id == resolved.locations[0].node_id and x.state == 'UNAVAILABLE'
                              for x in cluster.statuses(client).nodes), seconds=15)
        rejected(lambda: client.begin_write(fresh, 0, b'B'), 'DATA_UNAVAILABLE')
        client.close(fresh)
    finally:
        client.shutdown()


def test_full_locks_overwrite_and_cli(cluster):
    import json
    import subprocess
    import sys
    from runtime import ROOT, PROCESS_FLAGS
    client = cluster.client()
    try:
        h = client.open('/exclusive', 'x+')
        assert client.write(h, 0, b'X' * (16*1024*1024)) == 16*1024*1024
        lock = client.lock(h, whole_file=True)
        rejected(lambda: client.open('/exclusive', 'w'), 'LOCK_CONFLICT')
        source = cluster.directory / 'delta.txt'
        source.write_bytes(b'replacement')
        rejected(lambda: client.send(source, '/exclusive', overwrite=True), 'LOCK_CONFLICT')
        reader = client.open('/exclusive')
        client.unlock(lock)
        client.send(source, '/exclusive', overwrite=True)
        rejected(lambda: client.write(h, 0, b'x'), 'VERSION_CONFLICT')
        assert client.read(reader, 16*1024*1024-1, 1) == b'X'
        state = cluster.directory / 'cli/session.json'
        command = [sys.executable, '-m', 'dfsha.client.cli', '--config', str(cluster.directory / 'client.toml'),
                   '--session-file', str(state)]
        def run(args, stdin=None):
            result = subprocess.run(command + args, input=stdin, capture_output=True, text=True,
                creationflags=PROCESS_FLAGS, cwd=ROOT, timeout=45)
            assert result.returncode == 0, result.stderr + result.stdout
            return result.stdout
        run(['login', 'admin', '--password-stdin'], 'development-password\n')
        run(['open', '/cli-rf3', 'x+', 'h'])
        written = json.loads(run(['write', 'h', '0', str(source)]))
        assert written['written'] == 11
        status = json.loads(run(['operation', written['operation_id']]))
        assert status['state'] == 'COMMITTED'
        output = cluster.directory / 'cli-read'
        run(['read', 'h', '0', '11', str(output)])
        assert output.read_bytes() == b'replacement'
        run(['lock', 'h', 'l', '--offset', '0', '--length', '1'])
        run(['renew-lock', 'l'])
        run(['unlock', 'l'])
        run(['close', 'h'])
        result = run(['shell'], 'open /cli-rf3 r h\nclose h\nexit\n')
        assert 'FALLIDO' not in result
        client.close(reader)
        client.close(h)
    finally:
        client.shutdown()


def test_monotonic_gc_and_reservation_ignore_wall_hints(run_dir):
    """Prueba aislada de autoridad/SQLite, no se presenta como prueba de distribución."""
    import tomllib
    from dfsha.control.distributed import DistributedControl
    from dfsha.common.domain import asdict
    lab = Cluster(run_dir / ('clock-' + str(uuid.uuid4())), rf3=True)
    config = tomllib.loads(lab.control.config.read_text(encoding='utf-8'))
    app = DistributedControl({**config['server'], **config['distributed']})
    try:
        identity, snapshot_id, handle_id, op_id, block_id = [str(uuid.uuid4()) for _ in range(5)]
        handle = dict(id=handle_id, file=identity, snapshot=snapshot_id, session='unit-session',
            user='unit-user', closed=False, revision=1, ancestors=[], mode=ctl.R_PLUS, busy=op_id)
        app.leases.refresh_handle(handle, initial=True)
        handle['expires'] = 1  # Wire hint obsolete, authoritative monotonic lease still live.
        with app.store.transaction(True) as tx:
            tx.put('snapshot', dict(id=snapshot_id, file=identity, ref=asdict(c.SnapshotRef(file_id=identity,
                manifest_root=snapshot_id, block_size_bytes=4194304)), blocks=[]))
            tx.put('handle', handle)
            lock = app.leases.acquire(tx, handle, [0], automatic=True)
            lock['active'] = [op_id]
            tx.put('lock', lock)
            tx.put('upload', dict(id=op_id, kind='write', state=c.PREPARING, handle=handle_id,
                locks=[lock['id']], expires=1, reserved=0, allocations={}, control_epoch=app.leases.epoch))
            tx.put('assignment', dict(id=block_id, operation=op_id, node=lab.node_ids[0], reserved=4096))
        app.collect()
        with app.store.transaction() as tx:
            assert tx.get('snapshot', snapshot_id) is not None
            assert tx.get('upload', op_id)['state'] == c.PREPARING
            assert app.usage(tx, dict(id=lab.node_ids[0]))[1] == 4096
        with app.store.transaction(True) as tx:
            lock['deadline'] = app.leases.clock() - 1
            tx.put('lock', lock)
        app.collect()
        with app.store.transaction() as tx:
            assert tx.get('upload', op_id)['state'] == c.EXPIRED
            assert tx.get('handle', handle_id)['busy'] is None
            assert app.usage(tx, dict(id=lab.node_ids[0]))[1] == 0
    finally:
        app.owner_lock.close()
