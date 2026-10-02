"""Local guards only: mocked AWS responses do not establish account access or VM shutdown."""
from argparse import Namespace
import base64
import configparser
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import subprocess
from uuid import uuid4

import pytest
import cloud_preflight as preflight
from academy_profile import save
from academy_plan import render
from academy_window import render as render_window, GUARD, REFRESH, expiry
from academy_cost import estimate


def test_profile_requires_session_token_and_preserves_other_profiles(tmp_path):
    root=tmp_path/'.aws';root.mkdir()
    (root/'credentials').write_text('[other]\naws_access_key_id = existing\n')
    with pytest.raises(ValueError):save(tmp_path,'us-east-1','test-access','test-secret','')
    save(tmp_path,'us-east-1','test-access','test-secret','test-session')
    p=configparser.RawConfigParser();p.read(root/'credentials')
    assert p.get('other','aws_access_key_id')=='existing'
    assert preflight.profile_facts('academy',tmp_path)['temporary_credentials_complete']
    with pytest.raises(ValueError):save(tmp_path,'us-east-1','new','new','new')
    save(tmp_path,'us-east-1','new','new','new',refresh=True)
    p.read(root/'credentials');assert p.get('other','aws_access_key_id')=='existing'
    assert p.get('academy','aws_session_token')=='new'


def args(tmp_path):
    return Namespace(provider='aws',profile='academy',region='us-east-1',account='000000000000',
        deployment_id=str(uuid4()),output=tmp_path/'result.json')


@pytest.mark.parametrize('fault',('wrong_account','expired','missing_token','free_tier_denied'))
def test_preflight_does_not_confuse_access_with_benefit(monkeypatch,tmp_path,fault):
    calls=[]
    monkeypatch.setattr(preflight.shutil,'which',lambda name:name)
    monkeypatch.setattr(preflight,'profile_facts',lambda _:dict(configured=True,region=None,temporary_credentials_complete=fault!='missing_token'))
    def fake(command,**kw):
        calls.append(command)
        assert 'AWS_ACCESS_KEY_ID' not in kw['env']
        if 'sts' in command:
            if fault=='expired':return subprocess.CompletedProcess(command,255,'','ExpiredToken DO_NOT_PUBLISH')
            return subprocess.CompletedProcess(command,0,json.dumps({'Account':'111111111111' if fault=='wrong_account' else '000000000000'}),'')
        if 'freetier' in command:return subprocess.CompletedProcess(command,255,'','AccessDenied DO_NOT_PUBLISH')
        return subprocess.CompletedProcess(command,0,'[]','')
    monkeypatch.setattr(preflight.subprocess,'run',fake)
    monkeypatch.setenv('AWS_ACCESS_KEY_ID','DO_NOT_PUBLISH')
    report=preflight.inspect(args(tmp_path))
    assert 'DO_NOT_PUBLISH' not in (tmp_path/'result.json').read_text()
    assert report['economic_authorization'] is False
    if fault=='free_tier_denied':
        assert report['status']=='LECTURA_VERIFICADA'
        assert next(c for c in report['commands'] if 'freetier' in c['argv'])['reason']=='AccessDenied'
    else:
        assert report['status']=='BLOQUEADO_POR_ENTORNO'
        assert not any('ec2' in c for c in calls)


