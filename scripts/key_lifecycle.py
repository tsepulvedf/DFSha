"""Custodia de claves del laboratorio: provisión, comprobación mTLS y activación por fases."""
import hashlib
import json
import os
from pathlib import Path
import struct
import tomllib

from dfsha.common import node_rpc
from dfsha.common.domain import need
from dfsha.control.auth import protect
from dfsha.datanode.blocks import MAGIC
from dfsha.v1 import nodes_pb2 as n, nodes_pb2_grpc as ng
from hito2_runtime import write_toml


def key_status(lab, node):
    cfg = tomllib.loads(lab.controls[0].config.read_text(encoding='utf-8'))
    identity = dict(**cfg['server'])
    identity['service_epoch'] = lab.epoch
    destination = tomllib.loads(node.config.read_text(encoding='utf-8'))['datanode']
    with node_rpc.channel(destination['private_endpoint'], identity) as channel:
        return ng.StorageAdministrationServiceStub(channel).GetKeyStatus(
            n.KeyStatusRequest(context=node_rpc.context_for(identity)), timeout=15)


def provision(lab, key):
    need(len(key) == 32)
    identity = hashlib.sha256(key).hexdigest()
    for node in lab.nodes:
        cfg = tomllib.loads(node.config.read_text(encoding='utf-8'))['datanode']
        path = Path(cfg['key_path']).parent/(identity+'.key')
        if path.exists():
            need(path.read_bytes() == key, 'DATA_LOSS')
        else:
            with path.open('xb') as out:
                out.write(key)
                out.flush()
                os.fsync(out.fileno())
            protect(path)
        cfg['content_read_key_paths'] = sorted(set(cfg.get('content_read_key_paths', [])) | {path.as_posix()})
        write_toml(node.config, 'datanode', cfg)
    return identity


def activate(lab, key_id):
    active = [node for node in lab.nodes if node.process and node.process.poll() is None]
    need(len(active) >= 3, 'DATA_UNAVAILABLE')
    # A file on disk is not evidence that a running process loaded the key.
    need(all(key_id in key_status(lab, node).readable_key_ids for node in active), 'DATA_UNAVAILABLE')
    for node in lab.nodes:
        cfg = tomllib.loads(node.config.read_text(encoding='utf-8'))['datanode']
        path = Path(cfg['key_path']).parent/(key_id+'.key')
        need(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == key_id, 'DATA_LOSS')
        cfg['content_active_key_path'] = path.as_posix()
        write_toml(node.config, 'datanode', cfg)


def required_object_keys(roots):
    result = set()
    for root in roots:
        root = Path(root).resolve()
        need(root.is_dir(), 'DATA_UNAVAILABLE')
        for path in root.rglob('*.blk'):
            need(path.resolve().is_relative_to(root), 'PERMISSION_DENIED')
            with path.open('rb') as stream:
                need(stream.read(8) == MAGIC, 'DATA_LOSS')
                raw = stream.read(4)
                need(len(raw) == 4, 'DATA_LOSS')
                size = struct.unpack('>I', raw)[0]
                need(0 < size <= 4096, 'DATA_LOSS')
                result.add(json.loads(stream.read(size))['key_id'])
    return result


def check_retirement(lab, key_id, retained_backups=()):
    """Conservative offline guard. Does not erase keys or weaken the bootstrap key anchor."""
    need(all(not p.process or p.process.poll() is not None for p in lab.controls+lab.nodes), 'LOCK_BUSY')
    roots = [Path(tomllib.loads(p.config.read_text(encoding='utf-8'))['datanode']['block_path']) for p in lab.nodes]
    # A retained backup may need any former key. Without a verified dependency
    # inventory, fail closed rather than interpreting an absent live object as proof.
    need(not retained_backups and key_id not in required_object_keys(roots), 'LOCK_BUSY')
    for p in lab.nodes:
        cfg = tomllib.loads(p.config.read_text(encoding='utf-8'))['datanode']
        for anchor in ('key_path', 'content_active_key_path'):
            if cfg.get(anchor):
                need(hashlib.sha256(Path(cfg[anchor]).read_bytes()).hexdigest() != key_id, 'LOCK_BUSY')
    return dict(eligible=True, key_id=key_id, deletion_performed=False)
