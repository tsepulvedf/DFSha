"""Render E9 host bundles; no cloud mutation, SSH, secret generation or auto-start."""
import argparse
import hashlib
import ipaddress
import json
from pathlib import Path
import re
from uuid import UUID

from dfsha.common.config import endpoint, listener_address
from runtime import ROOT


def validate(value):
    if value['schema'] != 1 or value['provider'] not in ('aws', 'gcp'):
        raise ValueError('Seleccione el proveedor académico verificado')
    if 'REPLACE' in json.dumps(value) or 'SELECT_' in json.dumps(value):
        raise ValueError('Inventario contiene parámetros pendientes')
    UUID(value['deployment_id'])
    if not re.fullmatch(r'[a-f0-9]{40}', value['artifact_commit']) or not re.fullmatch(r'[a-f0-9]{64}', value['artifact_sha256']):
        raise ValueError('Exigir commit y SHA256 del wheel')
    if not value['image_id'] or not value['account_project'] or not value['region']:
        raise ValueError('Falta identidad de imagen/cuenta/región')
    if not 0 < value['duration_hours'] <= 24 or not value['budget_usd'] or value['budget_usd'] <= 0:
        raise ValueError('Falta duración/budget acotados; el renderer no concede autorización de gasto')
    network = ipaddress.IPv4Network(value['private_cidr'])
    for cidr in [value['admin_cidr'], *value['client_cidrs']]:
        parsed = ipaddress.IPv4Network(cidr)
        if parsed.prefixlen < 24 or parsed.network_address.is_unspecified:
            raise ValueError('Orígenes externos deben estar restringidos a /24 o más')
    if not value['client_cidrs'] or len(value['nodes']) != 3 or {n['slot'] for n in value['nodes']} != {'a','b','c'}:
        raise ValueError('E9 base requiere exactamente tres VMs a/b/c y orígenes cliente')
    for field in ('vm_id','private_ip','public_host','control_id','node_id','volume_id'):
        if len({n[field] for n in value['nodes']}) != 3:
            raise ValueError('Identidades/rutas independientes requeridas: '+field)
    ids = [n[k] for n in value['nodes'] for k in ('control_id','node_id')]
    if len(set(ids)) != 6:
        raise ValueError('Cada rol requiere identidad distinta')
    for n in value['nodes']:
        UUID(n['node_id']); UUID(n['control_id'])
        if not re.fullmatch(r'[A-Za-z0-9_./:-]{1,200}', n['vm_id']) or not n['zone']:
            raise ValueError('Identidad VM/zona inválida')
        ip = ipaddress.IPv4Address(n['private_ip'])
        if ip not in network or ip in (network.network_address, network.broadcast_address):
            raise ValueError('IP privada fuera de subred')
        endpoint(n['public_host']+':7443')
        if not 2147483648 <= n['capacity_bytes'] <= 21474836480:
            raise ValueError('Cuota de DN debe dejar margen en volumen de 40 GiB')
        listener_address(dict(network_profile='private-vm', metadata_key_path='required',
            private_cidr=value['private_cidr'], internal_bind=n['private_ip']+':7445',
            private_endpoint=n['private_ip']+':7445'), True)
    return value


def attest(inventory, evidence):
    """Only read-only provider observations, not a manually declared host label."""
    if evidence.get('status') != 'LECTURA_VERIFICADA' or evidence['provider'] != inventory['provider']:
        raise ValueError('Exigir preflight del proveedor aprobado')
    rows = evidence['commands']
    results = {next((x for x in ('describe-instances','describe-volumes','get-caller-identity') if x in r['argv']), ''):r['result'] for r in rows}
    if inventory['provider'] == 'aws':
        if results.get('get-caller-identity', {}).get('Account') != inventory['account_project']:
            raise ValueError('Cuenta no coincide')
        vms = {v['id']:v for v in results.get('describe-instances', [])}
        disks = {v['id']:v for v in results.get('describe-volumes', [])}
        for n in inventory['nodes']:
            vm, disk = vms.get(n['vm_id'], {}), disks.get(n['volume_id'], {})
            if vm.get('private') != n['private_ip'] or vm.get('zone') != n['zone'] or not disk.get('encrypted') or n['volume_id'] not in vm.get('volumes', []):
                raise ValueError('VM/disco/dominio no comprobado por API')
            if not vm.get('volumes') or not all(disks.get(v,{}).get('encrypted') for v in vm['volumes']):
                raise ValueError('Falta verificar cifrado de todos los discos, incluida raíz')
        if len({vms[n['vm_id']]['vpc'] for n in inventory['nodes']}) != 1:
            raise ValueError('Las VMs deben compartir VPC')
    else:
        # GCP export maps need exact network/disk identities, not AWS assumptions.
        raise ValueError('Mapeo administrativo GCP pendiente hasta disponer de proyecto; no fingir validación')
    return dict(verified_by='cloud_preflight:'+evidence['run_id'], evidence=evidence['run_id'],
        provider=inventory['provider'], nodes={n['node_id']:n['vm_id'] for n in inventory['nodes']})


