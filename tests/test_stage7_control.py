"""ControlNodes y DataNodes separados, autoridad etcd real compartida."""
import uuid
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import grpc
import pytest
from pathlib import Path
from ha_runtime import HACluster
from dfsha.v1 import common_pb2 as c, control_pb2 as ctl
from runtime import wait_until


def test_cross_control_session_handle_and_data(run_dir, tmp_path, record_property):
    with HACluster(run_dir/('ha7-'+str(uuid.uuid4()))) as lab:
        a = lab.client(0)
        b = lab.client(1, a.session)
        try:
            a.mkdir('/shared')
            assert b.stat('/shared').object_id == a.stat('/shared').object_id
            local = tmp_path/'source'
            local.write_bytes(b'A'*5000000)
            result = a.send(local, '/shared/file')
            h = a.open('/shared/file', 'r+')
            assert b.read(h, 0, 8) == b'A'*8
            b.renew_handle(h)
            assert b.write(h, 4194303, b'XY') == 2
            assert a.read(h, 4194302, 4) == b'AXYA'
            lab.controls[0].stop()
            assert b.read(h, 4194302, 4) == b'AXYA'
            b.close(h)
            record_property('members', str(lab.etcd.status()))
            record_property('migration', str(lab.migration))
        finally:
            a.shutdown()
            b.shutdown()


def test_cross_control_parallel_publication_and_lost_reply(run_dir, tmp_path, record_property):
    with HACluster(run_dir/('parallel7-'+str(uuid.uuid4()))) as lab:
        a, b = lab.client(0), lab.client(1)
        size = 4194304
        source = tmp_path/'parallel'
        source.write_bytes(b'A'*size+b'B'*size)
        try:
            a.send(source, '/parallel')
            left, right, reader = a.open('/parallel', 'r+'), b.open('/parallel', 'r+'), a.open('/parallel')
            barrier = threading.Barrier(2)
            with ExitStack() as leases:
                leases.enter_context(a.keepalive(reader))
                def prepare(sdk, handle, offset, data):
                    plan = sdk.begin_write(handle, offset, data)
                    keeper = sdk.write_keepalive(handle, plan)
                    keeper.__enter__()
                    try:
                        barrier.wait(20)
                        blocks = sdk.prepare_blocks(handle, plan, data)
                        sdk.wait_durable(plan.operation.operation_id)
                        return plan, blocks, keeper
                    except BaseException:
                        keeper.__exit__(None, None, None)
                        raise
                with ThreadPoolExecutor(2) as pool:
                    fa = pool.submit(prepare, a, left, 0, b'a'*4096)
                    fb = pool.submit(prepare, b, right, size, b'b'*4096)
                    pa, ca, ka = fa.result(timeout=240)
                    leases.callback(ka.__exit__, None, None, None)
                    pb, cb, kb = fb.result(timeout=240)
                    leases.callback(kb.__exit__, None, None, None)
                # Both independent preparations attained W2 before either publication.
                assert a.operation(pa.operation.operation_id).state == c.PREPARING
                assert b.operation(pb.operation.operation_id).state == c.PREPARING
                a.commit_write(left, pa, ca)
                b.commit_write(right, pb, cb)
                assert a.read(reader, 0, 1) == b'A'
                assert a.read(left, size, 1) == b'B'
                assert b.read(right, 0, 1) == b'a'
            fresh = a.open('/parallel', 'r+')
            lock = a.lock(fresh, 0, 1)
            with pytest.raises(grpc.RpcError, match='LOCK_CONFLICT'):
                b.lock(right, 2, 1)
            a.unlock(lock)
            plan = a.begin_write(fresh, 0, b'Z')
            with a.write_keepalive(fresh, plan):
                changes = a.prepare_blocks(fresh, plan, b'Z')
                a.wait_durable(plan.operation.operation_id)
                request = a.prepare(ctl.CommitWriteRequest(operation=plan.operation, handle_id=fresh.handle_id,
                    changes=changes, fences=plan.fences, expected_handle_revision=fresh.revision))
                (lab.controls[0].directory/'faults'/'after_commit_drop_response').touch()
                with pytest.raises(grpc.RpcError):
                    a.files.CommitWrite(request, metadata=a.metadata, timeout=15)
                alternate = lab.client(2, a.session)
                try:
                    status = alternate.operation(plan.operation.operation_id)
                    assert status.state == c.COMMITTED
                    replay = alternate.call(alternate.files.CommitWrite, request)
                    assert replay == status.result
                    fresh.snapshot.CopyFrom(replay.snapshot)
                    fresh.revision += 1
                    alternate.close(fresh)
                finally:
                    alternate.shutdown()
            for sdk, handle in ((a, left), (b, right), (a, reader)):
                sdk.close(handle)
            record_property('parallel', 'two controls; barrier before PatchBlock; W2 on both before commits; final A1 B1')
            record_property('lost_response', 'commit on control 0; result and identical replay on control 2')
        finally:
            a.shutdown()
            b.shutdown()


