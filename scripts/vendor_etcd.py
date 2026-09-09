"""Obtener fuentes oficiales sin modificarlas; luego verificar/reponer por hash.

--refresh es una acción de mantenimiento explícita, no parte del arranque normal.
La compilación adapta únicamente rutas de importación en una copia de build/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENDOR = ROOT / "third_party"
LOCK = VENDOR / "sources.lock.json"


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "DFSha-stage2"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    if args.refresh:
        google_commit = json.loads(fetch(
            "https://api.github.com/repos/googleapis/googleapis/commits/master"
        ))["sha"]
        upstream = {
            "etcd": ("etcd-io/etcd", "v3.6.14"),
            "gogo": ("gogo/protobuf", "v1.3.2"),
            "gateway": ("grpc-ecosystem/grpc-gateway", "v2.26.3"),
            "googleapis": ("googleapis/googleapis", google_commit),
        }

        def origin(proto: str) -> tuple[str, str]:
            if proto.startswith("etcd/"):
                return "etcd", proto.removeprefix("etcd/")
            if proto.startswith("gogoproto/"):
                return "gogo", proto
            if proto.startswith("google/api/"):
                return "googleapis", proto
            if proto.startswith("protoc-gen-openapiv2/"):
                return "gateway", proto
            raise ValueError(f"Import no contemplado: {proto}")

        pending = ["etcd/api/etcdserverpb/rpc.proto",
                   "etcd/server/etcdserver/api/v3lock/v3lockpb/v3lock.proto"]
        records: dict[str, dict] = {}

        def save(relative: str, project: str, upstream_path: str) -> bytes:
            repository, revision = upstream[project]
            url = f"https://raw.githubusercontent.com/{repository}/{revision}/{upstream_path}"
            payload = fetch(url)
            target = VENDOR / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
            records[relative] = {"project": project, "url": url,
                                 "sha256": hashlib.sha256(payload).hexdigest()}
            return payload

        while pending:
            name = pending.pop()
            if name.startswith("google/protobuf/") or "proto/" + name in records:
                continue
            project, upstream_path = origin(name)
            payload = save("proto/" + name, project, upstream_path)
            pending.extend(re.findall(r'^import\s+(?:public\s+)?"([^"]+)";',
                                      payload.decode(), re.MULTILINE))
        for project in upstream:
            save(f"licenses/{project}-LICENSE", project, "LICENSE")
        LOCK.write_text(json.dumps({"etcd_version": "3.6.14", "upstream": upstream,
                                    "files": records}, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads(LOCK.read_text(encoding="utf-8"))
    for relative, record in manifest["files"].items():
        target = VENDOR / relative
        if args.restore and not target.exists():
            payload = fetch(record["url"])
            if hashlib.sha256(payload).hexdigest() != record["sha256"]:
                raise ValueError(f"Hash remoto incorrecto: {relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        if hashlib.sha256(target.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError(f"Fuente modificada: {relative}")
    print(json.dumps({"verified_sources": len(manifest["files"]), "etcd": "3.6.14"}))


if __name__ == "__main__":
    main()
