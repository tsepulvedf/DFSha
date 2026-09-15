"""E4: conexiones TLS/mTLS reales y almacenamiento independiente por proceso."""
import hashlib
from pathlib import Path
from uuid import uuid4
import pytest
from hito2_runtime import Cluster
from test_hito1 import make_file
from dfsha.v1 import nodes_pb2 as n, nodes_pb2_grpc as ng, common_pb2 as c, control_pb2 as ctl
from runtime import wait_until


def resolve(client, handle, limit=64):
    return client.call(client.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
        snapshot=handle.snapshot, offset=0, length=handle.snapshot.size_bytes, page=c.PageRequest(limit=limit)))


def allocation(client, name, content):
    plan = client.call(client.uploads.BeginUpload, ctl.BeginUploadRequest(path=client.path(name),
        total_bytes=len(content), file_sha256=hashlib.sha256(content).digest()))
    block = client.call(client.uploads.AllocateBlocks, ctl.AllocateBlocksRequest(operation=plan.operation, fence=plan.fence,
        blocks=[c.BlockRef(file_id=plan.file_id, size_bytes=len(content), plaintext_sha256=hashlib.sha256(content).digest())])).blocks[0]
    return plan, block


@pytest.fixture
def cluster(run_dir):
    with Cluster(run_dir / ('h2-' + str(uuid4()))) as app:
        yield app


def test_distribution_roundtrip_copy_restart(cluster, record_property):
    client = cluster.client()
    try:
        client.mkdir('/distributed')
        source = cluster.directory / 'client-source.bin'
        digest = make_file(source, 3 * 4194304 + 1)
        result = client.send(source, '/distributed/data')
        assert result.minimum_durable == 1
        handle = client.open_read('/distributed/data')
        plan = client.call(client.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
            snapshot=handle.snapshot, offset=0, length=handle.snapshot.size_bytes, page=c.PageRequest(limit=64)))
        assert len({b.locations[0].node_id for b in plan.blocks}) == 3
        assert client.receive_handle(handle, cluster.directory / 'download.bin')['sha256'] == digest
        assert not list((cluster.control.directory / 'blocks').rglob('*.blk'))
        first = plan.blocks[0]
        origin = first.locations[0].node_id
        destination = next(x for x in cluster.node_ids[:3] if x != origin)
        stub = ng.ClusterAdministrationServiceStub(client.channel)
        task = client.call(stub.CopyBlock, n.CopyBlockRequest(block=first.block, source_node_id=origin, destination_node_id=destination))
        def finished():
            current = client.call(stub.CopyStatus, n.GetTaskRequest(task_id=task.task_id))
            assert current.state != n.FAILED
            return current if current.state == n.FINISHED else None
        wait_until(finished, seconds=30)
        cluster.nodes[cluster.node_ids.index(origin)].stop()
        wait_until(lambda: any(x.node.node_id == origin and x.state == 'UNAVAILABLE' for x in cluster.statuses(client).nodes), seconds=15)
        # Only copied block has redundancy; read that block directly from the destination.
        resolved = client.call(client.files.ResolveBlocks, ctl.ResolveBlocksRequest(handle_id=handle.handle_id,
            snapshot=handle.snapshot, offset=0, length=first.block.size_bytes, page=c.PageRequest(limit=1)))
        assert resolved.blocks[0].locations[0].node_id == destination
        from dfsha.common.rpc import channel
        from dfsha.v1 import data_pb2 as d, data_pb2_grpc as dg
        request = client.prepare(d.GetBlockRequest(handle_id=handle.handle_id, snapshot=handle.snapshot,
            block=first.block, length=first.block.size_bytes, capability=resolved.blocks[0].grants[0].capability))
        with channel(resolved.blocks[0].locations[0].client_endpoint, cluster.certs) as connection:
            frames = dg.BlockServiceStub(connection).GetBlock(request, metadata=client.metadata, timeout=30)
            next(frames)
            actual = hashlib.sha256()
            for frame in frames:
                actual.update(frame.chunk.data)
            assert actual.digest() == first.block.plaintext_sha256
        cluster.nodes[cluster.node_ids.index(origin)].start()
        cluster.wait_ready(3, client)
        destination_process = cluster.nodes[cluster.node_ids.index(destination)]
        destination_process.stop()
        destination_process.start()
        cluster.wait_ready(3, client)
        import tomllib
        from dfsha.common import node_rpc
        control_config = tomllib.loads(cluster.control.config.read_text())
        cfg = {**control_config['server'], **control_config['distributed'], 'service_epoch': cluster.epoch}
        receipt = finished().receipt
        with node_rpc.channel(destination_process.info['internal_target'], cfg) as connection:
            recovered_receipt = ng.StorageAdministrationServiceStub(connection).VerifyReceipt(n.VerifyReceiptRequest(
                context=node_rpc.context_for(cfg), block=first.block, operation_id=receipt.operation_id,
                receipt_id=receipt.receipt_id, expected_boot_generation=destination_process.info['generation']), timeout=5)
        assert recovered_receipt == receipt
        assert client.receive('/distributed/data', cluster.directory / 'recovered.bin')['sha256'] == digest
        from dfsha.common.domain import asdict
        import json
        traffic = wait_until(lambda: (s if sum(x.replica_write_bytes for x in s.nodes) >= receipt.stored_size_bytes and
            sum(x.replica_read_bytes for x in s.nodes) >= receipt.stored_size_bytes else None)
            if (s := cluster.statuses(client)) else None, seconds=15)
        record_property('copy_evidence', json.dumps(dict(task_id=task.task_id, source=origin, destination=destination,
            bytes=receipt.stored_size_bytes, ciphertext_sha256=receipt.ciphertext_sha256.hex(),
            block_sha256=first.block.plaintext_sha256.hex(), source_stopped_read=True,
            receipt_recovered_after_destination_restart=True, nodes=[asdict(x) for x in traffic.nodes])))
        client.close(handle)
    finally:
        client.shutdown()