def test_e6_migration_and_full_backup_restore(run_dir, tmp_path, record_property):
    from ha_recovery import backup_lab, RestoredHACluster
    from measure_stage6 import full
    source = tmp_path/'migration-source'
    source.write_bytes(b'original snapshot\x00'*1000)
    lab = HACluster(run_dir/('migration7-'+str(uuid.uuid4())))
    def seed(cluster, client):
        committed = client.send(source, '/migrated')
        old = client.open('/migrated')
        full(client, '/migrated')
        source.write_bytes(b'current snapshot\xff'*1000)
        current = client.send(source, '/migrated', overwrite=True)
        full(client, '/migrated')
        return committed, current, old
    original, current, old = lab.seed_e6(seed)
    bundle = run_dir/('backup7-'+str(uuid.uuid4()))
    with lab:
        client = lab.client()
        try:
            assert client.stat('/migrated').object_id == current.snapshot.file_id
            result = client.receive('/migrated', tmp_path/'migrated-output')
            assert (tmp_path/'migrated-output').read_bytes() == source.read_bytes()
            assert client.operation(current.operation.operation_id).result.snapshot == current.snapshot
            store = lab.metadata()
            try:
                with store.transaction() as tx:
                    retained = tx.all('migration-pin')
                    assert retained
                    snapshots = [tx.get('snapshot', x['snapshot']) for x in retained]
                    from dfsha.common.domain import asdict
                    assert any(x['ref'] == asdict(old.snapshot) for x in snapshots)
            finally:
                store.channel.close()
            retained = client.open('/migrated')
            old_session = client.session
            full(client, '/migrated')
            report = backup_lab(lab, bundle)
            record_property('backup', str(report))
        finally:
            client.shutdown()
    with RestoredHACluster(bundle, run_dir/('restored7-'+str(uuid.uuid4()))) as restored:
        client = restored.client()
        try:
            assert client.session.service_epoch != old_session.service_epoch
            assert client.stat('/migrated').object_id == current.snapshot.file_id
            client.receive('/migrated', tmp_path/'restored-output')
            assert (tmp_path/'restored-output').read_bytes() == source.read_bytes()
            assert client.operation(current.operation.operation_id).result.snapshot == current.snapshot
            with pytest.raises(grpc.RpcError):
                client.read(retained, 0, 1)
            record_property('migration', str(lab.migration))
            record_property('sha256', result['sha256'])
        finally:
            client.shutdown()


def test_control_failover_network_partition_and_quorum(run_dir, tmp_path, record_property):
    from dfsha.v1 import namespace_pb2 as ns
    with HACluster(run_dir/('failover7-'+str(uuid.uuid4()))) as lab:
        client = lab.client()
        source = tmp_path/'failover'
        source.write_bytes(b'failover-data'*1000)
        try:
            # Actual process exit immediately before CommitUpload; the SDK must
            # keep the same operation and finish via another active control.
            (lab.controls[0].directory/'faults'/'before_publish').touch()
            result = client.send(source, '/survives')
            assert lab.controls[0].process.poll() is not None
            h = client.open('/survives', 'r+')
            old_epoch = client.session.service_epoch
            lab.controls[0].start()
            alternate = lab.client(0, client.session)
            try:
                alternate.renew_handle(h)
                assert alternate.read(h, 0, 13) == b'failover-data'
                assert alternate.session.service_epoch == old_epoch
                start = time.monotonic()
                for proxy in lab.proxies[0]:
                    proxy.partition()
                request = alternate.prepare(ns.PathRequest(path=alternate.path('/survives')))
                with pytest.raises(grpc.RpcError):
                    alternate.namespace.Stat(request, metadata=alternate.metadata, timeout=4)
                assert lab.controls[0].process.poll() is None
                other = lab.client(1, client.session)
                try:
                    other.mkdir('/majority')
                    for proxy in lab.proxies[0]:
                        proxy.heal()
                    def visible():
                        try:
                            return alternate.stat('/majority').object_id
                        except grpc.RpcError:
                            return None
                    wait_until(visible, seconds=20)
                    record_property('partition_recovery_seconds', time.monotonic()-start)
                    membership = lab.etcd.status()
                    leader = next(i for i,m in enumerate(membership) if m['member'] == m['leader'])
                    lab.etcd.members[leader].stop()
                    lab.controls[2].stop()
                    # Simultaneous loss of a control and the etcd leader.
                    assert other.read(h, 0, 13) == b'failover-data'
                    second = next(i for i in range(3) if i != leader)
                    lab.etcd.members[second].stop()
                    start = time.monotonic()
                    denied = other.prepare(ns.PathRequest(path=other.path('/survives')))
                    with pytest.raises(grpc.RpcError):
                        other.namespace.Stat(denied, metadata=other.metadata, timeout=4)
                    mutation = other.prepare(ns.PathRequest(path=other.path('/forbidden-minority')))
                    with pytest.raises(grpc.RpcError):
                        other.namespace.Mkdir(mutation, metadata=other.metadata, timeout=4)
                    record_property('quorum_error_seconds', time.monotonic()-start)
                    lab.etcd.members[second].start()
                    wait_until(lambda: visible(), seconds=20)
                    assert other.operation(result.operation.operation_id).state == c.COMMITTED
                    with pytest.raises(grpc.RpcError, match='NOT_FOUND'):
                        other.stat('/forbidden-minority')
                    assert other.read(h, 0, 13) == b'failover-data'
                    other.close(h)
                finally:
                    other.shutdown()
            finally:
                alternate.shutdown()
        finally:
            client.shutdown()


