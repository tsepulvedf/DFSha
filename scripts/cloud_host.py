"""E9 Linux host inspection/activation. No disk formatting and no secret output."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib
from uuid import UUID

from cloud_bundle import toml


def inspect():
    report = {'platform':os.name,'status':'PENDIENTE','commands':[]}
    if os.name != 'posix':
        report['status']='BLOQUEADO_POR_ENTORNO';return report
    commands=[['id'],['findmnt','--json','-T','/var/lib/dfsha'],['findmnt','--json','-T','/etc/dfsha/secrets'],
        ['timedatectl','show','-p','NTPSynchronized'],['swapon','--show','--noheadings'],
        ['ss','-lnt'],['systemctl','show','dfsha-control','dfsha-data','dfsha-etcd',
            '-p','ActiveState','-p','User','-p','MemoryCurrent','-p','MemoryPeak','-p','CPUUsageNSec','-p','LimitCORE'],
        ['nft','list','table','inet','dfsha']]
    for command in commands:
        p=subprocess.run(command,capture_output=True,text=True,timeout=15)
        report['commands'].append(dict(argv=command,exit_code=p.returncode,stdout=p.stdout))
    report['paths']={str(p):{'mode':oct(p.stat().st_mode & 0o777),'uid':p.stat().st_uid,'gid':p.stat().st_gid}
        for p in Path('/etc/dfsha/secrets').rglob('*') if p.exists()}
    report['status']='INSPECCION_EJECUTADA_NO_CERTIFICACION'
    return report


def activate(epoch, config_root=Path('/etc/dfsha')):
    UUID(epoch)
    marker=config_root/'activation.json'
    if marker.exists():
        if json.loads(marker.read_text())['epoch'] != epoch:
            raise ValueError('No cambiar época al reiniciar; requiere transición administrativa')
        return {'status':'ALREADY_ACTIVATED','epoch':epoch}
    if not json.loads((config_root/'provisioned.json').read_text())['provisionable']:
        raise ValueError('Infraestructura no verificada')
    for name in ('control.toml','data.toml'):
        path=config_root/name;cfg=tomllib.loads(path.read_text())
        section=cfg.get('distributed',cfg.get('datanode'))
        section['service_epoch']=epoch
        pending=path.with_suffix('.pending');pending.write_text(toml(cfg));os.replace(pending,path)
    pending=marker.with_suffix('.pending');pending.write_text(json.dumps({'epoch':epoch}));os.replace(pending,marker)
    return {'status':'ACTIVATED_NOT_STARTED','epoch':epoch}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('inspect','activate','start','stop','status','firewall'))
    p.add_argument('--epoch');p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.action=='inspect':result=inspect()
    elif args.action=='activate':result=activate(args.epoch)
    elif args.action=='firewall':
        # Atomic replacement of this table only; never flush rules from another owner.
        existing=subprocess.run(['nft','list','table','inet','dfsha'],capture_output=True).returncode==0
        rules=('delete table inet dfsha\n' if existing else '')+Path('/etc/dfsha/firewall.nft').read_text()
        subprocess.run(['nft','--check','-f','-'],input=rules,text=True,check=True)
        subprocess.run(['nft','-f','-'],input=rules,text=True,check=True)
        result={'status':'FIREWALL_APPLIED','persistence':'PENDIENTE: install service after independent SSH validation'}
    else:
        if args.action=='start' and not Path('/etc/dfsha/activation.json').exists():
            raise ValueError('Bootstrap/epoch not activated')
        units=['dfsha-etcd','dfsha-control','dfsha-data']
        if args.action=='stop':units.reverse()
        p=subprocess.run(['systemctl',args.action,*units],check=False)
        result={'exit_code':p.returncode,'action':args.action}
    if args.output:args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result))


if __name__=='__main__':main()