def test_cli_process_and_unindexed_crash_recovery(cluster):
    import subprocess
    import sys
    import grpc
    from dfsha.common.rpc import channel
    from dfsha.v1 import data_pb2 as d, data_pb2_grpc as dg
    from runtime import ROOT, PROCESS_FLAGS
    config = cluster.directory / 'client.toml'
    session = cluster.directory / 'client-session.json'
    base = [sys.executable, '-m', 'dfsha.client.cli', '--config', str(config), '--session-file', str(session)]
    login = subprocess.run(base + ['login', 'admin', '--password-stdin'], input='development-password\n', text=True,
        capture_output=True, cwd=ROOT, creationflags=PROCESS_FLAGS)
    assert login.returncode == 0, login.stderr
    source = cluster.directory / 'cli-source'
    source.write_bytes(b'CLI uses only its config, CA and local input')
    for arguments in (['mkdir', '/cli'], ['put', str(source), '/cli/file'], ['get', '/cli/file', str(cluster.directory / 'cli-output')],
                      ['nodes'], ['rm', '/cli/file'], ['rmdir', '/cli']):
        result = subprocess.run(base + arguments, capture_output=True, text=True, cwd=ROOT, creationflags=PROCESS_FLAGS)
        assert result.returncode == 0, result.stderr
    assert source.read_bytes() == (cluster.directory / 'cli-output').read_bytes()
    client = cluster.client()
    try:
        plan, block = allocation(client, '/orphan', b'crash-data')
        node = cluster.nodes[cluster.node_ids.index(block.locations[0].node_id)]
        (node.directory / 'faults/after_block_persist').touch()
        header = client.prepare(d.PutBlockHeader(operation=plan.operation, fence=plan.fence, block=block.block,
            capability=block.grants[0].capability))
        with channel(block.locations[0].client_endpoint, cluster.certs) as connection:
            with pytest.raises(grpc.RpcError):
                dg.BlockServiceStub(connection).PutBlock(iter([d.PutBlockFrame(header=header),
                    d.PutBlockFrame(chunk=d.DataChunk(data=b'crash-data'))]), metadata=client.metadata, timeout=30)
        assert node.process.wait(timeout=10) == 93
        node.stop()
        stored = node.directory / 'blocks' / block.block.file_id / (block.block.block_version_id + '.blk')
        assert stored.exists()
        node.start()
        cluster.wait_ready(3, client)
        wait_until(lambda: not stored.exists(), seconds=20)
        from test_hito1 import error
        error('NOT_FOUND', lambda: client.stat('/orphan'))
        assert sum(x.reserved_bytes for x in cluster.statuses(client).nodes) == 0
    finally:
        client.shutdown()