def test_expired_writer_with_two_copies_cannot_publish(run_dir, tmp_path):
    from dfsha.common.domain import Fault
    with HACluster(run_dir/('fencing7-'+str(uuid.uuid4()))) as lab:
        a, b = lab.client(0), lab.client(1)
        source = tmp_path/'fencing'
        source.write_bytes(b'old content'*1000)
        try:
            a.send(source, '/fencing')
            old = a.open('/fencing', 'r+')
            plan = a.begin_write(old, 0, b'OLD')
            with a.write_keepalive(old, plan):
                changes = a.prepare_blocks(old, plan, b'OLD')
                a.wait_durable(plan.operation.operation_id)
            store = lab.metadata()
            try:
                def expired():
                    with store.transaction() as tx:
                        lock = tx.get('lock', plan.fences[0].lock_id)
                        return not lock or not store.lease_live(lock)
                wait_until(expired, seconds=40)
            finally:
                store.channel.close()
            fresh = b.open('/fencing', 'r+')
            successor = b.lock(fresh, 0, 3)
            with pytest.raises((Fault, grpc.RpcError)) as stale:
                a.commit_write(old, plan, changes)
            assert any(reason in str(stale.value) for reason in ('LOCK_EXPIRED', 'OPERATION_EXPIRED', 'VERSION_CONFLICT'))
            with pytest.raises(grpc.RpcError):
                a.unlock(plan.fences[0])
            b.renew_lock(successor)
            assert b.write(fresh, 0, b'NEW', fences=[successor]) == 3
            assert b.read(fresh, 0, 3) == b'NEW'
            b.unlock(successor)
            b.close(fresh)
            a.close(old)
        finally:
            a.shutdown()
            b.shutdown()


def test_cross_control_capacity_reservations_are_atomic(run_dir):
    import hashlib
    from dfsha.common.domain import Fault
    # One encrypted/staged 4 MiB object per node, insufficient for two uploads.
    with HACluster(run_dir/('capacity7-'+str(uuid.uuid4())), capacities=[6291456]*4) as lab:
        a, b = lab.client(0), lab.client(1)
        barrier = threading.Barrier(2)
        plans = []
        def reserve(client, name):
            plan = client.call(client.uploads.BeginUpload, ctl.BeginUploadRequest(path=client.path(name),
                total_bytes=4194304, file_sha256=hashlib.sha256(b'A'*4194304).digest()))
            plans.append((client, plan))
            barrier.wait(20)
            try:
                return client.call(client.uploads.AllocateBlocks, ctl.AllocateBlocksRequest(
                    operation=plan.operation, fence=plan.fence, blocks=[c.BlockRef(file_id=plan.file_id,
                        size_bytes=4194304, plaintext_sha256=hashlib.sha256(b'A'*4194304).digest())]))
            except (Fault, grpc.RpcError) as exc:
                assert any(reason in str(exc) for reason in ('NO_SPACE', 'INSUFFICIENT_REPLICAS'))
                return None
        try:
            with ThreadPoolExecutor(2) as pool:
                first = pool.submit(reserve, a, '/first')
                second = pool.submit(reserve, b, '/second')
                results = [first.result(timeout=60), second.result(timeout=60)]
            assert sum(result is not None for result in results) == 1
            status = a.nodes()
            assert all(node.reserved_bytes <= node.capacity_bytes for node in status.nodes)
            assert sum(node.reserved_bytes for node in status.nodes) > 0
            for client, plan in plans:
                client.call(client.uploads.AbortUpload, ctl.OperationRequest(operation=plan.operation))
            assert sum(node.reserved_bytes for node in b.nodes().nodes) == 0
        finally:
            a.shutdown()
            b.shutdown()


