"""Emitir un nuevo par de claves/certificado usando una CA existente, sin reemplazarla."""
import argparse
from datetime import datetime, timedelta, timezone
import ipaddress
from pathlib import Path
import shutil

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
from dfsha.control.auth import protect


def issue(ca_dir, output, identity, common_name=None, dns=('localhost',), ips=('127.0.0.1',), days=7):
    ca_dir, output = Path(ca_dir), Path(output)
    if output.exists() or not identity or any(x in identity for x in '/\\:') or identity in ('.', '..'):
        raise ValueError('Use una identidad simple y un directorio nuevo')
    if not 1 <= days <= 30:
        raise ValueError('Vigencia permitida: 1 a 30 días, limitada además por la CA')
    ca = x509.load_pem_x509_certificate((ca_dir/'ca.crt').read_bytes())
    signer = serialization.load_pem_private_key((ca_dir/'ca.key').read_bytes(), password=None)
    if not ca.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
        raise ValueError('El emisor no es una CA')
    if signer.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != ca.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
        raise ValueError('Clave del emisor incompatible')
    now = datetime.now(timezone.utc)
    until = min(now+timedelta(days=days), ca.not_valid_after_utc)
    if until <= now:
        raise ValueError('CA vencida')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    cert = (x509.CertificateBuilder().subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name or identity)]))
        .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(now-timedelta(minutes=1)).not_valid_after(until)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=True,
            data_encipherment=False, key_agreement=False, key_cert_sign=False, crl_sign=False,
            encipher_only=None, decipher_only=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(n) for n in dns]+
            [x509.IPAddress(ipaddress.ip_address(n)) for n in ips]), critical=False)
        .sign(signer, hashes.SHA256()))
    output.mkdir(parents=True)
    protect(output)
    (output/(identity+'.key')).write_bytes(key.private_bytes(serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    protect(output/(identity+'.key'))
    (output/(identity+'.crt')).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    shutil.copyfile(ca_dir/'ca.crt', output/'ca.crt')
    return dict(identity=identity, serial=cert.serial_number, expires=until.isoformat())


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ca-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--identity', required=True)
    parser.add_argument('--common-name')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--dns', action='append', help='SAN DNS explícito; se puede repetir')
    parser.add_argument('--ip', action='append', help='SAN IP explícito; se puede repetir')
    args = parser.parse_args()
    print(json.dumps(issue(args.ca_dir, args.output, args.identity, args.common_name,
        dns=tuple(args.dns or (() if args.ip else ('localhost',))),
        ips=tuple(args.ip or (() if args.dns else ('127.0.0.1',))), days=args.days)))