def test_namespace_snapshot_lost_commit_and_control_restart(cluster):
    from test_hito1 import test_rf1_paths_permissions_pagination_cwd, test_overwrite_snapshot_delete_idempotency
    client = cluster.client()
    try:
        test_rf1_paths_permissions_pagination_cwd(client, cluster)
        test_overwrite_snapshot_delete_idempotency(client, cluster)
        source = cluster.directory / 'persisted-source'
        source.write_bytes(b'persisted control and independent block volumes')
        (cluster.faults / 'after_commit_drop_response').touch()
        result = client.send(source, '/persisted')
        assert client.call(client.uploads.CommitUpload, client.last_commit_request) == result
        handle = client.open_read('/persisted')
        cluster.control.stop()
        cluster.control.start()
        cluster.wait_ready(3, client)
        assert client.receive_handle(handle, cluster.directory / 'persisted-output')['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
        client.close(handle)
    finally:
        client.shutdown()


@pytest.mark.parametrize('size', [4194304, 67108864, 134217728])
def test_profiles_boundaries_and_coexistence(run_dir, size):
    import re
    with Cluster(run_dir / ('profiles-' + str(uuid4())), block_size=4194304) as app:
        client = app.client()
        try:
            source = app.directory / 'source'
            digest = make_file(source, 4194305)
            old = client.send(source, '/old-profile')
            app.control.stop()
            text = app.control.config.read_text(encoding='utf-8')
            app.control.config.write_text(text.replace('block_size_bytes = 4194304', f'block_size_bytes = {size}'), encoding='utf-8')
            app.control.start()
            app.wait_ready(3, client)
            assert client.receive('/old-profile', app.directory / 'old-output')['sha256'] == digest
            assert client.send(source, '/old-profile', overwrite=True).snapshot.block_size_bytes == 4194304
            for length in (0, 17, size-1, size, size+1):
                digest = make_file(source, length)
                result = client.send(source, f'/size-{length}')
                assert result.snapshot.block_size_bytes == size
                output = app.directory / f'output-{length}'
                assert client.receive(f'/size-{length}', output)['sha256'] == digest
                output.unlink()
            handle = client.open_read('/size-' + str(size+1))
            assert len(resolve(client, handle).blocks) == 2
            client.close(handle)
        finally:
            client.shutdown()


def test_dynamic_fourth_node_reservations_and_unavailable(run_dir):
    import grpc
    from test_hito1 import error
    quotas = [100, 6*4194304, 12*4194304, 20*4194304]
    with Cluster(run_dir / ('placement-' + str(uuid4())), capacities=quotas) as app:
        client = app.client()
        try:
            source = app.directory / 'source'
            digest = make_file(source, 4194305)
            client.send(source, '/before')
            assert next(x for x in app.statuses(client).nodes if x.node.node_id == app.node_ids[0]).confirmed_blocks == 0
            app.nodes[3].start()
            app.wait_ready(4, client)
            # Occupation preference puts at least one new block on the empty newly registered node.
            client.send(source, '/after')
            handle = client.open_read('/after')
            assert app.node_ids[3] in {x.locations[0].node_id for x in resolve(client, handle).blocks}
            client.close(handle)
            assert client.receive('/before', app.directory / 'before-out')['sha256'] == digest
            content = b'a'*4194304
            from concurrent.futures import ThreadPoolExecutor
            def reserve(index):
                own = app.client()
                try:
                    return own, allocation(own, f'/reserved-{index}', content)
                except BaseException:
                    own.shutdown()
                    raise
            with ThreadPoolExecutor(max_workers=3) as pool:
                reserved = list(pool.map(reserve, range(3)))
            assert sum(x.reserved_bytes for x in app.statuses(client).nodes) >= len(content)*3
            for own, (plan, _) in reserved:
                own.call(own.uploads.AbortUpload, ctl.OperationRequest(operation=plan.operation))
                own.shutdown()
            assert sum(x.reserved_bytes for x in app.statuses(client).nodes) == 0
            # Stop all capable nodes: the only live quota cannot fit an encrypted block.
            for node in app.nodes[1:]:
                node.stop()
            wait_until(lambda: sum(x.state == 'UNAVAILABLE' for x in app.statuses(client).nodes) == 3, seconds=15)
            error('NO_SPACE', lambda: client.send(source, '/no-nodes'))
            error('DATA_UNAVAILABLE', lambda: client.receive('/before', app.directory / 'unavailable'))
        finally:
            client.shutdown()


def test_block_authentication_corruption_and_internal_roles(cluster):
    import grpc
    import tomllib
    from dfsha.client.sdk import Client
    from dfsha.common.rpc import channel
    from dfsha.common import node_rpc
    from dfsha.v1 import data_pb2 as d, data_pb2_grpc as dg
    from test_hito1 import error
    client = cluster.client()
    try:
        source = cluster.directory / 'secret-source'
        source.write_bytes(b'protected binary data')
        client.send(source, '/protected')
        handle = client.open_read('/protected')
        block = resolve(client, handle).blocks[0]
        target = block.locations[0].client_endpoint
        request = client.prepare(d.GetBlockRequest(handle_id=handle.handle_id, snapshot=handle.snapshot,
            block=block.block, length=block.block.size_bytes, capability=b'x'*32))
        with channel(target, cluster.certs) as connection:
            rpc = dg.BlockServiceStub(connection).GetBlock
            error('PERMISSION_DENIED', lambda: list(rpc(request, metadata=client.metadata, timeout=30)))
            error('UNAUTHENTICATED', lambda: list(rpc(request, timeout=30)))
            request.capability = block.grants[0].capability
            client.create_user('outsider', 'outsider-password')
            outsider = Client(cluster.target, cluster.certs)
            outsider.login('outsider', 'outsider-password')
            request.context.CopyFrom(outsider.prepare(d.GetBlockRequest()).context)
            error('STALE_HANDLE', lambda: list(rpc(request, metadata=outsider.metadata, timeout=30)))
            outsider.shutdown()
        # User TLS cannot authenticate to private node APIs without a client certificate.
        with channel(cluster.internal, cluster.certs) as connection:
            with pytest.raises(grpc.RpcError) as failure:
                ng.NodeRegistryServiceStub(connection).RegisterNode(n.RegisterNodeRequest(), timeout=2)
            assert failure.value.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)
        with channel(cluster.internal, cluster.authority, identity='client') as connection:
            error('PERMISSION_DENIED', lambda: ng.NodeRegistryServiceStub(connection).RegisterNode(
                n.RegisterNodeRequest(context=c.RequestContext(request_id=str(uuid4()), user_id=cluster.node_ids[0],
                    service_epoch=cluster.epoch), node=c.BlockLocation(node_id=cluster.node_ids[0])), timeout=5))
        # Authenticated node 1 cannot impersonate node 2 or invent an unallocated durable block.
        cfg = tomllib.loads(cluster.nodes[0].config.read_text())['datanode']
        with node_rpc.channel(cluster.internal, cfg) as connection:
            registry = ng.NodeRegistryServiceStub(connection)
            error('PERMISSION_DENIED', lambda: registry.Heartbeat(n.HeartbeatRequest(context=node_rpc.context_for(cfg),
                node_id=cluster.node_ids[1], boot_generation=1, sequence=1), timeout=5))
        with channel(target, cluster.authority, ca_name='rogue-ca') as connection:
            with pytest.raises(grpc.RpcError) as failure:
                list(dg.BlockServiceStub(connection).GetBlock(request, timeout=2))
            assert failure.value.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)
        node = cluster.nodes[cluster.node_ids.index(block.locations[0].node_id)]
        stored = node.directory / 'blocks' / block.block.file_id / (block.block.block_version_id + '.blk')
        payload = bytearray(stored.read_bytes())
        assert source.read_bytes() not in payload
        payload[-1] ^= 1
        stored.write_bytes(payload)
        output = cluster.directory / 'existing'
        output.write_bytes(b'keep')
        error('DATA_LOSS', lambda: client.receive_handle(handle, output, overwrite=True))
        assert output.read_bytes() == b'keep'
        client.close(handle)
    finally:
        client.shutdown()


