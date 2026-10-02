"""E9 read-only academic access inventory. Never select an implicit personal account."""
import argparse
import configparser
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import re
import subprocess
from uuid import uuid4

from verify_stage8 import atomic_json


def profile_facts(profile, home=None):
    """Presence only. Never serialize access keys, tokens or arbitrary config values."""
    home = Path(home or Path.home()) / '.aws'
    config = configparser.RawConfigParser(); credentials = configparser.RawConfigParser()
    config.read(home / 'config'); credentials.read(home / 'credentials')
    section = 'profile ' + profile
    region = config.get(section, 'region', fallback=None)
    return dict(profile=profile, configured=credentials.has_section(profile),
        temporary_credentials_complete=all(credentials.get(profile, key, fallback='').strip()
            for key in ('aws_access_key_id','aws_secret_access_key','aws_session_token')),
        region=region if region and re.fullmatch(r'[a-z]{2}-[a-z]+-\d', region) else None)


def aws_environment():
    # Do not let credentials/config redirects from another shell select a personal account.
    env = {k:v for k,v in os.environ.items() if not k.startswith('AWS_')}
    return dict(env, AWS_PAGER='', AWS_EC2_METADATA_DISABLED='true', AWS_MAX_ATTEMPTS='2')


def inspect(args):
    report = dict(run_id=str(uuid4()), start=datetime.now(timezone.utc).isoformat(),
        status='BLOQUEADO_POR_ENTORNO', provider=args.provider, commands=[], resources_created=[],
        tools={x: shutil.which(x) for x in ('aws', 'gcloud', 'ssh', 'scp', 'docker')},
        credential_environment_names=[k for k in os.environ if k.startswith(('AWS_', 'GOOGLE_', 'CLOUDSDK_'))],
        missing=[], benefits='NO_VERIFICADOS; sin descuento en estimacion',
        economic_authorization=False)
    if args.provider == 'aws':
        report['profile'] = profile_facts(args.profile)
        args.region = args.region or report['profile']['region']
        if not report['profile']['temporary_credentials_complete']:
            report['missing'].append('Perfil temporal dedicado incompleto: acceso, secreto y session token requeridos')
        if not args.region:report['missing'].append('Region academica permitida pendiente; no se adopta region de ejemplo')
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def run(command, required=True):
        row = dict(argv=command, exit_code=None, required=required)
        report['commands'].append(row)
        atomic_json(args.output, report)
        try:
            result = subprocess.run(command, capture_output=True, text=True, timeout=45,
                env=aws_environment() if args.provider == 'aws' else dict(os.environ, CLOUDSDK_CORE_DISABLE_PROMPTS='1'))
            row['exit_code'] = result.returncode
            if result.returncode:
                # Provider stderr may contain credential paths or response material.
                row['status'] = 'FALLIDO'
                codes = ('ExpiredToken','InvalidClientTokenId','UnrecognizedClientException',
                         'AccessDenied','UnauthorizedOperation','AuthFailure','OptInRequired','RequestExpired')
                row['reason'] = next((c for c in codes if c in result.stderr), 'DEPENDENCIA_O_PERMISO_NO_VERIFICADO')
                return None
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
        if report['missing']:
            report['end'] = datetime.now(timezone.utc).isoformat()
            atomic_json(args.output, report);return report
        base = ['aws', '--profile', args.profile, '--region', args.region, '--output', 'json']
        identity = run(base+['sts', 'get-caller-identity'])
        if not identity or identity.get('Account') != args.account:
            report['missing'].append('Identidad académica esperada no verificada; no se consultan recursos de otra cuenta')
        else:
            tag = 'Name=tag:DFShaDeployment,Values='+str(uuid4() if not args.deployment_id else args.deployment_id)
            instances = run(base+['ec2', 'describe-instances', '--filters', tag, '--query',
                'Reservations[].Instances[].{id:InstanceId,state:State.Name,type:InstanceType,zone:Placement.AvailabilityZone,private:PrivateIpAddress,public:PublicIpAddress,vpc:VpcId,subnet:SubnetId,volumes:BlockDeviceMappings[].Ebs.VolumeId}'])
            for instance in instances or []:
                for attribute in ('instanceInitiatedShutdownBehavior','blockDeviceMapping','disableApiStop'):
                    run(base+['ec2','describe-instance-attribute','--instance-id',instance['id'],'--attribute',attribute])
                run(base+['ec2','describe-instance-credit-specifications','--instance-ids',instance['id']])
            run(base+['ec2', 'describe-volumes', '--filters', tag, '--query',
                'Volumes[].{id:VolumeId,encrypted:Encrypted,kms:KmsKeyId,size:Size,state:State,zone:AvailabilityZone,attachments:Attachments[].InstanceId}'])
            run(base+['ec2', 'describe-security-groups', '--filters', tag, '--query',
                'SecurityGroups[].{id:GroupId,vpc:VpcId,ingress:IpPermissions,egress:IpPermissionsEgress}'])
            run(base+['ec2', 'describe-availability-zones', '--query', 'AvailabilityZones[].{name:ZoneName,state:State,region:RegionName}'])
            run(base+['ec2','describe-regions','--region-names',args.region,'--query','Regions[].{name:RegionName,optIn:OptInStatus}'])
            run(base+['ec2','describe-instance-types','--instance-types','t3.medium','t3a.medium','t3.small',
                '--query','InstanceTypes[].{type:InstanceType,vcpu:VCpuInfo.DefaultVCpus,memoryMiB:MemoryInfo.SizeInMiB,freeTierEligible:FreeTierEligible}'])
            run(base+['ec2','describe-instance-type-offerings','--location-type','availability-zone',
                '--filters','Name=instance-type,Values=t3.medium,t3a.medium','--query','InstanceTypeOfferings'])
            # Read network identifiers only; existence does not grant permission to modify/reuse them.
            for api, query in (
                ('describe-vpcs','Vpcs[].{id:VpcId,cidr:CidrBlock,default:IsDefault,state:State}'),
                ('describe-subnets','Subnets[].{id:SubnetId,vpc:VpcId,zone:AvailabilityZone,zoneId:AvailabilityZoneId,cidr:CidrBlock,free:AvailableIpAddressCount,public:MapPublicIpOnLaunch}'),
                ('describe-route-tables','RouteTables[].{id:RouteTableId,vpc:VpcId,routes:Routes,associations:Associations}')):
                run(base+['ec2',api,'--query',query])
            run(base+['service-quotas', 'list-service-quotas', '--service-code', 'ec2', '--query',
                'Quotas[].{name:QuotaName,value:Value,code:QuotaCode}'], required=False)
            run(base+['freetier','get-free-tier-usage','--query','freeTierUsages'], required=False)
            run(base+['ec2','describe-images','--owners','099720109477','--filters',
                'Name=name,Values=ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*',
                'Name=state,Values=available','--query',
                'sort_by(Images,&CreationDate)[-1].{id:ImageId,owner:OwnerId,name:Name,root:RootDeviceName,blocks:BlockDeviceMappings,products:ProductCodes}'], required=False)
            report['permission_scope'] = 'Solo APIs leidas; RunInstances/StopInstances y cuotas restantes no acreditados'
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
    if report['commands'] and all(c.get('status') == 'EJECUTADO' for c in report['commands'] if c.get('required',True)) and not report['missing']:
        report['status'] = 'LECTURA_VERIFICADA'
    report['end'] = datetime.now(timezone.utc).isoformat()
    report['deployment_acceptance'] = 'PENDIENTE: lectura no acredita presupuesto, aprovisionamiento ni acceso externo'
    atomic_json(args.output, report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--provider', choices=('aws', 'gcp'), default='aws')
    p.add_argument('--profile', default='academy')
    for key in ('account', 'region', 'deployment-id'):
        p.add_argument('--'+key)
    p.add_argument('--output', type=Path, default=Path('.runtime/academy/preflight.json'))
    args = p.parse_args(); report = inspect(args)
    print(json.dumps(dict(status=report['status'], evidence=str(args.output), missing=report['missing'])))
    return 0 if report['status'] == 'LECTURA_VERIFICADA' else 2


if __name__ == '__main__':
    raise SystemExit(main())
