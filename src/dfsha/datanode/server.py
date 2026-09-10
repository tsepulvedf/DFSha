"""Proceso DataNode E4, TLS público y mTLS privado, cierre y disponibilidad explícitos."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import threading
import tomllib
import grpc
from dfsha.common.config import loopback_address
from dfsha.common.limits import GRPC_OPTIONS
from dfsha.common import node_rpc
from dfsha.common.telemetry import configure, event
from dfsha.control.pending import register as pending
from dfsha.datanode.service import DataNode


def serve(path, ready_file, stop_file):
    cfg = tomllib.loads(path.read_text(encoding='utf-8'))['datanode']
    app = DataNode(cfg)
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    servers, pools = [], []
    try:
        for internal in (False, True):
            pool = ThreadPoolExecutor(max_workers=12)
            pools.append(pool)
            server = grpc.server(pool, options=GRPC_OPTIONS, maximum_concurrent_rpcs=24)
            certs = Path(cfg['certificate_dir'])
            identity = cfg['certificate_identity']
            creds = grpc.ssl_server_credentials([((certs / (identity + '.key')).read_bytes(),
                (certs / (identity + '.crt')).read_bytes())], root_certificates=(certs / 'ca.crt').read_bytes() if internal else None,
                require_client_auth=internal)
            port = server.add_secure_port(loopback_address(cfg['internal_bind' if internal else 'public_bind']), creds)
            if not port:
                raise RuntimeError('LISTENER_UNAVAILABLE')
            implemented = node_rpc.register(server, app, [('nodes', 'StorageAdministrationService'), ('data', 'ReplicaService')]
                if internal else [('data', 'BlockService')])
            pending(server, internal, implemented)
            server.start()
            servers.append(server)
        app.start()
        ready_file.write_text(json.dumps(dict(pid=os.getpid(), node_id=app.node_id, generation=app.generation,
            public_target=cfg['client_endpoint'], internal_target=cfg['private_endpoint'])), encoding='utf-8')
        while not stop.wait(.1):
            if stop_file.exists():
                stop.set()
    finally:
        for server in servers:
            server.stop(3).wait(4)
        for pool in pools:
            pool.shutdown(wait=True, cancel_futures=True)
        app.close()
        ready_file.unlink(missing_ok=True)
        event('datanode_stopped', pid=os.getpid())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--ready-file', type=Path, required=True)
    parser.add_argument('--stop-file', type=Path, required=True)
    args = parser.parse_args()
    configure()
    serve(args.config, args.ready_file, args.stop_file)


if __name__ == '__main__':
    main()