def test_restart_entire_lab_preserves_epoch_and_unexpired_handle(run_dir, tmp_path):
    from run_ha_lab import save, ExistingHACluster
    root = run_dir/('restart7-'+str(uuid.uuid4()))
    source = tmp_path/'persistent'
    source.write_bytes(b'persistent bytes'*100)
    with HACluster(root) as lab:
        client = lab.client()
        try:
            committed = client.send(source, '/persistent')
            handle = client.open('/persistent')
            session = client.session
            save(lab)
        finally:
            client.shutdown()
    with ExistingHACluster(root) as restarted:
        client = restarted.client(session=session)
        try:
            client.renew_handle(handle)
            assert client.read(handle, 0, 16) == b'persistent bytes'
            assert client.operation(committed.operation.operation_id).state == c.COMMITTED
            client.close(handle)
            assert restarted.epoch == session.service_epoch
        finally:
            client.shutdown()


def test_maintenance_takeover_rejects_old_callback_and_preserves_snapshot(run_dir, tmp_path, record_property):
    import tomllib
    from dfsha.common import node_rpc
    from dfsha.v1 import nodes_pb2 as n, nodes_pb2_grpc as ng
    from measure_stage6 import full
    with HACluster(run_dir/('maintenance7-'+str(uuid.uuid4()))) as lab:
        client = lab.client()
        store = lab.metadata()
        source = tmp_path/'maintenance'
        source.write_bytes(b'maintenance snapshot'*1000)
        try:
            markers = [p.directory/'faults'/('hold-copy-'+node_id) for p in lab.controls for node_id in lab.node_ids]
            for marker in markers:
                marker.touch()
            def pending():
                with store.transaction() as tx:
                    tasks = [t for t in tx.all('task') if t['kind'] == 'copy' and t['status']['state'] == 'ACCEPTED']
                    leader = tx.get('settings', 'maintenance')
                    return (tasks[0], leader) if tasks and leader else None
            with ThreadPoolExecutor(1) as pool:
                upload = pool.submit(client.send, source, '/maintenance')
                old_task, old_leader = wait_until(pending, seconds=60)
                index = lab.control_ids.index(old_leader['control_id'])
                lab.controls[index].stop()
                for marker in markers:
                    marker.unlink(missing_ok=True)
                result = upload.result(timeout=240)
            full(client, '/maintenance')
            with store.transaction() as tx:
                leader = tx.get('settings', 'maintenance')
                node = tx.get('datanode', old_task['dest'])
                assert leader['generation'] > old_leader['generation']
            node_index = lab.node_ids.index(old_task['dest'])
            cfg = tomllib.loads(lab.nodes[node_index].config.read_text(encoding='utf-8'))['datanode']
            active_control = next(i for i in range(3) if i != index)
            with node_rpc.channel(lab.internal_targets[active_control], cfg) as transport:
                with pytest.raises(grpc.RpcError, match='LOCK_EXPIRED'):
                    ng.NodeRegistryServiceStub(transport).ReportTask(n.ReportTaskRequest(
                        context=node_rpc.context_for(cfg), node_id=old_task['dest'],
                        boot_generation=int(node['location']['boot_generation']),
                        task=n.TaskStatus(task_id=old_task['id'], state=n.FAILED),
                        fence=c.Fence(lock_id=old_task['id'], service_epoch=lab.epoch, generation=old_task['generation'])), timeout=15)
            other = lab.client(active_control, client.session)
            try:
                reader = other.open('/maintenance')
                client.rm('/maintenance')
                assert other.read(reader, 0, 20) == b'maintenance snapshot'
                other.close(reader)
                def retired():
                    with store.transaction() as tx:
                        blocks = [b for b in tx.all('retired') if b['ref']['file_id'] == result.snapshot.file_id]
                        return blocks if blocks else None
                assert wait_until(retired, seconds=60)
                record_property('maintenance_generations', str((old_leader['generation'], leader['generation'])))
            finally:
                other.shutdown()
        finally:
            client.shutdown()
            store.channel.close()
