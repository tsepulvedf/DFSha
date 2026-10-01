"""Laboratorio HA persistente local: ejecutar, reanudar y detener sin recrear datos."""
import argparse
import getpass
import json
from pathlib import Path
import threading
import sys
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
    record['protected'] = bool(getattr(lab, 'protected', False))
    (lab.directory/'ha-lab.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')


class ExistingHACluster(HACluster):
    def __init__(self, directory):
        self.directory = Path(directory).resolve()
        record = json.loads((self.directory/'ha-lab.json').read_text(encoding='utf-8'))
        self.protected = record.get('protected', False)
        self.metadata_key_path = self.directory/'secrets/metadata-at-rest.key'
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
    parser.add_argument('--protected', action='store_true', help='E8: new encrypted HA laboratory')
    parser.add_argument('--admin-password-stdin', action='store_true', help='Read administrative password from stdin, never from an argument')
    parser.add_argument('--archive-key-file', type=Path, help='Existing 32-byte backup key, never a password argument')
    parser.add_argument('--collect-pages-on-stop', action='store_true', help='Offline orphan-page collection after protected backup')
    parser.add_argument('--release-pin-on-stop', help='Explicit migration snapshot pin to release after backup')
    parser.add_argument('--expected-pin-digest', help='SHA-256 of the canonical snapshot record')
    args = parser.parse_args()
    archive_key = args.archive_key_file.read_bytes() if args.archive_key_file else None
    if archive_key is not None and len(archive_key) != 32:
        parser.error('Backup key must contain exactly 32 bytes')
    directory = args.directory.resolve()
    protected_credentials = args.protected or archive_key is not None
    if args.resume:
        protected_credentials |= json.loads((directory/'ha-lab.json').read_text(encoding='utf-8')).get('protected', False)
    password = (sys.stdin.readline().rstrip('\r\n') if args.admin_password_stdin else
                getpass.getpass('Contraseña administrativa vigente: ') if protected_credentials else 'development-password')
    if args.restore_from:
        from ha_recovery import RestoredHACluster
        lab = RestoredHACluster(args.restore_from, directory, archive_key=archive_key)
    else:
        lab = ExistingHACluster(directory) if args.resume else HACluster(directory, block_size=args.block_size, protected=args.protected, admin_password=password)
    lab.admin_password = password  # In memory only; never saved in ha-lab.json.
    if args.protected and not lab.protected:
        parser.error('Existing data cannot be converted implicitly to the protected profile')
    if args.backup_on_stop and lab.protected and archive_key is None:
        parser.error('Protected backup requires --archive-key-file')
    if (args.collect_pages_on_stop or args.release_pin_on_stop) and not (lab.protected and args.backup_on_stop and archive_key):
        parser.error('Retention maintenance requires protected profile and encrypted backup')
    if bool(args.release_pin_on_stop) != bool(args.expected_pin_digest):
        parser.error('Pin release requires both snapshot identity and expected digest')
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
                from ha_recovery import backup_lab, backup_protected_lab
                result = (backup_protected_lab(lab, args.backup_on_stop, archive_key) if lab.protected else
                          backup_lab(lab, args.backup_on_stop))
                print(json.dumps(result), flush=True)
                if args.release_pin_on_stop:
                    from metadata_retention import release_pin
                    print(json.dumps(release_pin(lab, args.release_pin_on_stop, args.expected_pin_digest)), flush=True)
                if args.collect_pages_on_stop:
                    from metadata_retention import collect_pages
                    print(json.dumps(collect_pages(lab)), flush=True)
    finally:
        ready.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
