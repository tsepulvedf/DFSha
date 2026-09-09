"""Servidor modular E2: diagnóstico TLS/mTLS; negocio pendiente y SQLite desacoplado."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import signal
import threading

import grpc

from dfsha.common.config import read_config
from dfsha.common.limits import GRPC_OPTIONS
from dfsha.common.telemetry import configure, event
from dfsha.control.diagnostic import Diagnostic
from dfsha.control.pending import register
from dfsha.v1.diagnostic_pb2_grpc import add_DiagnosticServiceServicer_to_server


def serve(config_path: Path, ready_file: Path | None = None, stop_file: Path | None = None) -> None:
    configuration = read_config(config_path)
    cfg = configuration["server"]
    app = None
    if configuration.get('monolith', {}).get('enabled'):
        from dfsha.control.monolith import Monolith
        app = Monolith({**cfg, **configuration['monolith']})
    certs = Path(cfg["certificate_dir"])
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    servers, pools = [], []
    ready = {"pid": os.getpid(), "filesystem_implemented": app is not None}
    try:
        for listener, internal in (("public", False), ("internal", True)):
            pool = ThreadPoolExecutor(max_workers=cfg["max_workers"])
            pools.append(pool)
            server = grpc.server(pool, options=GRPC_OPTIONS,
                                 maximum_concurrent_rpcs=cfg["max_concurrent_rpcs"])
            credentials = grpc.ssl_server_credentials(
                [((certs / "server.key").read_bytes(), (certs / "server.crt").read_bytes())],
                root_certificates=(certs / "ca.crt").read_bytes() if internal else None,
                require_client_auth=internal,
            )
            port = server.add_secure_port(cfg[f"{listener}_bind"], credentials)
            if not port:
                raise RuntimeError(f"No se pudo abrir listener {listener}")
            implemented = set()
            if app is not None and not internal:
                app.placement.endpoint = f'localhost:{port}'
                implemented = app.register(server)
            register(server, internal, implemented)
            add_DiagnosticServiceServicer_to_server(Diagnostic(listener, app is not None), server)
            server.start()
            servers.append(server)
            ready[f"{listener}_target"] = f"localhost:{port}"
            event("listening", listener=listener, pid=os.getpid())
        if ready_file:
            ready_file.parent.mkdir(parents=True, exist_ok=True)
            ready_file.write_text(json.dumps(ready), encoding="utf-8")
        import time
        maintenance_at = time.monotonic()
        while not stop.wait(0.1):
            if stop_file and stop_file.exists():
                stop.set()
            if app is not None and time.monotonic() - maintenance_at > 10:
                app.collect()
                maintenance_at = time.monotonic()
    finally:
        for server in servers:
            server.stop(cfg["grace_seconds"]).wait(cfg["grace_seconds"] + 1)
        for pool in pools:
            pool.shutdown(wait=True, cancel_futures=True)
        if app is not None:
            app.owner_lock.close()
        event("stopped", pid=os.getpid())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("deploy/local.example.toml"))
    parser.add_argument("--ready-file", type=Path)
    parser.add_argument("--stop-file", type=Path)
    args = parser.parse_args()
    configure()
    serve(args.config, args.ready_file, args.stop_file)


if __name__ == "__main__":
    main()
