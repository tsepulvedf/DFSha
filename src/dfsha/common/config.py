"""Listeners locales por defecto; perfil VM protegido explícito y sin fallback."""
from __future__ import annotations

import ipaddress
import re
import tomllib
from pathlib import Path


def loopback_address(address: str) -> str:
    host, port = address.rsplit(":", 1)
    if not ipaddress.ip_address(host).is_loopback or not 0 <= int(port) <= 65535:
        raise ValueError("El diagnóstico requiere una IP loopback y puerto válido")
    return address


def endpoint(address: str) -> str:
    """DNS/IPv4 advertised endpoint, not a listen address or a URL."""
    host, port = address.rsplit(':', 1)
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,252}', host) or not 1 <= int(port) <= 65535:
        raise ValueError('Endpoint DNS/IPv4 inválido')
    if host in ('0.0.0.0', 'localhost'):
        raise ValueError('Una VM no anuncia wildcard ni localhost')
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return address
    if ip.is_loopback or ip.is_unspecified or ip.is_multicast or ip.is_link_local:
        raise ValueError('Endpoint no enrutable')
    return address


def listener_address(cfg: dict, internal: bool) -> str:
    address = cfg['internal_bind' if internal else 'public_bind']
    profile = cfg.get('network_profile', 'loopback')
    if profile == 'loopback':
        return loopback_address(address)
    if profile != 'private-vm' or not cfg.get('metadata_key_path'):
        raise ValueError('Perfil VM requiere cifrado de metadatos explícito')
    host, port = address.rsplit(':', 1)
    ip = ipaddress.IPv4Address(host)
    network = ipaddress.IPv4Network(cfg['private_cidr'], strict=True)
    # RFC1918 only; ipaddress.is_private also includes documentation/reserved ranges.
    if not any(network.subnet_of(ipaddress.ip_network(n)) for n in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16')):
        raise ValueError('Red S/S requiere CIDR RFC1918')
    if not 1024 <= int(port) <= 65535:
        raise ValueError('Puerto de servicio inválido')
    if internal:
        if ip not in network or ip in (network.network_address, network.broadcast_address):
            raise ValueError('Listener S/S debe enlazar la IP privada de la VM')
    elif not ip.is_unspecified and ip not in network:
        raise ValueError('Listener público enlaza wildcard o IP privada; nunca la IP NAT')
    advertised = cfg['private_endpoint' if internal else 'client_endpoint']
    endpoint(advertised)
    if advertised.rsplit(':', 1)[1] != port:
        raise ValueError('Puerto anunciado y listener deben coincidir')
    if internal and advertised != address:
        raise ValueError('Endpoint S/S debe coincidir con la IP privada enlazada')
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
    network_cfg = {**server, **cfg.get('distributed', {})}
    listener_address(network_cfg, False)
    listener_address(network_cfg, True)
    if network_cfg.get('network_profile') == 'private-vm' and server['metadata_backend'] != 'etcd':
        raise ValueError('Perfil VM E9 exige autoridad etcd')
    if server["metadata_backend"] not in ('sqlite', 'etcd'):
        raise ValueError('Backend desconocido; no existe fallback automático')
    if not 1 <= server["max_workers"] <= 16 or not 1 <= server["max_concurrent_rpcs"] <= 32:
        raise ValueError("Concurrencia de diagnóstico fuera de límites")
    if not 0 <= server["grace_seconds"] <= 10:
        raise ValueError("Cierre fuera de límites")
    return cfg