def test_interruption_expiry_restart_and_late_receipts(cluster):
    import grpc
    import tomllib
    from dfsha.common.rpc import channel
    from dfsha.common import node_rpc
    from dfsha.control.metadata import SQLiteMetadataStore
    from dfsha.v1 import data_pb2 as d, data_pb2_grpc as dg
    from test_hito1 import error
    client = cluster.client()
    try:
        plan, block = allocation(client, '/interrupted', b'abcdef')
        header = client.prepare(d.PutBlockHeader(operation=plan.operation, fence=plan.fence, block=block.block,
            capability=block.grants[0].capability))
        with channel(block.locations[0].client_endpoint, cluster.certs) as connection:
            error('CHECKSUM_MISMATCH', lambda: dg.BlockServiceStub(connection).PutBlock(iter([d.PutBlockFrame(header=header)]),
                metadata=client.metadata, timeout=30))
        error('NOT_FOUND', lambda: client.stat('/interrupted'))
        node = cluster.nodes[cluster.node_ids.index(block.locations[0].node_id)]
        node.stop()
        node.start()
        cluster.wait_ready(3, client)
        error('OPERATION_EXPIRED', lambda: client.call(client.uploads.RenewUpload, ctl.OperationRequest(operation=plan.operation)))
        assert sum(x.reserved_bytes for x in cluster.statuses(client).nodes) == 0
        # Expiration is injected in authoritative metadata; authorization itself still uses real RPC.
        plan, block = allocation(client, '/expired', b'abcdef')
        db = SQLiteMetadataStore(cluster.control.directory / 'metadata.sqlite3')
        with db.transaction(True) as tx:
            op = tx.get('upload', plan.operation.operation_id)
            op['expires'] = 1
            tx.put('upload', op)
        header = client.prepare(d.PutBlockHeader(operation=plan.operation, fence=plan.fence, block=block.block,
            capability=block.grants[0].capability))
        with channel(block.locations[0].client_endpoint, cluster.certs) as connection:
            error('OPERATION_EXPIRED', lambda: dg.BlockServiceStub(connection).PutBlock(iter([d.PutBlockFrame(header=header)]),
                metadata=client.metadata, timeout=30))
        source = cluster.directory / 'original'
        source.write_bytes(b'old visible version')
        client.send(source, '/atomic')
        source.write_bytes(b'new must not become visible')
        (cluster.faults / 'before_publish').touch()
        from dfsha.common.domain import Fault
        with pytest.raises(Fault, match='OUTCOME_UNKNOWN'):
            client.send(source, '/atomic', overwrite=True)
        assert cluster.control.process.wait(timeout=10) == 93
        cluster.control.stop()
        cluster.control.start()
        cluster.wait_ready(3, client)
        client.receive('/atomic', cluster.directory / 'atomic-output')
        assert (cluster.directory / 'atomic-output').read_bytes() == b'old visible version'
    finally:
        client.shutdown()


