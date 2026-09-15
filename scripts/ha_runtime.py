"""Procesos etcd propios, tres miembros del mismo clúster y TLS en clientes/peers."""
import json
import os
from pathlib import Path
import subprocess
from uuid import uuid4

from generate_certs import generate
from hito2_runtime import Cluster, Process, write_toml
from runtime import ROOT, PROCESS_FLAGS, free_port, wait_until
from dfsha.common.etcd_probe_client import EtcdProbeClient, prefix_end
from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb, rpc_pb2_grpc as api
from dfsha._vendor.etcd.api.authpb import auth_pb2 as auth


class EtcdMember:
    def __init__(self, directory, args, target):
        self.directory, self.args, self.target = directory, args, target
        self.process = None

    def start(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        self.log = (self.directory/'etcd.log').open('ab')
        self.process = subprocess.Popen(self.args, cwd=ROOT, stdout=self.log, stderr=subprocess.STDOUT,
            creationflags=PROCESS_FLAGS)

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=15)
        if hasattr(self, 'log'):
            self.log.close()


class EtcdCluster:
    def __init__(self, directory, certs=None, identities=()):
        self.directory = Path(directory).resolve()
        self.directory.mkdir(parents=True, exist_ok=True)
        self.prefix = '/dfsha/ha/'+str(uuid4())
        self.token = 'dfsha-e7-'+str(uuid4())
        self.certs = Path(certs) if certs else self.directory/'certificates'
        self.identities = list(identities) or ['dfsha-probe']
        if not certs:
            generate(self.certs)
        binary = ROOT/'.tools/etcd-3.6.14'/('windows-amd64/etcd.exe' if os.name == 'nt' else 'linux-amd64/etcd')
        if not binary.is_file():
            raise FileNotFoundError('Ejecute scripts/fetch_etcd.py con la plataforma correspondiente')
        ports = set()
        while len(ports) < 6:
            ports.add(free_port())
        ports = list(ports)
        self.targets = [f'127.0.0.1:{p}' for p in ports[:3]]
        peers = [f'https://127.0.0.1:{p}' for p in ports[3:]]
        initial = ','.join(f'm{i}={peers[i]}' for i in range(3))
        self.members = []
        for i in range(3):
            directory = self.directory/f'm{i}'
            args = [str(binary), f'--name=m{i}', f'--data-dir={directory / "data"}',
                f'--listen-client-urls=https://{self.targets[i]}', f'--advertise-client-urls=https://{self.targets[i]}',
                f'--listen-peer-urls={peers[i]}', f'--initial-advertise-peer-urls={peers[i]}',
                f'--initial-cluster={initial}', f'--initial-cluster-token={self.token}', '--initial-cluster-state=new',
                f'--cert-file={self.certs / "etcd-server.crt"}', f'--key-file={self.certs / "etcd-server.key"}',
                f'--trusted-ca-file={self.certs / "ca.crt"}', '--client-cert-auth=true',
                f'--peer-cert-file={self.certs / "etcd-server.crt"}', f'--peer-key-file={self.certs / "etcd-server.key"}',
                f'--peer-trusted-ca-file={self.certs / "ca.crt"}', '--peer-client-cert-auth=true',
                '--quota-backend-bytes=1073741824', '--max-request-bytes=1572864', '--max-txn-ops=128',
                '--enable-grpc-gateway=false', '--log-level=warn']
            self.members.append(EtcdMember(directory, args, self.targets[i]))

    def status(self):
        results = []
        for member in self.members:
            with EtcdProbeClient(member.target, self.certs, 'etcd-root') as admin:
                status = api.MaintenanceStub(admin.channel).Status(pb.StatusRequest(), timeout=2)
                listing = api.ClusterStub(admin.channel).MemberList(pb.MemberListRequest(), timeout=2)
                results.append(dict(member=status.header.member_id, cluster=status.header.cluster_id,
                    leader=status.leader, revision=status.header.revision, members=[m.ID for m in listing.members],
                    endpoint=member.target, pid=member.process.pid))
        assert len({x['cluster'] for x in results}) == 1
        assert len({x['member'] for x in results}) == 3
        assert all(len(x['members']) == 3 for x in results)
        return results

    def configure_auth(self):
        with EtcdProbeClient(self.targets[0], self.certs, 'etcd-root') as admin:
            admin.auth.UserAdd(pb.AuthUserAddRequest(name='root', options=auth.UserAddOptions(no_password=True)), timeout=3)
            admin.auth.UserGrantRole(pb.AuthUserGrantRoleRequest(user='root', role='root'), timeout=3)
            admin.auth.RoleAdd(pb.AuthRoleAddRequest(name='dfsha-ha'), timeout=3)
            prefix = (self.prefix+'/').encode()
            admin.auth.RoleGrantPermission(pb.AuthRoleGrantPermissionRequest(name='dfsha-ha', perm=auth.Permission(
                permType=auth.Permission.READWRITE, key=prefix, range_end=prefix_end(prefix))), timeout=3)
            for identity in self.identities:
                admin.auth.UserAdd(pb.AuthUserAddRequest(name=identity, options=auth.UserAddOptions(no_password=True)), timeout=3)
                admin.auth.UserGrantRole(pb.AuthUserGrantRoleRequest(user=identity, role='dfsha-ha'), timeout=3)
            admin.auth.AuthEnable(pb.AuthEnableRequest(), timeout=3)

    def config(self, identity='etcd-probe'):
        return dict(etcd_prefix=self.prefix, etcd_endpoints=self.targets,
            etcd_certificate_dir=str(self.certs), etcd_identity=identity)

    def __enter__(self):
        try:
            for member in self.members:
                member.start()
            def ready():
                try:
                    return self.status()
                except Exception:
                    if any(m.process.poll() is not None for m in self.members):
                        raise RuntimeError('Un miembro etcd terminó; consultar logs del laboratorio')
                    return None
            self.membership = wait_until(ready, seconds=30)
            if not getattr(self, 'restored', False):
                self.configure_auth()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *args):
        for member in reversed(self.members):
            member.stop()


