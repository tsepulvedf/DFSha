"""CA y certificados efímeros de desarrollo; nunca utilizarlos en producción."""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import ipaddress
import json
import os
from pathlib import Path
import subprocess

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


def generate(directory: Path) -> dict:
    directory.mkdir(parents=True, exist_ok=True)
    # No sobreescribir una CA existente: rompería clientes que ya la confían.
    if any(directory.iterdir()):
        raise ValueError("Directorio de certificados no vacío; use otro directorio para rotar")
    directory.chmod(0o700)
    if os.name == "nt":
        identity = subprocess.check_output(["whoami", "/user", "/fo", "csv", "/nh"], text=True)
        sid = next(csv.reader(identity.strip().splitlines()))[1]
        subprocess.run(["icacls", str(directory), "/inheritance:r", "/grant:r",
                        f"*{sid}:(OI)(CI)F", "*S-1-5-18:(OI)(CI)F",
                        "*S-1-5-32-544:(OI)(CI)F"], check=True, capture_output=True)
    now = datetime.now(timezone.utc)

    def issue(name: str, common_name: str, issuer=None, server=False, client=False, san=None):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])
        is_ca = issuer is None
        issuer_cert, issuer_key = issuer if issuer else (None, key)
        builder = (x509.CertificateBuilder().subject_name(subject)
                   .issuer_name(issuer_cert.subject if issuer_cert else subject)
                   .public_key(key.public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now - timedelta(minutes=5))
                   .not_valid_after(now + timedelta(days=7))
                   .add_extension(x509.BasicConstraints(ca=is_ca, path_length=0 if is_ca else None), True)
                   .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False,
                       key_encipherment=server, data_encipherment=False, key_agreement=False,
                       key_cert_sign=is_ca, crl_sign=is_ca, encipher_only=None, decipher_only=None), True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), False))
        if not is_ca:
            builder = builder.add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                issuer_key.public_key()), False)
            purposes = ([ExtendedKeyUsageOID.SERVER_AUTH] if server else []) + (
                [ExtendedKeyUsageOID.CLIENT_AUTH] if client else [])
            builder = builder.add_extension(x509.ExtendedKeyUsage(purposes), False)
        if san:
            builder = builder.add_extension(x509.SubjectAlternativeName(san), False)
        cert = builder.sign(issuer_key, hashes.SHA256())
        private = directory / f"{name}.key"
        private.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        private.chmod(0o600)
        (directory / f"{name}.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        return cert, key

    ca = issue("ca", "DFSha development CA")
    rogue = issue("rogue-ca", "Untrusted test CA")
    local_san = [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
    issue("server", "localhost", ca, server=True, san=local_san)
    issue("wrong-name-server", "wrong.invalid", ca, server=True, san=[x509.DNSName("wrong.invalid")])
    issue("client", "dfsha-diagnostic", ca, client=True)
    issue("rogue-client", "dfsha-diagnostic", rogue, client=True)
    issue("etcd-server", "localhost", ca, server=True, client=True, san=local_san)
    for identity, common_name in (("etcd-root", "root"), ("etcd-probe", "dfsha-probe"),
                                  ("etcd-denied", "dfsha-denied")):
        issue(identity, common_name, ca, client=True)
    return {"status": "EJECUTADO", "certificates": 10, "valid_days": 7,
            "private_material": "excluded from Git; local ACL/permissions"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path(".runtime/certs"))
    args = parser.parse_args()
    print(json.dumps(generate(args.output.resolve())))