def test_control_outage_node_space_keys_and_forged_receipts(cluster):
    import grpc
    import tomllib
    from dfsha.common import node_rpc
    from dfsha.common.rpc import channel
    from dfsha.common.domain import intent
    from dfsha.v1 import data_pb2 as d, data_pb2_grpc as dg
    from test_hito1 import error
    client = cluster.client()
    try:
        source = cluster.directory / 'saved'
        source.write_bytes(b'one durable copy')
        client.send(source, '/saved')
        handle = client.open_read('/saved')
        block = resolve(client, handle).blocks[0]
        request = client.prepare(d.GetBlockRequest(handle_id=handle.handle_id, snapshot=handle.snapshot,
            block=block.block, length=block.block.size_bytes, capability=block.grants[0].capability))
        with channel(cluster.target, cluster.certs) as connection:
            error('NOT_IMPLEMENTED_STAGE2', lambda: list(dg.BlockServiceStub(connection).GetBlock(request,
                metadata=client.metadata, timeout=30)))
        cluster.control.stop()
        with channel(block.locations[0].client_endpoint, cluster.certs) as connection:
            with pytest.raises(grpc.RpcError) as failure:
                list(dg.BlockServiceStub(connection).GetBlock(request, metadata=client.metadata, timeout=30))
            assert failure.value.code() in (grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED)
        cluster.control.start()
        cluster.wait_ready(3, client)
        assert client.receive_handle(handle, cluster.directory / 'restored-control')['bytes'] == len(source.read_bytes())
        client.close(handle)

        # Inject an ENOSPC-equivalent rejection at the DN, after a valid control reservation.
        plan, planned = allocation(client, '/no-space-at-node', b'abc')
        node = cluster.nodes[cluster.node_ids.index(planned.locations[0].node_id)]
        (node.directory / 'faults/no_space').touch()
        header = client.prepare(d.PutBlockHeader(operation=plan.operation, fence=plan.fence, block=planned.block,
            capability=planned.grants[0].capability))
        with channel(planned.locations[0].client_endpoint, cluster.certs) as connection:
            error('NO_SPACE', lambda: dg.BlockServiceStub(connection).PutBlock(iter([d.PutBlockFrame(header=header),
                d.PutBlockFrame(chunk=d.DataChunk(data=b'abc'))]), metadata=client.metadata, timeout=30))
        client.call(client.uploads.AbortUpload, ctl.OperationRequest(operation=plan.operation))
        error('NOT_FOUND', lambda: client.stat('/no-space-at-node'))
        assert sum(x.reserved_bytes for x in cluster.statuses(client).nodes) == 0
        cfg = tomllib.loads(node.config.read_text())['datanode']
        with node_rpc.channel(cluster.internal, cfg) as connection:
            registry = ng.NodeRegistryServiceStub(connection)
            # Correct certificate, but old incarnation and an invented receipt of an aborted upload.
            error('VERSION_CONFLICT', lambda: registry.Heartbeat(n.HeartbeatRequest(context=node_rpc.context_for(cfg),
                node_id=node.info['node_id'], boot_generation=0, sequence=999999), timeout=5))
            receipt = c.DurableReceipt(receipt_id=str(uuid4()), operation_id=plan.operation.operation_id,
                block=planned.block, node_id=node.info['node_id'], boot_generation=node.info['generation'],
                failure_domain='local-host', stored_size_bytes=1000, ciphertext_sha256=b'a'*32)
            error('OPERATION_EXPIRED', lambda: registry.ReportDurable(n.ReportDurableRequest(context=node_rpc.context_for(cfg),
                client_context=header.context, receipt=receipt, operation=plan.operation, fence=plan.fence), timeout=5))
        key = Path(cfg['key_path'])
        original = key.read_bytes()
        node.stop()
        key.unlink()
        try:
            with pytest.raises(RuntimeError, match='MASTER_KEY_MISSING_OR_INVALID'):
                node.start()
            assert not key.exists()
            key.write_bytes(b'z'*32)
            with pytest.raises(RuntimeError, match='MASTER_KEY_MISMATCH'):
                node.start()
        finally:
            key.write_bytes(original)
        node.start()
        cluster.wait_ready(3, client)
        assert client.receive('/saved', cluster.directory / 'after-key-recovery')['bytes'] == len(source.read_bytes())
    finally:
        client.shutdown()