def toml(sections):
    return '\n'.join('['+section+']\n'+'\n'.join(k+' = '+json.dumps(v) for k,v in values.items())
        for section, values in sections.items())+'\n'


def unit(role, command, memory):
    return f'''[Unit]
Description=DFSha E9 {role}
After=network-online.target dfsha-firewall.service
Requires=dfsha-firewall.service
Wants=network-online.target
RequiresMountsFor=/var/lib/dfsha
ConditionPathExists=/etc/dfsha/{'provisioned.json' if role == 'etcd' else 'activation.json'}
ConditionPathExists=/etc/dfsha/secrets/{role}/{'member.key' if role == 'etcd' else 'master.key' if role == 'control' else 'content.key'}
StartLimitIntervalSec=60
StartLimitBurst=10
[Service]
Type=simple
User=dfsha-{role}
Group=dfsha-{role}
ExecStart={command}
Restart=on-failure
RestartSec=5
TimeoutStopSec=30
UMask=0077
NoNewPrivileges=true
ProtectSystem=strict
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictRealtime=true
LockPersonality=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET
LimitCORE=0
LimitNOFILE=4096
TasksMax=256
MemoryMax={memory}
MemorySwapMax=0
ReadWritePaths=/var/lib/dfsha/{role}
InaccessiblePaths=/etc/dfsha/admin
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
'''


