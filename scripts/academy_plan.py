"""Generate EC2 requests only. Never launches instances or treats a JSON file as spending approval."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from uuid import UUID
from academy_window import render as window


def render(plan, output, now=None):
    if 'REPLACE' in json.dumps(plan):raise ValueError('Completar acceso, AMI y red verificados antes de generar')
    UUID(plan['deployment_id'])
    if plan['profile']!='academy' or not re.fullmatch(r'\d{12}',plan['account']):raise ValueError('Cuenta Academy explicita requerida')
    if plan['instance_type'] not in ('t3.medium','t3a.medium'):raise ValueError('Minimo preparado: amd64 2 vCPU / 4 GiB')
    if len(plan['nodes'])!=3 or {n['slot'] for n in plan['nodes']}!={'a','b','c'}:raise ValueError('Tres VMs independientes')
    for key,pattern in [('region',r'[a-z]{2}-[a-z]+-\d'),('image_id',r'ami-[a-f0-9]{8,17}'),('security_group',r'sg-[a-f0-9]{8,17}')]:
        if not re.fullmatch(pattern,plan[key]):raise ValueError('Identificador invalido: '+key)
    if not re.fullmatch(r'/dev/[a-z0-9]+',plan['root_device']):raise ValueError('Root device de la AMI requerida')
    for n in plan['nodes']:
        if not re.fullmatch(r'subnet-[a-f0-9]{8,17}',n['subnet_id']):raise ValueError('Subred verificada requerida')
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    result=window(plan['deadline_utc'],out/'window',now)
    userdata=base64.b64encode((out/'window/user-data.yaml').read_bytes()).decode()
    (out/'resume-user-data.json').write_text(json.dumps({'Value':userdata})+'\n',encoding='utf-8')
    for n in plan['nodes']:
        tags=[{'Key':'DFShaDeployment','Value':plan['deployment_id']},{'Key':'DFShaSlot','Value':n['slot']},
              {'Key':'Name','Value':'dfsha-'+n['slot']},{'Key':'DFShaDeadlineUTC','Value':plan['deadline_utc']}]
        request=dict(ImageId=plan['image_id'],InstanceType=plan['instance_type'],MinCount=1,MaxCount=1,
            KeyName=plan['key_name'],ClientToken=plan['deployment_id']+'-'+n['slot'],
            CreditSpecification={'CpuCredits':'standard'},InstanceInitiatedShutdownBehavior='stop',
            DisableApiTermination=True,MaintenanceOptions={'AutoRecovery':'disabled'},
            Monitoring={'Enabled':False},MetadataOptions={'HttpTokens':'required','HttpEndpoint':'enabled','HttpPutResponseHopLimit':1},
            NetworkInterfaces=[{'DeviceIndex':0,'SubnetId':n['subnet_id'],'Groups':[plan['security_group']],
                                'AssociatePublicIpAddress':True,'DeleteOnTermination':True}],
            BlockDeviceMappings=[{'DeviceName':dev,'Ebs':{'VolumeSize':size,'VolumeType':'gp3','Encrypted':True,
                'Iops':3000,'Throughput':125,'DeleteOnTermination':False}} for dev,size in ((plan['root_device'],16),('/dev/sdf',12))],
            TagSpecifications=[{'ResourceType':kind,'Tags':tags} for kind in ('instance','volume')])
        (out/(n['slot']+'.json')).write_text(json.dumps(request,indent=2)+'\n',encoding='utf-8')
    result.update(status='PLAN_NO_EJECUTADO_NO_AUTORIZADO',account=plan['account'],profile=plan['profile'],
        region=plan['region'],root_gib_per_vm=16,data_gib_per_vm=12,created_resources=[],
        required_launch_argument='--user-data file://'+(out/'window/user-data.yaml').as_posix())
    (out/'plan-result.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(render(json.loads(a.plan.read_text(encoding='utf-8')),a.output)))
