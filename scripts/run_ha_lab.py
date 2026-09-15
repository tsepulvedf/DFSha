"""Laboratorio HA persistente local: ejecutar, reanudar y detener sin recrear datos."""
import argparse
import json
from pathlib import Path
import threading
import tomllib
from ha_runtime import HACluster, EtcdCluster, EtcdMember
from hito2_runtime import Process
from fault_proxy import FaultProxy


def save(lab):
    record = {key: getattr(lab, key) for key in ('control_ids', 'node_ids', 'public_targets',
        'internal_targets', 'epoch', 'migration')}
    record['etcd'] = dict(prefix=lab.etcd.prefix, token=lab.etcd.token,
        members=[dict(directory=m.directory.name, args=m.args, target=m.target) for m in lab.etcd.members])
    record['controls'] = [p.directory.name for p in lab.controls]
    record['nodes'] = [p.directory.name for p in lab.nodes]
    (lab.directory/'ha-lab.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')


class ExistingHACluster(HACluster):
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        record = json.loads((self.directory/'ha-lab.json').read_text(encoding='utf-8'))
        for key in ('control_ids', 'node_ids', 'public_targets', 'internal_targets', 'epoch', 'migration'):
            setattr(self, key, record[key])
        self.control_id = self.control_ids[0]
        self.target, self.internal = self.public_targets[0], self.internal_targets[0]
        self.certs, self.authority = self.directory/'client-trust', self.directory/'certificates'
        self.controls = [Process(self.directory/name, self.directory/name/'config.toml', 'dfsha.control.server') for name in record['controls']]
        self.nodes = [Process(self.directory/name, self.directory/name/'config.toml', 'dfsha.datanode.server') for name in record['nodes']]
        self.control = self.controls[0]
        self.proxies = []
        self.etcd = EtcdCluster.__new__(EtcdCluster)
        self.etcd.directory, self.etcd.certs = self.directory/'etcd', self.authority
        self.etcd.prefix, self.etcd.token = record['etcd']['prefix'], record['etcd']['token']
        self.etcd.identities, self.etcd.restored = self.control_ids, True  # Existing auth configuration.
        self.etcd.members = [EtcdMember(self.etcd.directory/m['directory'], m['args'], m['target']) for m in record['etcd']['members']]
        self.etcd.targets = [m.target for m in self.etcd.members]

    def activate(self):
        for process in self.controls:
            cfg = tomllib.loads(process.config.read_text(encoding='utf-8'))
            group = [FaultProxy(target) for target in self.etcd.targets]
            self.proxies.append(group)
            cfg['distributed']['etcd_endpoints'] = [p.endpoint for p in group]
            process.config.write_text('\n'.join('['+section+']\n'+'\n'.join(k+' = '+json.dumps(v)
                for k,v in values.items()) for section,values in cfg.items()), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--resume', action='store_true')
    mode.add_argument('--restore-from', type=Path, help='Bundle privado; restaurar en una raíz nueva')
    parser.add_argument('--backup-on-stop', type=Path, help='Bundle nuevo; respaldo offline al recibir stop-ha')
    parser.add_argument('--block-size', type=int, choices=(4194304, 67108864, 134217728), default=4194304)
    args = parser.parse_args()
    directory = args.directory.resolve()
    if args.restore_from:
        from ha_recovery import RestoredHACluster
        lab = RestoredHACluster(args.restore_from, directory)
    else:
        lab = ExistingHACluster(directory) if args.resume else HACluster(directory, block_size=args.block_size)
    stop, ready = directory/'stop-ha', directory/'ready-ha.json'
    stop.unlink(missing_ok=True)
    ready.unlink(missing_ok=True)
    try:
        with lab:
            save(lab)
            status = dict(status='READY', client_config=str(directory/'client.toml'),
                controls=[p.info for p in lab.controls], members=lab.etcd.status(),
                nodes=[p.info for p in lab.nodes[:3]], epoch=lab.epoch)
            ready.write_text(json.dumps(status, indent=2)+'\n', encoding='utf-8')
            print(json.dumps(status), flush=True)
            wait = threading.Event()
            while not stop.exists():
                wait.wait(.2)
            if args.backup_on_stop:
                from ha_recovery import backup_lab
                print(json.dumps(backup_lab(lab, args.backup_on_stop)), flush=True)
    finally:
        ready.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