def render(inventory, output, attestation=None):
    validate(inventory)
    output = Path(output)
    if output.exists():
        raise FileExistsError('Use un directorio nuevo; no sobrescribir identidades/configuración')
    output.mkdir(parents=True)
    nodes = sorted(inventory['nodes'], key=lambda n:n['slot'])
    controls = [n['control_id'] for n in nodes]
    targets = [n['private_ip']+':7445' for n in nodes]
    allowed = {n['node_id']:dict(identity=n['node_id'],client_endpoint=n['public_host']+':7444',
        private_endpoint=n['private_ip']+':7446', failure_domain=n['vm_id'],capacity_bytes=n['capacity_bytes']) for n in nodes}
    prefix = '/dfsha/cloud/'+inventory['deployment_id']
    for n in nodes:
        d = output/n['slot'];d.mkdir()
        common = dict(network_profile='private-vm',private_cidr=inventory['private_cidr'])
        server = dict(**common,public_bind='0.0.0.0:7443',internal_bind=n['private_ip']+':7445',
            client_endpoint=n['public_host']+':7443',private_endpoint=n['private_ip']+':7445',
            certificate_dir='/etc/dfsha/secrets/control',certificate_identity=n['control_id'],
            max_workers=12,max_concurrent_rpcs=24,grace_seconds=3,metadata_backend='etcd',
            sqlite_path='/var/lib/dfsha/control/auxiliary.sqlite3',block_path='/var/lib/dfsha/control/unused-blocks')
        distributed = dict(enabled=True,rf3_enabled=True,replication_enabled=True,failure_profile='independent-hosts',
            default_replicas=3,key_path='/etc/dfsha/secrets/control/master.key',
            metadata_key_path='/etc/dfsha/secrets/control/metadata.key',block_size_bytes=67108864,
            capacity_bytes=n['capacity_bytes'],max_file_bytes=17179869184,
            authorized_nodes_path='/etc/dfsha/authorized-nodes.json',infrastructure_inventory_path='/etc/dfsha/infrastructure.json',
            etcd_prefix=prefix,etcd_endpoints=[v['private_ip']+':2379' for v in nodes],
            etcd_certificate_dir='/etc/dfsha/secrets/control',etcd_identity=n['control_id'],
            control_rpc_timeout_seconds=15,metadata_gate_wait_seconds=8,metadata_gate_lease_seconds=30,
            suspect_ms=12000,unavailable_ms=30000,service_epoch='NOT_ACTIVATED')
        dn = dict(**common,certificate_dir='/etc/dfsha/secrets/data',certificate_identity=n['node_id'],
            control_identity=controls[0],control_identities=controls,control_internal_targets=targets,
            control_internal_target=targets[0],service_epoch='NOT_ACTIVATED',
            public_bind='0.0.0.0:7444',internal_bind=n['private_ip']+':7446',
            client_endpoint=n['public_host']+':7444',private_endpoint=n['private_ip']+':7446',
            failure_domain=n['vm_id'],capacity_bytes=n['capacity_bytes'],
            sqlite_path='/var/lib/dfsha/data/inventory.sqlite3',block_path='/var/lib/dfsha/data/blocks',
            key_path='/etc/dfsha/secrets/data/content.key',metadata_key_path='/etc/dfsha/secrets/data/inventory.key',
            rf3_enabled=True,replication_enabled=True,heartbeat_seconds=3,control_rpc_timeout_seconds=15)
        (d/'control.toml').write_text(toml({'server':server,'distributed':distributed}),encoding='utf-8')
        (d/'data.toml').write_text(toml({'datanode':dn}),encoding='utf-8')
        (d/'authorized-nodes.json').write_text(json.dumps(allowed,indent=2),encoding='utf-8')
        (d/'control-identities.json').write_text(json.dumps(controls),encoding='utf-8')
        (d/'infrastructure.json').write_text(json.dumps(attestation or {'status':'UNVERIFIED'},indent=2),encoding='utf-8')
        etcd = {'name':n['slot'],'data-dir':'/var/lib/dfsha/etcd/member',
            'listen-client-urls':'https://'+n['private_ip']+':2379',
            'advertise-client-urls':'https://'+n['private_ip']+':2379',
            'listen-peer-urls':'https://'+n['private_ip']+':2380',
            'initial-advertise-peer-urls':'https://'+n['private_ip']+':2380',
            'initial-cluster':','.join(v['slot']+'=https://'+v['private_ip']+':2380' for v in nodes),
            'initial-cluster-token':inventory['deployment_id'],'initial-cluster-state':'new',
            'quota-backend-bytes':1073741824,'max-request-bytes':1572864,'max-txn-ops':128,
            'enable-grpc-gateway':False,'log-level':'warn','logger':'zap',
            'client-transport-security':{'cert-file':'/etc/dfsha/secrets/etcd/member.crt','key-file':'/etc/dfsha/secrets/etcd/member.key',
                'trusted-ca-file':'/etc/dfsha/secrets/etcd/ca.crt','client-cert-auth':True},
            'peer-transport-security':{'cert-file':'/etc/dfsha/secrets/etcd/member.crt','key-file':'/etc/dfsha/secrets/etcd/member.key',
                'trusted-ca-file':'/etc/dfsha/secrets/etcd/ca.crt','client-cert-auth':True,'allowed-cn':['dfsha-etcd-a','dfsha-etcd-b','dfsha-etcd-c']}}
        (d/'etcd.json').write_text(json.dumps(etcd,indent=2),encoding='utf-8')
        for role, command, memory in (
            ('control','/opt/dfsha/venv/bin/python -m dfsha.control.server --config /etc/dfsha/control.toml --ready-file /var/lib/dfsha/control/ready.json','768M'),
            ('data','/opt/dfsha/venv/bin/python -m dfsha.datanode.server --config /etc/dfsha/data.toml --ready-file /var/lib/dfsha/data/ready.json --stop-file /var/lib/dfsha/data/stop','1024M'),
            ('etcd','/opt/dfsha/etcd/etcd --config-file=/etc/dfsha/etcd.json','768M')):
            (d/f'dfsha-{role}.service').write_text(unit(role,command,memory),encoding='utf-8')
        # Dedicated table only. Default drop in our chain; never flush the host ruleset.
        peers=', '.join(v['private_ip'] for v in nodes)
        clients=', '.join(inventory['client_cidrs'])
        firewall=f'''table inet dfsha {{
 chain input {{
  type filter hook input priority 0; policy drop;
  iifname "lo" accept
  ct state established,related accept
  ip protocol icmp accept
  ip saddr {inventory['admin_cidr']} tcp dport 22 accept
  ip saddr {{ {clients} }} tcp dport {{ 7443, 7444 }} accept
  ip saddr {{ {peers} }} tcp dport {{ 2379, 2380, 7445, 7446 }} accept
 }}
}}
'''
        (d/'firewall.nft').write_text(firewall,encoding='utf-8')
        (d/'bundle.json').write_text(json.dumps(dict(deployment_id=inventory['deployment_id'],slot=n['slot'],
            vm_id=n['vm_id'],provider=inventory['provider'],artifact_sha256=inventory['artifact_sha256'],artifact_commit=inventory['artifact_commit'],
            provisionable=attestation is not None),indent=2),encoding='utf-8')
        (d/'requirements.lock').write_bytes((ROOT/'requirements.lock').read_bytes())
        for helper in ('cloud_host.py','cloud_bundle.py','cloud_initialize.py','runtime.py'):
            (d/helper).write_bytes((ROOT/'scripts'/helper).read_bytes())
    (output/'client.toml').write_text(toml({'client':dict(public_targets=[n['public_host']+':7443' for n in nodes],
        certificate_dir='REPLACE_LOCAL_TRUST_DIRECTORY',require_encrypted_session=True)}),encoding='utf-8')
    (output/'inventory.json').write_text(json.dumps(inventory,indent=2),encoding='utf-8')
    return dict(status='CONFIGURADO_NO_DESPLEGADO',hosts=3,attested=attestation is not None,
        files={p.relative_to(output).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in output.rglob('*') if p.is_file()})


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inventory',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--preflight',type=Path)
    args=p.parse_args();inventory=validate(json.loads(args.inventory.read_text(encoding='utf-8')))
    verified=attest(inventory,json.loads(args.preflight.read_text(encoding='utf-8'))) if args.preflight else None
    print(json.dumps(render(inventory,args.output,verified)))


if __name__=='__main__':main()
