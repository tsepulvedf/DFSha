"""E9 read-only academic access inventory. Never select an implicit personal account."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
from uuid import uuid4

from verify_stage8 import atomic_json


def inspect(args):
    report = dict(run_id=str(uuid4()), start=datetime.now(timezone.utc).isoformat(),
        status='BLOQUEADO_POR_ENTORNO', provider=args.provider, commands=[], resources_created=[],
        tools={x: shutil.which(x) for x in ('aws', 'gcloud', 'ssh', 'scp', 'docker')},
        credential_environment_names=[k for k in os.environ if k.startswith(('AWS_', 'GOOGLE_', 'CLOUDSDK_'))],
        missing=[])
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def run(command):
        row = dict(argv=command, exit_code=None)
        report['commands'].append(row)
        atomic_json(args.output, report)
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=45,
                env=dict(os.environ, AWS_PAGER='', CLOUDSDK_CORE_DISABLE_PROMPTS='1'))
            row['exit_code'] = result.returncode
            if result.returncode:
                # Provider stderr may contain credential paths or response material.
                row['status'] = 'FALLIDO'; return None
            row['result'] = json.loads(result.stdout)
            row['status'] = 'EJECUTADO'
            return row['result']
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
            row['status'] = 'BLOQUEADO_POR_ENTORNO'; row['error_type'] = type(exc).__name__
            return None
        finally:
            atomic_json(args.output, report)

    if not args.provider:
        report['missing'].append('Proveedor académico, perfil/proyecto, región y autorización de presupuesto no definidos')
    elif not report['tools'][args.provider == 'aws' and 'aws' or 'gcloud']:
        report['missing'].append('CLI del proveedor no disponible en PATH; no se instaló otra ruta')
    elif not all((args.account, args.region, args.deployment_id)) or (args.provider == 'aws' and not args.profile):
        report['missing'].append('Exigir cuenta/proyecto esperado, región, deployment-id y perfil AWS explícito')
    elif args.provider == 'aws':
        base = ['aws', '--profile', args.profile, '--region', args.region, '--output', 'json']
        identity = run(base+['sts', 'get-caller-identity'])
        if not identity or identity.get('Account') != args.account:
            report['missing'].append('Identidad académica esperada no verificada; no se consultan recursos de otra cuenta')
        else:
            tag = 'Name=tag:DFShaDeployment,Values='+str(uuid4() if not args.deployment_id else args.deployment_id)
            run(base+['ec2', 'describe-instances', '--filters', tag, '--query',
                'Reservations[].Instances[].{id:InstanceId,state:State.Name,type:InstanceType,zone:Placement.AvailabilityZone,private:PrivateIpAddress,public:PublicIpAddress,vpc:VpcId,subnet:SubnetId,volumes:BlockDeviceMappings[].Ebs.VolumeId}'])
            run(base+['ec2', 'describe-volumes', '--filters', tag, '--query',
                'Volumes[].{id:VolumeId,encrypted:Encrypted,kms:KmsKeyId,size:Size,state:State,zone:AvailabilityZone,attachments:Attachments[].InstanceId}'])
            run(base+['ec2', 'describe-security-groups', '--filters', tag, '--query',
                'SecurityGroups[].{id:GroupId,vpc:VpcId,ingress:IpPermissions,egress:IpPermissionsEgress}'])
            run(base+['ec2', 'describe-availability-zones', '--query', 'AvailabilityZones[].{name:ZoneName,state:State,region:RegionName}'])
            run(base+['service-quotas', 'list-service-quotas', '--service-code', 'ec2', '--query',
                'Quotas[].{name:QuotaName,value:Value,code:QuotaCode}'])
    else:
        base = ['gcloud', '--project', args.account, '--quiet']
        project = run(base+['projects', 'describe', args.account, '--format=json(projectId,projectNumber,lifecycleState)'])
        if not project or project.get('projectId') != args.account:
            report['missing'].append('Proyecto académico esperado no verificado')
        else:
            run(base+['compute', 'instances', 'list', '--filter=labels.dfsha-deployment='+args.deployment_id,
                '--format=json(id,name,zone,status,machineType,networkInterfaces.networkIP,networkInterfaces.accessConfigs.natIP,disks.source)'])
            run(base+['compute', 'disks', 'list', '--filter=labels.dfsha-deployment='+args.deployment_id,
                '--format=json(id,name,zone,sizeGb,status,diskEncryptionKey.kmsKeyName,users)'])
            run(base+['compute', 'regions', 'describe', args.region, '--format=json(name,status,quotas)'])
            run(base+['compute', 'firewall-rules', 'list', '--filter=name~dfsha-',
                '--format=json(name,network,direction,sourceRanges,allowed,denied,targetTags)'])
    if report['commands'] and all(c.get('status') == 'EJECUTADO' for c in report['commands']) and not report['missing']:
        report['status'] = 'LECTURA_VERIFICADA'
    report['end'] = datetime.now(timezone.utc).isoformat()
    report['deployment_acceptance'] = 'PENDIENTE: lectura no acredita presupuesto, aprovisionamiento ni acceso externo'
    atomic_json(args.output, report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--provider', choices=('aws', 'gcp'))
    for key in ('account', 'region', 'profile', 'deployment-id'):
        p.add_argument('--'+key)
    p.add_argument('--output', type=Path, default=Path('docs/evidencias/etapa9/preflight.json'))
    args = p.parse_args(); report = inspect(args)
    print(json.dumps(dict(status=report['status'], evidence=str(args.output), missing=report['missing'])))
    return 0 if report['status'] == 'LECTURA_VERIFICADA' else 2


if __name__ == '__main__':
    raise SystemExit(main())
