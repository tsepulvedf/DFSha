"""One-time private E9 material. CA stays with custodian; never rerun on an existing root."""
import argparse
from datetime import datetime, timedelta, timezone
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import shutil

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from cloud_bundle import validate
from issue_certificate import issue
from dfsha.control.auth import initialize, protect
from dfsha.control.metadata import SQLiteMetadataStore
from dfsha.common.protected import MetadataCipher


def prepare(inventory, output, password):
    validate(inventory)
    output=Path(output)
    if output.exists():raise FileExistsError('No regenerar PKI, claves ni identidades existentes')
    output.mkdir(parents=True);protect(output)
    ca_dir=output/'custodian';ca_dir.mkdir();protect(ca_dir)
    key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    now=datetime.now(timezone.utc)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'DFSha '+inventory['deployment_id'])])
    cert=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
        .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
        .not_valid_after(now+timedelta(days=30)).add_extension(x509.BasicConstraints(ca=True,path_length=0),True)
        .add_extension(x509.KeyUsage(digital_signature=True,content_commitment=False,key_encipherment=False,
            data_encipherment=False,key_agreement=False,key_cert_sign=True,crl_sign=True,encipher_only=None,decipher_only=None),True)
        .sign(key,hashes.SHA256()))
    (ca_dir/'ca.key').write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    protect(ca_dir/'ca.key');(ca_dir/'ca.crt').write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    metadata=os.urandom(32);content=os.urandom(32)
    (ca_dir/'metadata.key').write_bytes(metadata);protect(ca_dir/'metadata.key')
    cfg=dict(sqlite_path=str(ca_dir/'bootstrap.sqlite3'),key_path=str(ca_dir/'master.key'),
        block_path=str(ca_dir/'empty-blocks'),metadata_key_path=str(ca_dir/'metadata.key'))
    initialize(cfg,'admin',password)
    master=(ca_dir/'master.key').read_bytes()
    serials=[]
    for n in inventory['nodes']:
        host=output/n['slot'];host.mkdir();protect(host)
        dns=[];ips=[n['private_ip']]
        try:ipaddress.ip_address(n['public_host']);ips.append(n['public_host'])
        except ValueError:dns.append(n['public_host'])
        for role,identity,cn in [('control',n['control_id'],n['control_id']),('data',n['node_id'],n['node_id']),
                                ('etcd','member','dfsha-etcd-'+n['slot'])]:
            serials.append(issue(ca_dir,host/role,identity,cn,dns=tuple(dns),ips=tuple(ips),days=7))
        for role,filename,payload in [('control','master.key',master),('control','metadata.key',metadata),
                                     ('data','content.key',content),('data','inventory.key',os.urandom(32))]:
            path=host/role/filename;path.write_bytes(payload);protect(path)
        store=SQLiteMetadataStore(host/'inventory.sqlite3',MetadataCipher((host/'data/inventory.key').read_bytes()))
        store.initialize()
        with store.transaction(True) as tx:
            tx.put('settings',dict(id='node',id_node=n['node_id'],key_sha256=hashlib.sha256(content).hexdigest(),generation=0))
        protect(store.path)
        (host/'material.json').write_text(json.dumps(dict(deployment_id=inventory['deployment_id'],
            slot=n['slot'],node_id=n['node_id'],control_id=n['control_id'])),encoding='utf-8')
    # Only administrative material, never the signing CA, is sent to bootstrap VM A.
    admin=output/'admin'
    issue(ca_dir,admin,'etcd-root','root',dns=(),ips=tuple(n['private_ip'] for n in inventory['nodes']),days=7)
    shutil.copyfile(ca_dir/'bootstrap.sqlite3',admin/'bootstrap.sqlite3');protect(admin/'bootstrap.sqlite3')
    trust=output/'client-trust';trust.mkdir();shutil.copyfile(ca_dir/'ca.crt',trust/'ca.crt')
    return dict(status='MATERIAL_PREPARADO_NO_PROVISIONADO',deployment_id=inventory['deployment_id'],
        certificates=serials,bootstrap_password_persisted=False,ca_on_service_hosts=False)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(prepare(json.loads(args.inventory.read_text()),args.output,getpass.getpass('Contraseña administrativa inicial: '))))


if __name__=='__main__':main()
