"""Real mTLS key inventory, staged rotation, retained snapshots and node revocation."""
import hashlib
import json
import os
import tomllib

import grpc
import pytest

from dfsha.common import node_rpc
from dfsha.common.domain import Fault
from dfsha.v1 import nodes_pb2 as n, nodes_pb2_grpc as ng
from ha_runtime import HACluster
from hito2_runtime import write_toml
from issue_certificate import issue
from key_lifecycle import provision, activate, key_status, check_retirement
from measure_stage6 import full
from ha_recovery import backup_protected_lab, RestoredHACluster


def test_rotation_snapshots_and_revoked_node_existing_channel(run_dir, tmp_path, record_property):
    archive_key = os.urandom(32)
    backup = run_dir/'rotated-backup'
    with HACluster(run_dir/'keys-e8', protected=True) as lab:
        admin = lab.client()
        try:
            source = tmp_path/'old'
            source.write_bytes(b'old-version'*1000)
            admin.send(source, '/home/admin/old')
            full(admin, '/home/admin/old')
            reader = admin.open('/home/admin/old')
            old_key = key_status(lab, lab.nodes[0]).active_key_id
            with admin.keepalive(reader):
                new_key = provision(lab, os.urandom(32))
                with pytest.raises(Fault, match='DATA_UNAVAILABLE'):
                    activate(lab, new_key)  # Not loaded in the processes yet.
                for node in lab.nodes[:3]:
                    node.stop()
                    node.start()
                    lab.wait_ready(3, admin)
                assert all(new_key in key_status(lab, node).readable_key_ids for node in lab.nodes[:3])
                activate(lab, new_key)
                for node in lab.nodes[:3]:
                    node.stop()
                    node.start()
                    lab.wait_ready(3, admin)
                assert all(key_status(lab, node).active_key_id == new_key for node in lab.nodes[:3])
                source.write_bytes(b'new-version'*1000)
                admin.send(source, '/home/admin/old', overwrite=True)
                full(admin, '/home/admin/old')
                assert admin.read(reader, 0, 11) == b'old-version'
                # Leaf rotation on one control preserves the shared handle/epoch.
                cn = lab.controls[0]
                cfg = tomllib.loads(cn.config.read_text(encoding='utf-8'))
                issued = lab.directory/'identities/renewed-control'
                issue(lab.authority, issued, lab.control_ids[0])
                cfg['server']['certificate_dir'] = issued.as_posix()
                cfg['distributed']['etcd_certificate_dir'] = issued.as_posix()
                cn.stop()
                cn.config.write_text('\n'.join('['+section+']\n'+'\n'.join(k+' = '+json.dumps(v)
                    for k,v in values.items()) for section,values in cfg.items()), encoding='utf-8')
                cn.start()
                assert admin.read(reader, 0, 11) == b'old-version'
                # Existing authenticated DN channel: registration works before
                # administrative revocation and is forbidden afterwards.
                node = lab.nodes[0]
                cfg = tomllib.loads(node.config.read_text(encoding='utf-8'))['datanode']
                store = lab.metadata()
                try:
                    with store.transaction() as tx:
                        previous = tx.get('datanode', node.info['node_id'])
                finally:
                    store.channel.close()
                from dfsha.common.domain import proto
                from dfsha.v1.common_pb2 import BlockLocation
                request = n.RegisterNodeRequest(context=node_rpc.context_for(cfg),
                    node=proto(BlockLocation, previous['location']), capacity_bytes=cfg['capacity_bytes'],
                    free_bytes=previous['free'], inventory_id=previous['inventory_id'])
                with node_rpc.channel(lab.internal_targets[1], cfg) as transport:
                    stub = ng.NodeRegistryServiceStub(transport)
                    assert stub.RegisterNode(request, timeout=15).node_id == node.info['node_id']
                    update = admin.set_node_authorization(node.info['node_id'], 0, False)
                    with pytest.raises(grpc.RpcError) as error:
                        stub.RegisterNode(request, timeout=15)
                    assert error.value.code() == grpc.StatusCode.PERMISSION_DENIED
                    assert next(x for x in admin.nodes().nodes if x.node.node_id == node.info['node_id']).state == 'UNAVAILABLE'
                    admin.set_node_authorization(node.info['node_id'], update.revision, True)
                lab.wait_ready(3, admin)
                admin.receive('/home/admin/old', tmp_path/'new')
                assert (tmp_path/'new').read_bytes() == source.read_bytes()
                record_property('rotation', 'loaded on 3 processes before activation; old snapshot and new writes readable')
                record_property('node_revocation', 'same established mTLS channel rejected; eligibility removed')
                record_property('new_sha256', hashlib.sha256(source.read_bytes()).hexdigest())
            # Quiesce, retaining the reader reference. Retirement must fail closed.
            for process in lab.controls+lab.nodes:
                process.stop()
            key_files = {p: p.read_bytes() for p in (lab.directory/'secrets').rglob('*.key')}
            with pytest.raises(Fault, match='LOCK_BUSY'):
                check_retirement(lab, old_key, retained_backups=['retained-backup'])
            assert all(p.read_bytes() == data for p, data in key_files.items())
            backup_protected_lab(lab, backup, archive_key)
        finally:
            admin.shutdown()
    with RestoredHACluster(backup, run_dir/'rotated-restored', archive_key=archive_key) as restored:
        reader = restored.client()
        try:
            reader.receive('/home/admin/old', tmp_path/'restored-rotated')
            assert (tmp_path/'restored-rotated').read_bytes() == source.read_bytes()
            record_property('rotated_recovery', 'new active keys and renewed control certificate restored without the source')
        finally:
            reader.shutdown()
