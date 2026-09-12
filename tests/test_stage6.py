"""R3/W2 real, dominios de proceso explícitos y volúmenes de laboratorio aislados."""
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import uuid
from pathlib import Path
import grpc
import pytest
from hito2_runtime import Cluster
from runtime import wait_until
from dfsha.common.domain import Fault, asdict, proto
from dfsha.control.metadata import SQLiteMetadataStore
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl, nodes_pb2 as n


@pytest.fixture
def cluster(run_dir):
    with Cluster(run_dir / ('replication-'+str(uuid.uuid4())), replication=True) as lab:
        yield lab


def rejected(action, reason):
    with pytest.raises((grpc.RpcError, Fault)) as error:
        action()
    assert reason in str(error.value)


def healthy(client, path, count=3):
    def check():
        status = client.protection(path)
        if all(b.eligible >= count for b in status.blocks):
            return status
    return wait_until(check, seconds=90)


def upload(client, tmp_path, path='/file', data=b'content'):
    local = tmp_path / ('input-'+str(uuid.uuid4()))
    local.write_bytes(data)
    return client.send(local, path)


def test_late_delete_physical_generation_guard(tmp_path):
    """Isolated deletion guard: authorization is stubbed, never evidence of distribution."""
    from types import SimpleNamespace
    from dfsha.datanode.blocks import EncryptedBlockStore
    from dfsha.datanode.service import DataNode
    app = DataNode.__new__(DataNode)
    app.cfg = {'replication_enabled': True}
    app.node_id = str(uuid.uuid4())
    app.store = SQLiteMetadataStore(tmp_path/'inventory.sqlite3')
    app.store.initialize()
    app.blocks = EncryptedBlockStore(tmp_path/'blocks', b'K'*32)
    block = c.BlockRef(file_id=str(uuid.uuid4()), block_version_id=str(uuid.uuid4()))
    current = app.blocks.path(block.file_id, block.block_version_id)
    current.parent.mkdir(parents=True, exist_ok=True)
    current.write_bytes(b'current physical instance; guard does not decode content')
    with app.store.transaction(True) as tx:
        tx.put('block', dict(id=block.block_version_id, receipt=dict(receipt_id='replacement-instance')))
    app.control_peer = lambda *args: None
    app.context = lambda: c.RequestContext()
    app.authorization = SimpleNamespace(AuthorizeInternal=lambda *args, **kwargs: n.AuthorizationDecision())
    rejected(lambda: app.DeleteRetiredBlock(n.DeleteRetiredBlockRequest(task_id=str(uuid.uuid4()),
        block=block, expected_receipt_id='retired-instance'), None), 'VERSION_CONFLICT')
    assert current.read_bytes() == b'current physical instance; guard does not decode content'
    with app.store.transaction() as tx:
        assert tx.get('block', block.block_version_id)['receipt']['receipt_id'] == 'replacement-instance'


def test_third_delayed_w2_and_empty(cluster, tmp_path, record_property):
    client = cluster.client()
    try:
        h = client.open('/empty', 'x+')
        client.close(h)
        assert client.protection('/empty').target_replicas == 3
        # Hold only copies to one node. A primary on that node is still allowed.
        held = cluster.node_ids[2]
        marker = cluster.faults / ('hold-copy-'+held)
        marker.touch()
        result = upload(client, tmp_path, data=b'hello'*1000000)
        assert result.minimum_durable == 2 and result.target_replicas == 3
        state = client.protection('/file')
        assert all(b.confirmed >= 2 for b in state.blocks)
        assert any(b.eligible == 2 for b in state.blocks)
        record_property('before_third', str(asdict(state)))
        client.logout()
        client.login('admin', 'development-password')
        marker.unlink()
        final = healthy(client, '/file')
        assert all(len({x.node.failure_domain for x in b.copies if x.eligible}) == 3 for b in final.blocks)
        record_property('after_third', str(asdict(final)))
        out = tmp_path / 'out'
        client.receive('/file', out)
        assert out.read_bytes() == b'hello'*1000000
    finally:
        client.shutdown()


