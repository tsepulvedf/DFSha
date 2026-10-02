#!/usr/bin/env bash
# Transfer via authenticated SSH into a root-only staging directory, never user-data.
set -euo pipefail
umask 077
[[ $(id -u) == 0 && $# == 1 ]] || { echo 'Usage as root: provision-host.sh PRIVATE_ROLE_BUNDLE'; exit 2; }
material=$(realpath -- "$1")
/opt/dfsha/venv/bin/python - "$material" <<'PY'
import json,pathlib,sys,urllib.request
from cryptography import x509
from cryptography.x509.oid import NameOID
from dfsha.common.protected import MetadataCipher
from dfsha.control.metadata import SQLiteMetadataStore
b=pathlib.Path(sys.argv[1]);m=json.loads((b/'material.json').read_text())
p=json.loads(pathlib.Path('/etc/dfsha/provisioned.json').read_text())
assert m['deployment_id']==p['deployment_id'] and m['slot']==p['slot'], 'Wrong host bundle'
if p['provider']=='aws':
 request=urllib.request.Request('http://169.254.169.254/latest/api/token',method='PUT',headers={'X-aws-ec2-metadata-token-ttl-seconds':'60'})
 with urllib.request.urlopen(request,timeout=5) as r:token=r.read().decode()
 request=urllib.request.Request('http://169.254.169.254/latest/meta-data/instance-id',headers={'X-aws-ec2-metadata-token':token})
 with urllib.request.urlopen(request,timeout=5) as r:actual=r.read().decode()
 assert actual==p['vm_id'], 'Actual VM differs from inventory'
else:
 raise ValueError('GCP host binding pending verified project')
assert not pathlib.Path('/var/lib/dfsha/data/inventory.sqlite3').exists(), 'Existing inventory: use recovery, not bootstrap'
for role,identity in [('control',m['control_id']),('data',m['node_id']),('etcd','member')]:
 cert=x509.load_pem_x509_certificate((b/role/(identity+'.crt')).read_bytes())
 expected='dfsha-etcd-'+m['slot'] if role=='etcd' else identity
 assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value==expected
 assert not any(pathlib.Path('/etc/dfsha/secrets',role).iterdir()), 'Never overwrite keys'
store=SQLiteMetadataStore(b/'inventory.sqlite3',MetadataCipher((b/'data/inventory.key').read_bytes()))
with store.transaction() as tx:assert tx.get('settings','node')['id_node']==m['node_id']
PY
for role in control data etcd; do
  for key in "$material/$role/"*.key "$material/$role/"*.crt; do
    [[ $(basename -- "$key") != ca.key ]] || { echo 'CA must stay offline'; exit 2; }
    install -o root -g "dfsha-$role" -m 0640 "$key" "/etc/dfsha/secrets/$role/$(basename -- "$key")"
  done
done
install -o dfsha-data -g dfsha-data -m 0600 "$material/inventory.sqlite3" /var/lib/dfsha/data/inventory.sqlite3
echo 'Provisioned, NOT started. Retain private recovery material outside service VMs.'