def test_plan_has_persistence_and_no_unlimited_or_paid_extras(tmp_path):
    now=datetime(2026,10,2,tzinfo=timezone.utc)
    p=dict(profile='academy',account='000000000000',deployment_id=str(uuid4()),region='us-east-1',
        image_id='ami-12345678',root_device='/dev/sda1',instance_type='t3.medium',security_group='sg-12345678',
        key_name='TEST_ONLY',deadline_utc=(now+timedelta(hours=4)).isoformat(),
        nodes=[dict(slot=s,subnet_id='subnet-12345678') for s in 'abc'])
    render(p,tmp_path/'plan',now)
    ids=set()
    for slot in 'abc':
        r=json.loads((tmp_path/'plan'/f'{slot}.json').read_text())
        ids.add(r['ClientToken']);assert r['CreditSpecification']['CpuCredits']=='standard'
        assert r['InstanceInitiatedShutdownBehavior']=='stop' and not r['Monitoring']['Enabled']
        assert sum(d['Ebs']['VolumeSize'] for d in r['BlockDeviceMappings'])==28
        assert all(d['Ebs']['Encrypted'] and not d['Ebs']['DeleteOnTermination'] for d in r['BlockDeviceMappings'])
        assert r['MetadataOptions']['HttpTokens']=='required'
        assert 'UserData' not in r  # CLI --user-data file://raw YAML handles base64 once.
        script=(tmp_path/'plan/window/user-data.yaml').read_text()
        assert base64.b64decode(json.loads((tmp_path/'plan/resume-user-data.json').read_text())['Value']).decode()==script
        assert 'Persistent=true' in script and 'dfsha-window-refresh' in script
        assert 'AWS_ACCESS_KEY' not in script and 'terminate-instances' not in script
    assert len(ids)==3
    with pytest.raises(FileExistsError):render(p,tmp_path/'plan',now)


@pytest.mark.parametrize('hours',(-1,0,9))
def test_window_rejects_invalid_duration(tmp_path,hours):
    now=datetime.now(timezone.utc)
    with pytest.raises(ValueError):render_window((now+timedelta(hours=hours)).isoformat(),tmp_path/'w',now)


@pytest.mark.parametrize('state',('valid','expired','missing'))
def test_guard_orders_poweroff_only_after_expiry_or_missing_state(monkeypatch,tmp_path,state):
    file=tmp_path/'window.json';calls=[]
    if state!='missing':file.write_text(json.dumps({'deadline_unix':datetime.now(timezone.utc).timestamp()+(300 if state=='valid' else -1)}))
    actual=Path.read_text
    monkeypatch.setattr(Path,'read_text',lambda self,*a,**kw:actual(file,*a,**kw))
    monkeypatch.setattr(subprocess,'run',lambda argv,**kw:calls.append(argv))
    if state=='valid':exec(compile(GUARD,'guard','exec'),{});assert not calls
    else:
        with pytest.raises(SystemExit):exec(compile(GUARD,'guard','exec'),{})
        assert calls==[['/usr/bin/systemctl','--no-block','poweroff']]


def test_cost_counts_three_hosts_and_stopped_storage():
    r=estimate();two=r['sessions'][0];eight=r['sessions'][2]
    assert two['instance_hours']==6 and eight['instance_hours']==24
    assert two['compute']==pytest.approx(.2508)
    assert r['stopped'][0]['ebs_usd']==pytest.approx(1.568)
    assert r['stopped'][1]['ebs_usd']==pytest.approx(6.72)
    assert not r['free_benefits_verified'] and r['verified_balance'] is None


@pytest.mark.parametrize('hours',(1,-1,9))
def test_boot_refresh_uses_absolute_authorized_deadline(monkeypatch,tmp_path,hours):
    import io
    import urllib.request
    deadline=int((datetime.now(timezone.utc)+timedelta(hours=hours)).timestamp())
    local=tmp_path/'window.json';local.write_text(json.dumps({'deadline_unix':1}))
    def response(req,**kwargs):
        if req.get_method()=='PUT':return io.BytesIO(b'fixture-token')
        assert req.get_header('X-aws-ec2-metadata-token')=='fixture-token'
        return io.BytesIO(f'#cloud-config\n# DFSHA_DEADLINE_UNIX={deadline}\n'.encode())
    monkeypatch.setattr(urllib.request,'urlopen',response)
    script=REFRESH.replace('/etc/dfsha-window.json',local.as_posix())
    if hours==9:
        with pytest.raises(ValueError):exec(compile(script,'refresh','exec'),{})
        assert json.loads(local.read_text())['deadline_unix']==1
    else:
        exec(compile(script,'refresh','exec'),{})
        assert json.loads(local.read_text())['deadline_unix']==deadline
        assert expiry(datetime.fromtimestamp(deadline,timezone.utc).isoformat())==(hours<0)