def test_two_nodes_degraded_one_rejects_and_fourth_repairs(cluster, tmp_path, record_property):
    client = cluster.client()
    try:
        upload(client, tmp_path, data=b'A'*9000000)
        healthy(client, '/file')
        started = time.monotonic()
        cluster.nodes[0].stop()
        wait_until(lambda: next(x for x in client.nodes().nodes if x.node.node_id == cluster.node_ids[0]).state == 'UNAVAILABLE', seconds=15)
        record_property('detection_seconds_from_stop', time.monotonic()-started)
        result = upload(client, tmp_path, '/two', b'two')
        assert result.minimum_durable == 2 and result.degraded
        before = client.protection('/file')
        assert all(b.eligible == 2 for b in before.blocks)
        cluster.nodes[1].stop()
        wait_until(lambda: next(x for x in client.nodes().nodes if x.node.node_id == cluster.node_ids[1]).state == 'UNAVAILABLE', seconds=15)
        rejected(lambda: upload(client, tmp_path, '/one'), 'INSUFFICIENT_REPLICAS')
        h = client.open('/file')
        assert client.read(h, 0, 10) == b'A'*10
        client.close(h)
        cluster.nodes[1].start()
        cluster.wait_ready(2, client)
        started = time.monotonic()
        cluster.nodes[3].start()
        cluster.wait_ready(3, client)
        final = healthy(client, '/file')
        assert all(any(x.node.node_id == cluster.node_ids[3] and x.eligible for x in b.copies) for b in final.blocks)
        record_property('repair_seconds_from_fourth_start', time.monotonic()-started)
        record_property('before', str(asdict(before)))
        record_property('after', str(asdict(final)))
        cluster.nodes[0].start()
        cluster.wait_ready(4, client)
        assert all(b.eligible >= 3 for b in healthy(client, '/file').blocks)
    finally:
        client.shutdown()


def test_multiblock_insufficient_atomic_and_stale_fencing(cluster, tmp_path):
    client = cluster.client()
    try:
        upload(client, tmp_path, data=b'A'*8388608)
        healthy(client, '/file')
        writer = client.open('/file', 'r+')
        plan = client.begin_write(writer, 4194303, b'XY')
        (cluster.faults / ('hold-block-'+plan.blocks[1].replacement_block_version_id)).touch()
        changes = client.prepare_blocks(writer, plan, b'XY')
        wait_until(lambda: client.protection(operation_id=plan.operation.operation_id).blocks[0].eligible >= 2, seconds=30)
        assert client.protection(operation_id=plan.operation.operation_id).blocks[1].eligible == 1
        rejected(lambda: client.call(client.files.CommitWrite, ctl.CommitWriteRequest(operation=plan.operation,
            handle_id=writer.handle_id, expected_handle_revision=writer.revision, fences=plan.fences, changes=changes), retries=0), 'INSUFFICIENT_REPLICAS')
        reader = client.open('/file')
        assert client.read(reader, 4194303, 2) == b'AA'
        client.close(reader)
        client.call(client.files.AbortWrite, ctl.OperationRequest(operation=plan.operation))
        client.close(writer)
    finally:
        client.shutdown()


def test_disjoint_concurrent_and_lost_commit(cluster, tmp_path):
    first, second = cluster.client(), cluster.client()
    try:
        upload(first, tmp_path, data=b'A'*8388608)
        a, b = first.open('/file', 'r+'), second.open('/file', 'r+')
        pa, pb = first.begin_write(a, 0, b'X'), second.begin_write(b, 4194304, b'Y')
        gate = threading.Barrier(2)
        def prepare(client, handle, plan, value):
            gate.wait(timeout=10)
            result = client.prepare_blocks(handle, plan, value)
            client.wait_durable(plan.operation.operation_id)
            gate.wait(timeout=30)
            return result
        with ThreadPoolExecutor(2) as pool:
            fa = pool.submit(prepare, first, a, pa, b'X')
            fb = pool.submit(prepare, second, b, pb, b'Y')
            ca, cb = fa.result(), fb.result()
        first.commit_write(a, pa, ca)
        (cluster.faults / 'after_commit_drop_response').touch()
        result = second.commit_write(b, pb, cb)
        assert second.operation(pb.operation.operation_id).state == c.COMMITTED
        assert second.call(second.files.CommitWrite, second.last_commit_request) == result
        current = first.open('/file')
        assert first.read(current, 0, 1) == b'X'
        assert first.read(current, 4194304, 1) == b'Y'
        for client, handle in ((first, a), (second, b), (first, current)):
            client.close(handle)
    finally:
        first.shutdown()
        second.shutdown()


