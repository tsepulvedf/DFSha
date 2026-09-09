"""Descargar solo el binario etcd de compatibilidad, verificado por SHA-256."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=["windows-amd64", "linux-amd64"])
    args = parser.parse_args()
    if platform.machine().lower() not in {"amd64", "x86_64"} and not args.platform:
        raise SystemExit("Arquitectura no fijada en deploy/etcd-artifacts.json")
    target_platform = args.platform or ("windows-amd64" if platform.system() == "Windows"
                                        else "linux-amd64")
    manifest = json.loads((ROOT / "deploy/etcd-artifacts.json").read_text())
    artifact = manifest[target_platform]
    tools_dir = ROOT / ".tools" / f"etcd-{manifest['version']}" / target_platform
    tools_dir.mkdir(parents=True, exist_ok=True)
    archive = tools_dir / artifact["url"].rsplit("/", 1)[1]
    if not archive.exists():
        with urllib.request.urlopen(artifact["url"], timeout=60) as source, archive.open("wb") as dest:
            shutil.copyfileobj(source, dest, length=256 * 1024)
    with archive.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    if digest != artifact["sha256"]:
        raise SystemExit("SHA-256 incorrecto: no se extrae ni ejecuta el archivo")
    binary_name = "etcd.exe" if target_platform.startswith("windows") else "etcd"
    member_name = f"etcd-v{manifest['version']}-{target_platform}/{binary_name}"
    destination = tools_dir / binary_name
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as source, source.open(member_name) as binary:
            payload = binary.read()
    else:
        with tarfile.open(archive, "r:gz") as source:
            member = source.extractfile(member_name)
            if member is None:
                raise SystemExit("Binario ausente")
            payload = member.read()
    # Se extrae un único miembro conocido; nunca rutas arbitrarias del archivo.
    destination.write_bytes(payload)
    destination.chmod(0o700)
    print(json.dumps({"binary": str(destination), "version": manifest["version"],
                      "archive_sha256": digest, "binary_sha256": hashlib.sha256(payload).hexdigest()}))


if __name__ == "__main__":
    main()
