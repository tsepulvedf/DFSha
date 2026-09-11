"""Laboratorio local E4: procesos y volúmenes distintos; nunca copias de bloques por filesystem."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from uuid import uuid4
from runtime import ROOT, PROCESS_FLAGS, free_port, wait_until
from generate_certs import generate
from dfsha.control.auth import initialize, protect
from dfsha.control.metadata import SQLiteMetadataStore
from dfsha.client.sdk import Client
from dfsha.v1 import nodes_pb2 as n, nodes_pb2_grpc as ng


def write_toml(path, section, values):
    path.write_text('[' + section + ']\n' + '\n'.join(k + ' = ' + json.dumps(v) for k, v in values.items()) + '\n', encoding='utf-8')


class Process:
    def __init__(self, directory, config, module):
        self.directory, self.config, self.module = directory, config, module
        directory.mkdir(parents=True, exist_ok=True)
        self.ready, self.stop_file = directory / 'ready.json', directory / 'stop'
        self.process = None

    def start(self):
        self.ready.unlink(missing_ok=True)
        self.stop_file.unlink(missing_ok=True)
        self.log = (self.directory / 'server.log').open('ab')
        self.process = subprocess.Popen([sys.executable, '-m', self.module, '--config', str(self.config),
            '--ready-file', str(self.ready), '--stop-file', str(self.stop_file)], cwd=ROOT,
            stdout=self.log, stderr=subprocess.STDOUT, creationflags=PROCESS_FLAGS)
        def ready():
            if self.process.poll() is not None:
                self.log.close()
                raise RuntimeError((self.directory / 'server.log').read_text(encoding='utf-8'))
            if self.ready.exists():
                try:
                    return json.loads(self.ready.read_text(encoding='utf-8'))
                except json.JSONDecodeError:
                    pass
        self.info = wait_until(ready, seconds=30)
        return self

    def stop(self):
        if self.process and self.process.poll() is None:
            self.stop_file.touch()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)
        if hasattr(self, 'log'):
            self.log.close()


class Cluster:
    def __init__(self, directory, block_size=4194304, capacities=None, rf3=False, lease_seconds=30):
        self.directory = Path(directory).resolve()
        if self.directory.exists() and any(self.directory.iterdir()):
            raise ValueError('Use una raíz nueva; no se convierte ni sobrescribe H1')
        self.directory.mkdir(parents=True, exist_ok=True)
        protect(self.directory)
        self.certs = self.directory / 'certificates'
        self.control_id = str(uuid4())
        self.node_ids = [str(uuid4()) for _ in range(4)]
        generate(self.certs, [self.control_id] + self.node_ids)
        # Provision only the authorized identity to each process; never expose the CA key to a server.
        import shutil
        authority = self.certs
        trust = self.directory / 'client-trust'
        trust.mkdir()
        shutil.copyfile(authority / 'ca.crt', trust / 'ca.crt')
        self.authority, self.certs = authority, trust
        identity_dirs = {}
        for identity in [self.control_id] + self.node_ids:
            target = self.directory / 'identities' / identity
            target.mkdir(parents=True)
            protect(target)
            for filename in ('ca.crt', identity + '.crt', identity + '.key'):
                shutil.copyfile(authority / filename, target / filename)
            identity_dirs[identity] = target
        self.target = f'localhost:{free_port()}'
        self.internal = f'localhost:{free_port()}'
        self.capacities = capacities or [17179869184]*4
        self.allowed = {}
        for identity, capacity in zip(self.node_ids, self.capacities):
            self.allowed[identity] = dict(identity=identity, client_endpoint=f'localhost:{free_port()}',
                private_endpoint=f'localhost:{free_port()}', failure_domain='local-host', capacity_bytes=capacity)
        allowed_path = self.directory / 'authorized-nodes.json'
        allowed_path.write_text(json.dumps(self.allowed, indent=2), encoding='utf-8')
        directory = self.directory / 'control'
        directory.mkdir()
        config = directory / 'config.toml'
        template = (ROOT / 'deploy/monolith.example.toml').read_text(encoding='utf-8')
        template = template.replace('[monolith]', '[distributed]').replace('.runtime/certs', identity_dirs[self.control_id].as_posix()).replace(
            '.runtime/hito1', directory.as_posix()).replace('127.0.0.1:17443', self.target.replace('localhost', '127.0.0.1')).replace(
            '127.0.0.1:17445', self.internal.replace('localhost', '127.0.0.1')).replace('localhost:17443', self.target).replace(
            'block_size_bytes = 4194304', f'block_size_bytes = {block_size}')
        template = template.replace('[server]', '[server]\ncertificate_identity = ' + json.dumps(self.control_id))
        if rf3:
            template = template.replace('[distributed]', '[distributed]\nrf3_enabled = true\nlock_lease_seconds = ' + str(lease_seconds))
        self.faults = directory / 'faults'
        self.faults.mkdir()
        template = template.replace('[client]', 'authorized_nodes_path = ' + json.dumps(allowed_path.as_posix()) +
            '\ntest_fault_dir = ' + json.dumps(self.faults.as_posix()) + '\nsuspect_ms = 2500\nunavailable_ms = 6000\n\n[client]')
        config.write_text(template, encoding='utf-8')
        parsed = tomllib.loads(template)
        initialize({**parsed['server'], **parsed['distributed']}, 'admin', 'development-password')
        with SQLiteMetadataStore(parsed['server']['sqlite_path']).transaction() as tx:
            self.epoch = tx.get('settings', 'system')['epoch']
        self.control = Process(directory, config, 'dfsha.control.server')
        self.nodes = []
        content_key = os.urandom(32)
        import hashlib
        for index, identity in enumerate(self.node_ids):
            directory = self.directory / f'datanode-{index+1}'
            directory.mkdir()
            secret = self.directory / 'secrets' / identity
            secret.mkdir(parents=True)
            protect(secret)
            key_path = secret / 'content.key'
            key_path.write_bytes(content_key)
            protect(key_path)
            metadata = SQLiteMetadataStore(directory / 'inventory.sqlite3')
            metadata.initialize()
            with metadata.transaction(True) as tx:
                tx.put('settings', dict(id='node', id_node=identity, key_sha256=hashlib.sha256(content_key).hexdigest(), generation=0))
            allow = self.allowed[identity]
            cfg = dict(certificate_dir=identity_dirs[identity].as_posix(), certificate_identity=identity, control_identity=self.control_id,
                service_epoch=self.epoch, control_internal_target=self.internal, capacity_bytes=allow['capacity_bytes'],
                client_endpoint=allow['client_endpoint'], private_endpoint=allow['private_endpoint'], failure_domain=allow['failure_domain'],
                public_bind=allow['client_endpoint'].replace('localhost', '127.0.0.1'), internal_bind=allow['private_endpoint'].replace('localhost', '127.0.0.1'),
                sqlite_path=metadata.path.as_posix(), key_path=key_path.as_posix(), block_path=(directory / 'blocks').as_posix(), heartbeat_seconds=.5)
            config = directory / 'config.toml'
            faults = directory / 'faults'
            faults.mkdir()
            cfg['test_fault_dir'] = faults.as_posix()
            cfg['rf3_enabled'] = rf3
            write_toml(config, 'datanode', cfg)
            self.nodes.append(Process(directory, config, 'dfsha.datanode.server'))
        (self.directory / 'lab.json').write_text(json.dumps(dict(control_id=self.control_id, node_ids=self.node_ids,
            target=self.target, internal=self.internal, epoch=self.epoch), indent=2), encoding='utf-8')
        write_toml(self.directory / 'client.toml', 'client', dict(public_target=self.target, certificate_dir=self.certs.as_posix()))

    @classmethod
    def load(cls, directory):
        app = cls.__new__(cls)
        app.directory = Path(directory).resolve()
        record = json.loads((app.directory / 'lab.json').read_text(encoding='utf-8'))
        app.__dict__.update(record)
        app.certs, app.authority = app.directory / 'client-trust', app.directory / 'certificates'
        app.control = Process(app.directory / 'control', app.directory / 'control/config.toml', 'dfsha.control.server')
        app.nodes = [Process(app.directory / f'datanode-{i}', app.directory / f'datanode-{i}/config.toml',
                     'dfsha.datanode.server') for i in range(1, 5)]
        return app

    def client(self):
        client = Client(self.target, self.certs)
        client.login('admin', 'development-password')
        return client

    def statuses(self, client):
        return client.call(ng.ClusterAdministrationServiceStub(client.channel).ListNodes, n.ClusterQuery())

    def wait_ready(self, count, client):
        def ready():
            value = self.statuses(client)
            active = [p for p in self.nodes if p.process and p.process.poll() is None]
            current = {x.node.node_id: x for x in value.nodes}
            if len(active) == count and all(p.info['node_id'] in current and
                current[p.info['node_id']].state == 'READY' and
                current[p.info['node_id']].node.boot_generation == p.info['generation'] for p in active):
                return value
        return wait_until(ready, seconds=45)

    def start(self):
        self.control.start()
        for node in self.nodes[:3]:
            node.start()
        client = self.client()
        try:
            self.wait_ready(3, client)
        finally:
            client.shutdown()
        return self

    def stop(self):
        for node in self.nodes:
            node.stop()
        self.control.stop()

    def __enter__(self):
        try:
            return self.start()
        except BaseException:
            self.stop()
            raise

    def __exit__(self, *args):
        self.stop()