class HACluster(Cluster):
    def __init__(self, directory, block_size=4194304, lease_seconds=30, capacities=None):
        super().__init__(directory, block_size=block_size, lease_seconds=lease_seconds,
            replication=True, extra_controls=2, capacities=capacities)
        self.etcd = EtcdCluster(self.directory/'etcd', self.authority, self.control_ids)
        self.controls = [self.control]
        self.proxies = []
        self.public_targets = [self.target]+[f'localhost:{free_port()}' for _ in range(2)]
        self.internal_targets = [self.internal]+[f'localhost:{free_port()}' for _ in range(2)]

    def activate(self):
        import shutil
        import tomllib
        from dfsha.control.etcd_metadata import EtcdMetadataStore
        from dfsha.control.migration import migrate
        original = tomllib.loads(self.control.config.read_text(encoding='utf-8'))
        cfg = self.etcd.config(self.control_id)
        cfg['etcd_certificate_dir'] = str(self.directory/'identities'/self.control_id)
        store = EtcdMetadataStore(cfg)
        try:
            self.migration = migrate(original['server']['sqlite_path'], self.directory/'migration'/'sqlite-backup.sqlite3', store)
        finally:
            store.channel.close()
        self.epoch = self.migration['epoch']
        for index, identity in enumerate(self.control_ids):
            directory = self.control.directory if index == 0 else self.directory/f'control-{index+1}'
            directory.mkdir(parents=True, exist_ok=True)
            server, distributed = dict(original['server']), dict(original['distributed'])
            server.update(metadata_backend='etcd', certificate_identity=identity,
                certificate_dir=(self.directory/'identities'/identity).as_posix(),
                public_bind=self.public_targets[index].replace('localhost', '127.0.0.1'),
                internal_bind=self.internal_targets[index].replace('localhost', '127.0.0.1'))
            if index:
                secrets = self.directory/'secrets'/identity
                secrets.mkdir(parents=True)
                shutil.copyfile(distributed['key_path'], secrets/'metadata.key')
                distributed['key_path'] = (secrets/'metadata.key').as_posix()
                server['sqlite_path'] = (directory/'auxiliary.sqlite3').as_posix()
            distributed.update(cfg, etcd_identity=identity, service_epoch=self.epoch,
                control_rpc_timeout_seconds=15, metadata_gate_wait_seconds=8,
                metadata_trace_timing=True,
                metadata_gate_lease_seconds=30, unavailable_ms=30000, suspect_ms=12000,
                etcd_certificate_dir=(self.directory/'identities'/identity).as_posix())
            from fault_proxy import FaultProxy
            proxies = [FaultProxy(target) for target in self.etcd.targets]
            self.proxies.append(proxies)
            distributed['etcd_endpoints'] = [p.endpoint for p in proxies]
            # Each control has a separate fault directory; shared data faults remain explicit fixtures.
            fault_dir = directory/'faults'
            fault_dir.mkdir(exist_ok=True)
            distributed['test_fault_dir'] = fault_dir.as_posix()
            config = directory/'config.toml'
            config.write_text('\n'.join('['+section+']\n'+'\n'.join(k+' = '+json.dumps(v) for k,v in values.items())
                for section, values in [('server', server), ('distributed', distributed)]), encoding='utf-8')
            if index:
                self.controls.append(Process(directory, config, 'dfsha.control.server'))
        for node in self.nodes:
            config = tomllib.loads(node.config.read_text(encoding='utf-8'))['datanode']
            config.update(service_epoch=self.epoch, control_internal_targets=self.internal_targets,
                control_identities=self.control_ids, control_rpc_timeout_seconds=15, heartbeat_seconds=3)
            write_toml(node.config, 'datanode', config)
        write_toml(self.directory/'client.toml', 'client', dict(public_targets=self.public_targets,
            certificate_dir=self.certs.as_posix()))

    def client(self, index=None, session=None):
        from dfsha.client.sdk import Client
        client = Client(self.public_targets if index is None else [self.public_targets[index]], self.certs, session)
        if session is None:
            client.login('admin', 'development-password')
        return client

    def metadata(self):
        from dfsha.control.etcd_metadata import EtcdMetadataStore
        cfg = self.etcd.config(self.control_id)
        cfg['etcd_certificate_dir'] = str(self.directory/'identities'/self.control_id)
        return EtcdMetadataStore(cfg)

    def seed_e6(self, callback):
        """Create real E6 data in this NEW laboratory before offline migration."""
        from dfsha.client.sdk import Client
        self.control.start()
        client = Client(self.target, self.certs)
        try:
            for node in self.nodes[:3]:
                node.start()
            client.login('admin', 'development-password')
            self.wait_ready(3, client)
            return callback(self, client)
        finally:
            client.shutdown()
            for node in reversed(self.nodes):
                node.stop()
            self.control.stop()

    def __enter__(self):
        try:
            self.etcd.__enter__()
            self.activate()
            for process in self.controls:
                process.start()
            for process in self.nodes[:3]:
                process.start()
            client = self.client()
            try:
                self.wait_ready(3, client)
            finally:
                client.shutdown()
            return self
        except BaseException:
            self.__exit__()
            raise

    def __exit__(self, *args):
        for process in reversed(self.nodes):
            process.stop()
        for process in reversed(self.controls):
            process.stop()
        for group in self.proxies:
            for proxy in group:
                proxy.close()
        self.etcd.__exit__()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    args = parser.parse_args()
    with EtcdCluster(ROOT/'.runtime/etcd-e7'/str(uuid4())) as cluster:
        result = dict(status='EJECUTADO', membership=cluster.status(), profile='process-simulation',
            version='3.6.14', prefix=cluster.prefix, client_mtls=True, peer_mtls=True)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result))