@pytest.mark.parametrize('size', [4194304, 67108864, 134217728])
def test_profiles_patch_delta(run_dir, tmp_path, size, record_property):
    with Cluster(run_dir / ('profile-'+str(uuid.uuid4())), replication=True, block_size=size) as lab:
        client = lab.client()
        try:
            local = tmp_path / 'profile'
            with local.open('wb') as out:
                for _ in range(size//262144):
                    out.write(b'A'*262144)
                out.write(b'B')
            client.send(local, '/profile')
            healthy(client, '/profile')
            before = {x.node.node_id: x for x in client.nodes().nodes}
            h = client.open('/profile', 'r+')
            assert client.write(h, size-2, b'XYZ') == 3
            assert client.read(h, size-3, 4) == b'AXYZ'
            healthy(client, '/profile')
            after = {x.node.node_id: x for x in client.nodes().nodes}
            # Heartbeat counters are eventually reported; observe a condition, not a fixed sleep.
            def traffic():
                current = {x.node.node_id: x for x in client.nodes().nodes}
                return current if sum(current[k].client_write_bytes-before[k].client_write_bytes for k in before) >= 3 else None
            after = wait_until(traffic, seconds=15)
            record_property('block_bytes', size)
            record_property('patch_client_bytes', sum(after[k].client_write_bytes-before[k].client_write_bytes for k in before))
            record_property('replica_ciphertext_bytes', sum(after[k].replica_write_bytes-before[k].replica_write_bytes for k in before))
            assert sum(after[k].client_write_bytes-before[k].client_write_bytes for k in before) == 3
            client.close(h)
        finally:
            client.shutdown()


def test_corrupt_copy_repair_and_interrupted_read(cluster, tmp_path, record_property):
    client = cluster.client()
    try:
        upload(client, tmp_path, data=b'A'*4194304)
        state = healthy(client, '/file')
        block = state.blocks[0].block
        bad = state.blocks[0].copies[0]
        index = cluster.node_ids.index(bad.node.node_id)
        path = cluster.nodes[index].directory / 'blocks' / block.file_id / (block.block_version_id+'.blk')
        # Only the isolated fixture object is modified to simulate corruption.
        with path.open('r+b') as out:
            out.seek(-1, 2)
            value = out.read(1)
            out.seek(-1, 2)
            out.write(bytes([value[0] ^ 1]))
        h = client.open('/file')
        assert client.read(h, 0, 4194304) == b'A'*4194304
        def repaired():
            status = client.protection('/file')
            repaired_copy = next(x for x in status.blocks[0].copies if x.node.node_id == bad.node.node_id)
            return status if repaired_copy.eligible and repaired_copy.receipt.receipt_id != bad.receipt.receipt_id else None
        final = wait_until(repaired, seconds=90)
        record_property('repaired', str(asdict(final)))
        (cluster.nodes[index].directory / 'faults' / 'interrupt_get').touch()
        target = tmp_path/'download-after-interruption'
        target.write_bytes(b'previous-local-version')
        client.receive('/file', target, overwrite=True)
        assert target.read_bytes() == b'A'*4194304
        for node in cluster.nodes[:3]:
            (node.directory / 'faults' / 'interrupt_get').touch()
        # Each failed source delivers one prefix; client resumes exact offsets on another copy.
        data = client.read(h, 0, 700000)
        assert data == b'A'*700000
        client.close(h)
    finally:
        client.shutdown()


def test_restart_pending_and_gc_tombstone(cluster, tmp_path):
    client = cluster.client()
    try:
        marker = cluster.faults / ('hold-copy-'+cluster.node_ids[2])
        marker.touch()
        upload(client, tmp_path, data=b'A'*5000000)
        cluster.control.stop()
        cluster.control.start()
        cluster.wait_ready(3, client)
        marker.unlink()
        state = healthy(client, '/file')
        objects = [node.directory / 'blocks' / b.block.file_id / (b.block.block_version_id+'.blk')
            for b in state.blocks for node in cluster.nodes[:3]]
        assert all(path.exists() for path in objects)
        old = client.open('/file')
        client.rm('/file')
        assert client.read(old, 0, 5) == b'AAAAA'
        assert all(path.exists() for path in objects)
        client.close(old)
        wait_until(lambda: all(not path.exists() for path in objects), seconds=90)
        rejected(lambda: client.open('/file'), 'NOT_FOUND')
        cluster.nodes[0].stop()
        cluster.nodes[0].start()
        cluster.wait_ready(3, client)
        rejected(lambda: client.open('/file'), 'NOT_FOUND')
    finally:
        client.shutdown()


def test_promotion_r1_retained_snapshot(run_dir, tmp_path):
    with Cluster(run_dir / ('promotion-'+str(uuid.uuid4())), replication=True, default_replicas=1) as lab:
        client = lab.client()
        try:
            upload(client, tmp_path, data=b'A'*4194304)
            reader = client.open('/file')
            writer = client.open('/file', 'r+')
            client.write(writer, 0, b'X')
            before = client.protection('/file')
            assert before.target_replicas == 1
            pending = client.begin_write(writer, 1, b'Y')
            changes = client.prepare_blocks(writer, pending, b'Y')
            client.promote('/file', before.policy_revision)
            rejected(lambda: client.call(client.files.CommitWrite, ctl.CommitWriteRequest(operation=pending.operation,
                handle_id=writer.handle_id, expected_handle_revision=writer.revision, changes=changes, fences=pending.fences), retries=0), 'VERSION_CONFLICT')
            final = wait_until(lambda: (s if (s := client.protection('/file')).policy_state == 'ACTIVE' and
                all(b.eligible == 3 for b in s.blocks) else None), seconds=90)
            assert before.blocks[0].block == final.blocks[0].block
            retained = client.protection('/file', snapshot_id=reader.snapshot.manifest_root)
            assert all(b.eligible == 3 for b in retained.blocks)
            assert client.read(reader, 0, 1) == b'A'
            assert client.write(writer, 1, b'Z') == 1
            client.close(reader)
            client.close(writer)
        finally:
            client.shutdown()


def test_volume_loss_keys_and_recovery(cluster, tmp_path, record_property):
    import tomllib
    client = cluster.client()
    try:
        upload(client, tmp_path, data=b'preserved'*500000)
        before = healthy(client, '/file')
        process = cluster.nodes[0]
        process.stop()
        cfg = tomllib.loads(process.config.read_text(encoding='utf-8'))['datanode']
        root = process.directory.resolve()
        volume = Path(cfg['block_path']).resolve()
        lost = root/'lost-test-volume'
        assert volume.is_relative_to(root) and lost.is_relative_to(root) and not lost.exists()
        volume.rename(lost)  # Isolated fixture only. No subsequent read/copy from this lost volume.
        volume.mkdir()
        store = SQLiteMetadataStore(cfg['sqlite_path'])
        with store.transaction(True) as tx:
            for record in tx.all('block'):
                tx.delete('block', record['id'])
        key = Path(cfg['key_path'])
        original = key.read_bytes()
        key.write_bytes(b'0'*32)
        with pytest.raises(RuntimeError, match='MASTER_KEY_MISMATCH'):
            process.start()
        key.write_bytes(original)
        started = time.monotonic()
        process.start()
        cluster.wait_ready(3, client)
        final = healthy(client, '/file')
        record_property('volume_repair_seconds_from_restart', time.monotonic()-started)
        assert before.blocks[0].block == final.blocks[0].block
        out = tmp_path/'restored'
        client.receive('/file', out)
        assert out.read_bytes() == b'preserved'*500000
    finally:
        client.shutdown()


def test_old_maintenance_callback_and_duplicate_receipt(cluster, tmp_path):
    import tomllib
    from dfsha.common import node_rpc
    from dfsha.v1 import nodes_pb2_grpc as ng
    client = cluster.client()
    try:
        upload(client, tmp_path, data=b'A'*4194304)
        healthy(client, '/file')
        h = client.open('/file', 'r+')
        plan = client.begin_write(h, 0, b'X')
        changes = client.prepare_blocks(h, plan, b'X')
        client.wait_durable(plan.operation.operation_id)
        changed = ctl.BlockChange()
        changed.CopyFrom(changes[0])
        changed.receipts.append(changes[0].receipts[0])
        rejected(lambda: client.call(client.files.CommitWrite, ctl.CommitWriteRequest(operation=plan.operation,
            handle_id=h.handle_id, expected_handle_revision=h.revision, fences=plan.fences, changes=[changed]), retries=0), 'CHECKSUM_MISMATCH')
        client.commit_write(h, plan, changes)
        client.close(h)
        cfg = tomllib.loads(cluster.control.config.read_text(encoding='utf-8'))['server']
        with SQLiteMetadataStore(cfg['sqlite_path']).transaction() as tx:
            task = next(t for t in tx.all('task') if t['kind'] == 'copy' and t['status']['state'] == 'FINISHED')
        dest = cluster.nodes[cluster.node_ids.index(task['dest'])]
        dn_cfg = tomllib.loads(dest.config.read_text(encoding='utf-8'))['datanode']
        callback = n.ReportTaskRequest(context=node_rpc.context_for(dn_cfg), node_id=task['dest'],
            boot_generation=dest.info['generation'], task=proto(n.TaskStatus, task['status']),
            fence=c.Fence(lock_id=task['id'], generation=task['generation'], service_epoch=cluster.epoch))
        cluster.control.stop()
        cluster.control.start()
        cluster.wait_ready(3, client)
        with node_rpc.channel(cluster.internal, dn_cfg) as channel:
            rejected(lambda: ng.NodeRegistryServiceStub(channel).ReportTask(callback, timeout=5), 'LOCK_EXPIRED')
        assert healthy(client, '/file').state == 'NORMAL'
    finally:
        client.shutdown()


def test_expired_writer_with_two_copies(run_dir, tmp_path):
    with Cluster(run_dir/('fenced-'+str(uuid.uuid4())), replication=True, lease_seconds=12) as lab:
        a, b = lab.client(), lab.client()
        try:
            upload(a, tmp_path, data=b'A'*4194304)
            healthy(a, '/file')
            ha = a.open('/file', 'r+')
            hb = b.open('/file', 'r+')
            plan = a.begin_write(ha, 0, b'X')
            changes = a.prepare_blocks(ha, plan, b'X')
            a.wait_durable(plan.operation.operation_id)
            wait_until(lambda: a.operation(plan.operation.operation_id).state == c.EXPIRED, seconds=25)
            assert b.write(hb, 0, b'Y') == 1
            rejected(lambda: a.call(a.files.CommitWrite, ctl.CommitWriteRequest(operation=plan.operation,
                handle_id=ha.handle_id, expected_handle_revision=ha.revision, fences=plan.fences, changes=changes), retries=0), 'OPERATION_EXPIRED')
            assert b.read(hb, 0, 1) == b'Y'
            a.close(ha)
            b.close(hb)
        finally:
            a.shutdown()
            b.shutdown()


def test_commit_without_original_primary_and_permissions(cluster, tmp_path):
    client = cluster.client()
    try:
        upload(client, tmp_path, data=b'A'*4194304)
        healthy(client, '/file')
        writer = client.open('/file', 'r+')
        plan = client.begin_write(writer, 0, b'X')
        changes = client.prepare_blocks(writer, plan, b'X')
        wait_until(lambda: all(b.eligible == 3 for b in client.protection(operation_id=plan.operation.operation_id).blocks), seconds=30)
        primary = plan.blocks[0].locations[0].node_id
        cluster.nodes[cluster.node_ids.index(primary)].stop()
        wait_until(lambda: next(x for x in client.nodes().nodes if x.node.node_id == primary).state == 'UNAVAILABLE', seconds=15)
        result = client.commit_write(writer, plan, changes)
        assert result.minimum_durable == 2 and result.degraded
        assert client.read(writer, 0, 2) == b'XA'
        client.close(writer)
        user = client.create_user('outsider', 'development-password')
        stranger = cluster.client()
        try:
            stranger.logout()
            stranger.login('outsider', 'development-password')
            rejected(lambda: stranger.protection('/file'), 'PERMISSION_DENIED')
            rejected(lambda: stranger.promote('/file', 1), 'PERMISSION_DENIED')
        finally:
            stranger.shutdown()
    finally:
        client.shutdown()
