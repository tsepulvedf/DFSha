"""Configuración explícita: esta etapa solo escucha en loopback."""
from __future__ import annotations

import ipaddress
import tomllib
from pathlib import Path


def loopback_address(address: str) -> str:
    host, port = address.rsplit(":", 1)
    if not ipaddress.ip_address(host).is_loopback or not 0 <= int(port) <= 65535:
        raise ValueError("El diagnóstico requiere una IP loopback y puerto válido")
    return address


def read_config(path: Path) -> dict:
    with path.open("rb") as stream:
        cfg = tomllib.load(stream)
    if 'server' not in cfg and 'client' in cfg:
        client = cfg['client']
        for target in client.get('public_targets', [client.get('public_target', '')]):
            host, port = target.rsplit(':', 1)
            if not host or not 1 <= int(port) <= 65535 or not client.get('certificate_dir'):
                raise ValueError('Cliente requiere punto de entrada y CA explícitos')
        return cfg
    server = cfg["server"]
    loopback_address(server["public_bind"])
    loopback_address(server["internal_bind"])
    if server["metadata_backend"] not in ('sqlite', 'etcd'):
        raise ValueError('Backend desconocido; no existe fallback automático')
    if not 1 <= server["max_workers"] <= 16 or not 1 <= server["max_concurrent_rpcs"] <= 32:
        raise ValueError("Concurrencia de diagnóstico fuera de límites")
    if not 0 <= server["grace_seconds"] <= 10:
        raise ValueError("Cierre fuera de límites")
    return cfg
