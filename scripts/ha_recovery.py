"""Respaldo en mantenimiento y restauración aislada de metadatos, objetos y claves."""
import hashlib
import json
from pathlib import Path
import shutil
import tomllib
from uuid import uuid4
from dfsha.control.auth import protect
from dfsha.control.metadata import SQLiteMetadataStore
from dfsha.v1 import common_pb2 as c
from etcd_backup import snapshot, restore
from ha_runtime import HACluster, EtcdCluster
from hito2_runtime import Process


def file_hash(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def backup_lab(lab, destination):
    """Offline window: all controls and DataNodes stopped before copying files.

    This is explicitly backup I/O, never evidence of S/S replication.
    """
    destination = Path(destination).resolve()
    if destination.exists():
        raise FileExistsError(destination)
    destination.mkdir(parents=True)
    protect(destination)
    for process in reversed(lab.controls):
        process.stop()
    for process in reversed(lab.nodes):
        process.stop()
    if any(p.process and p.process.poll() is None for p in lab.controls+lab.nodes):
        raise RuntimeError('MAINTENANCE_NOT_QUIESCENT')
    payload = destination/'payload'
    payload.mkdir()
    names = ['certificates', 'client-trust', 'identities', 'secrets', 'authorized-nodes.json']
    names += [p.directory.name for p in lab.controls+lab.nodes]
    for name in names:
        source = lab.directory/name
        if source.is_dir():
            shutil.copytree(source, payload/name)
        else:
            shutil.copyfile(source, payload/name)
    status = snapshot(lab.etcd, destination/'snapshot.db')
    files = {p.relative_to(destination).as_posix(): file_hash(p) for p in destination.rglob('*') if p.is_file()}
    record = dict(schema=1, source_root=lab.directory.as_posix(), prefix=lab.etcd.prefix,
        control_ids=lab.control_ids, node_ids=lab.node_ids, public_targets=lab.public_targets,
        internal_targets=lab.internal_targets, controls=[p.directory.name for p in lab.controls],
        nodes=[p.directory.name for p in lab.nodes], files=files, snapshot=status)
    (destination/'backup.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    return dict(status='EJECUTADO', files=len(files), snapshot=status, offline=True,
        block_objects=sum(name.endswith('.blk') for name in files))


class RestoredHACluster(HACluster):
    def __init__(self, bundle, directory):
        self.bundle, self.directory = Path(bundle).resolve(), Path(directory).resolve()
        if self.directory.exists():
            raise FileExistsError(self.directory)
        record = json.loads((self.bundle/'backup.json').read_text(encoding='utf-8'))
        for name, expected in record['files'].items():
            source = (self.bundle/name).resolve()
            if not source.is_relative_to(self.bundle) or not source.is_file() or file_hash(source) != expected:
                raise RuntimeError('BACKUP_INTEGRITY_FAILED')
        self.directory.mkdir(parents=True)
        protect(self.directory)
        shutil.copytree(self.bundle/'payload', self.directory, dirs_exist_ok=True)
        self.control_ids, self.node_ids = record['control_ids'], record['node_ids']
        self.control_id = self.control_ids[0]
        self.public_targets, self.internal_targets = record['public_targets'], record['internal_targets']
        self.target, self.internal = self.public_targets[0], self.internal_targets[0]
        self.certs, self.authority = self.directory/'client-trust', self.directory/'certificates'
        self.proxies = []
        self.etcd = EtcdCluster(self.directory/'etcd', self.authority, self.control_ids)
        self.etcd.prefix = record['prefix']
        restore(self.bundle/'snapshot.db', self.etcd)
        self.controls, self.nodes = [], []
        # Ports are reused only after the documented shutdown of the original lab.
        # etcd gets new peer endpoints, membership IDs and cluster token.
        for names, processes, module in ((record['controls'], self.controls, 'dfsha.control.server'),
                                         (record['nodes'], self.nodes, 'dfsha.datanode.server')):
            for name in names:
                directory = self.directory/name
                path = directory/'config.toml'
                text = path.read_text(encoding='utf-8').replace(record['source_root'], self.directory.as_posix())
                path.write_text(text, encoding='utf-8')
                processes.append(Process(directory, path, module))
        self.control = self.controls[0]

    def activate(self):
        epoch = str(uuid4())
        store = self.metadata()
        try:
            with store.transaction(True) as tx:
                system = tx.get('settings', 'system')
                system['epoch'] = epoch
                tx.put('settings', system)
                tx.put('settings', dict(id='control-epoch', epoch=epoch, generation=1))
                tx.delete('settings', 'maintenance')
                for handle in tx.all('handle'):
                    if not handle['closed']:
                        tx.put('migration-pin', dict(id=handle['snapshot'], snapshot=handle['snapshot']))
                    tx.delete('handle', handle['id'])
                for kind in ('lock', 'read'):
                    for item in tx.all(kind):
                        tx.delete(kind, item['id'])
                for session in tx.all('session'):
                    session['revoked'] = True
                    tx.put('session', session)
                for op in tx.all('upload'):
                    if op['state'] == c.PREPARING:
                        op.update(state=c.ABORTED, reserved=0)
                        tx.put('upload', op)
                for task in tx.all('task'):
                    if task['status']['state'] in ('ACCEPTED', 'RUNNING'):
                        task.update(expires=0, reserved=0)
                        task['status']['state'] = 'FAILED'
                        tx.put('task', task)
                for node in tx.all('datanode'):
                    node.update(seen=0, reconciled=False)
                    node.pop('lease_key', None)
                    tx.pending[('datanode', node['id'])] = node
        finally:
            store.channel.close()
        self.epoch = epoch
        for process in self.controls+self.nodes:
            cfg = tomllib.loads(process.config.read_text(encoding='utf-8'))
            if process in self.controls:
                cfg['distributed'].update(self.etcd.config(cfg['server']['certificate_identity']), service_epoch=epoch,
                    etcd_certificate_dir=cfg['server']['certificate_dir'])
            else:
                cfg['datanode']['service_epoch'] = epoch
                with SQLiteMetadataStore(cfg['datanode']['sqlite_path']).transaction(True) as tx:
                    for task in tx.all('task'):
                        task['reported'] = True  # Executors from the backed-up epoch cannot resume.
                        tx.put('task', task)
            process.config.write_text('\n'.join('['+section+']\n'+'\n'.join(k+' = '+json.dumps(v)
                for k,v in values.items()) for section,values in cfg.items()), encoding='utf-8')
        self.migration = dict(status='RESTORED', epoch=epoch)
