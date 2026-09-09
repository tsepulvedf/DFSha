"""Procesos de prueba propios, puertos loopback y cierre acotado; no toca servicios ajenos."""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
PROCESS_FLAGS = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


def wait_until(predicate, seconds=15):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        result = predicate()
        if result:
            return result
        time.sleep(0.05)
    raise TimeoutError("El proceso de prueba no quedó disponible dentro del plazo")


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@contextmanager
def diagnostic_process(directory: Path, certs: Path):
    directory.mkdir(parents=True, exist_ok=True)
    config = (ROOT / "deploy/local.example.toml").read_text(encoding="utf-8")
    config = config.replace("127.0.0.1:17443", "127.0.0.1:0").replace("127.0.0.1:17445", "127.0.0.1:0")
    config = config.replace('".runtime/certs"', json.dumps(certs.resolve().as_posix()))
    config_path, ready, stop = directory / "config.toml", directory / "ready.json", directory / "stop"
    config_path.write_text(config, encoding="utf-8")
    with (directory / "server.log").open("wb") as log:
        process = subprocess.Popen([sys.executable, "-m", "dfsha.control.server", "--config", str(config_path),
                    "--ready-file", str(ready), "--stop-file", str(stop)], cwd=ROOT, stdout=log,
                    stderr=subprocess.STDOUT, creationflags=PROCESS_FLAGS)
        try:
            def read_ready():
                if process.poll() is not None:
                    raise RuntimeError(f"Servidor terminó con {process.returncode}; revisar {directory / 'server.log'}")
                if ready.exists():
                    try:
                        return json.loads(ready.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        return None
                return None
            yield process, wait_until(read_ready)
        finally:
            stop.touch()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(timeout=5)


@contextmanager
def etcd_process(directory: Path, certs: Path):
    directory.mkdir(parents=True, exist_ok=True)
    platform = "windows-amd64" if os.name == "nt" else "linux-amd64"
    binary = ROOT / ".tools/etcd-3.6.14" / platform / ("etcd.exe" if os.name == "nt" else "etcd")
    if not binary.is_file():
        raise FileNotFoundError("Ejecute scripts/fetch_etcd.py primero")
    port, peer_port = free_port(), free_port()
    while peer_port == port:
        peer_port = free_port()
    # En Linux el WAL debe vivir en FS nativo, nunca en /mnt/f de WSL.
    base = (ROOT / ".runtime/etcd-data" if os.name == "nt" else
            Path(os.environ.get("XDG_STATE_HOME", str(Path.home() / ".local/state"))) / "dfsha-stage2")
    data = base / str(uuid4())
    data.mkdir(parents=True)
    data.chmod(0o700)
    args = [str(binary), "--name=stage2", f"--data-dir={data}",
            f"--listen-client-urls=https://127.0.0.1:{port}",
            f"--advertise-client-urls=https://localhost:{port}",
            f"--listen-peer-urls=https://127.0.0.1:{peer_port}",
            f"--initial-advertise-peer-urls=https://localhost:{peer_port}",
            f"--initial-cluster=stage2=https://localhost:{peer_port}",
            f"--initial-cluster-token=stage2-{uuid4()}", "--initial-cluster-state=new",
            f"--cert-file={certs / 'etcd-server.crt'}", f"--key-file={certs / 'etcd-server.key'}",
            f"--trusted-ca-file={certs / 'ca.crt'}", "--client-cert-auth=true",
            f"--peer-cert-file={certs / 'etcd-server.crt'}", f"--peer-key-file={certs / 'etcd-server.key'}",
            f"--peer-trusted-ca-file={certs / 'ca.crt'}", "--peer-client-cert-auth=true",
            "--quota-backend-bytes=67108864", "--log-level=warn", "--enable-grpc-gateway=false"]
    with (directory / "etcd.log").open("wb") as log:
        process = subprocess.Popen(args, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=PROCESS_FLAGS)
        try:
            yield process, f"localhost:{port}", data
        finally:
            if process.poll() is None:
                process.terminate()  # Windows: parada del proceso aislado, no prueba de cierre graceful de etcd.
            process.wait(timeout=10)
            # Se conservan WAL/logs en ruta única ignorada para inspección; el probe limpia su prefijo antes.
