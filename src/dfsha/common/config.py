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
    server = cfg["server"]
    loopback_address(server["public_bind"])
    loopback_address(server["internal_bind"])
    if server["metadata_backend"] != "sqlite":
        raise ValueError("E2 solo prepara el adaptador local SQLite de H1")
    if not 1 <= server["max_workers"] <= 16 or not 1 <= server["max_concurrent_rpcs"] <= 32:
        raise ValueError("Concurrencia de diagnóstico fuera de límites")
    if not 0 <= server["grace_seconds"] <= 10:
        raise ValueError("Cierre fuera de límites")
    return cfg
