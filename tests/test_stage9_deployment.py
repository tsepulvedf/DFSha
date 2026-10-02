"""E9 preparation tests. Fixture host IDs never count as cloud deployment evidence."""
from copy import deepcopy
import json
from pathlib import Path
import tomllib
from uuid import uuid4

import pytest
from cryptography import x509
from cloud_bundle import validate, render, attest
from cloud_secrets import prepare
from cloud_host import activate
from dfsha.common.config import listener_address, read_config


def inventory():
    return dict(schema=1,status='TEST_FIXTURE_NOT_DEPLOYED',deployment_id=str(uuid4()),provider='aws',
        account_project='000000000000',region='test-region',private_cidr='10.83.0.0/24',
        admin_cidr='192.0.2.1/32',client_cidrs=['192.0.2.2/32'],budget_usd=5,duration_hours=8,
        artifact_commit='a'*40,artifact_sha256='b'*64,image_id='TEST_IMAGE',
        nodes=[dict(slot=slot,vm_id='TEST_VM_'+slot,zone='TEST_ZONE',private_ip='10.83.0.'+str(i+11),
            public_host='node-'+slot+'.example.invalid',control_id=str(uuid4()),node_id=str(uuid4()),
            volume_id='TEST_DISK_'+slot,capacity_bytes=21474836480) for i,slot in enumerate('abc')])


@pytest.mark.parametrize('fault',('placeholder','shared_vm','shared_volume','public_ssh','wrong_private','same_role','budget'))
def test_inventory_rejects_unsafe_or_incomplete(fault):
    cfg=inventory()
    if fault=='placeholder':cfg['image_id']='REPLACE_IMAGE'
    if fault=='shared_vm':cfg['nodes'][1]['vm_id']=cfg['nodes'][0]['vm_id']
    if fault=='shared_volume':cfg['nodes'][1]['volume_id']=cfg['nodes'][0]['volume_id']
    if fault=='public_ssh':cfg['admin_cidr']='0.0.0.0/0'
    if fault=='wrong_private':cfg['nodes'][0]['private_ip']='192.168.1.9'
    if fault=='same_role':cfg['nodes'][0]['control_id']=cfg['nodes'][0]['node_id']
    if fault=='budget':cfg['budget_usd']=None
    with pytest.raises((ValueError,TypeError)):validate(cfg)


def test_render_keeps_private_listeners_and_draft_disabled(tmp_path):
    cfg=inventory();out=tmp_path/'bundle';render(cfg,out)
    for n in cfg['nodes']:
        host=out/n['slot'];c=read_config(host/'control.toml');d=tomllib.loads((host/'data.toml').read_text())['datanode']
        assert c['server']['public_bind']=='0.0.0.0:7443'
        assert c['server']['client_endpoint']==n['public_host']+':7443'
        assert listener_address(d,True)==n['private_ip']+':7446'
        assert c['distributed']['default_replicas']==3 and len(c['distributed']['etcd_endpoints'])==3
        assert not json.loads((host/'bundle.json').read_text())['provisionable']
        assert json.loads((host/'infrastructure.json').read_text())=={'status':'UNVERIFIED'}
        unit=(host/'dfsha-control.service').read_text()
        assert 'User=dfsha-control' in unit and 'MemorySwapMax=0' in unit and 'LimitCORE=0' in unit
        firewall=(host/'firewall.nft').read_text()
        assert 'flush ruleset' not in firewall and 'policy drop' in firewall
    with pytest.raises(FileExistsError):render(cfg,out)


@pytest.mark.parametrize('change',({'internal_bind':'0.0.0.0:7446'}, {'metadata_key_path':''},
    {'private_cidr':'0.0.0.0/0'}, {'network_profile':'unknown'}, {'private_endpoint':'node.example:7446'}))
def test_vm_network_rejects_unsafe_settings(change):
    cfg=dict(network_profile='private-vm',metadata_key_path='key',private_cidr='10.83.0.0/24',
        internal_bind='10.83.0.11:7446',private_endpoint='10.83.0.11:7446')
    cfg.update(change)
    with pytest.raises(ValueError):listener_address(cfg,True)


def test_loopback_default_and_nat_address_rules():
    assert listener_address({'public_bind':'127.0.0.1:1234'},False)=='127.0.0.1:1234'
    with pytest.raises(ValueError):listener_address({'public_bind':'0.0.0.0:7443'},False)
    cfg=dict(network_profile='private-vm',metadata_key_path='key',private_cidr='10.83.0.0/24',
        public_bind='198.51.100.1:7443',client_endpoint='public.example:7443')
    with pytest.raises(ValueError):listener_address(cfg,False)


def test_attestation_requires_real_matching_observations():
    cfg=inventory()
    with pytest.raises(ValueError):attest(cfg,{'status':'UNVERIFIED'})
    commands=[dict(argv=['get-caller-identity'],result={'Account':cfg['account_project']}),
        dict(argv=['describe-instances'],result=[dict(id=n['vm_id'],private=n['private_ip'],zone=n['zone'],
            vpc='TEST_VPC',volumes=[n['volume_id']]) for n in cfg['nodes']]),
        dict(argv=['describe-volumes'],result=[dict(id=n['volume_id'],encrypted=True) for n in cfg['nodes']])]
    proof=dict(status='LECTURA_VERIFICADA',provider='aws',run_id='TEST_ONLY',commands=commands)
    assert len(attest(cfg,proof)['nodes'])==3
    commands[2]['result'][0]['encrypted']=False
    with pytest.raises(ValueError):attest(cfg,proof)


def test_private_material_has_real_sans_unique_keys_and_encrypted_seed(tmp_path):
    from dfsha.common.protected import MetadataCipher
    from dfsha.control.metadata import SQLiteMetadataStore
    cfg=inventory();root=tmp_path/'private';prepare(cfg,root,'fixture-only-password')
    public_keys=[]
    for n in cfg['nodes']:
        host=root/n['slot'];identity=n['control_id']
        cert=x509.load_pem_x509_certificate((host/'control'/(identity+'.crt')).read_bytes())
        san=cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
        assert n['public_host'] in san.get_values_for_type(x509.DNSName)
        assert n['private_ip'] in [str(v) for v in san.get_values_for_type(x509.IPAddress)]
        public_keys.append(cert.public_key().public_numbers())
        assert not list(host.rglob('ca.key'))
        store=SQLiteMetadataStore(host/'inventory.sqlite3',MetadataCipher((host/'data/inventory.key').read_bytes()))
        with store.transaction() as tx:assert tx.get('settings','node')['id_node']==n['node_id']
    assert len(set(public_keys))==3
    with pytest.raises(FileExistsError):prepare(cfg,root,'fixture-only-password')
    assert b'fixture-only-password' not in (root/'custodian/bootstrap.sqlite3').read_bytes()


def test_activation_never_changes_epoch_on_restart(tmp_path):
    cfg=inventory();out=tmp_path/'bundle';render(cfg,out)
    host=out/'a';(host/'provisioned.json').write_text(json.dumps({'provisionable':True}))
    epoch=str(uuid4());assert activate(epoch,host)['status']=='ACTIVATED_NOT_STARTED'
    assert activate(epoch,host)['status']=='ALREADY_ACTIVATED'
    with pytest.raises(ValueError):activate(str(uuid4()),host)
    assert tomllib.loads((host/'data.toml').read_text())['datanode']['service_epoch']==epoch


def test_rendered_etcd_security_config_real_three_members(run_dir):
    from ha_runtime import EtcdCluster
    from generate_certs import generate
    root=run_dir/'e9-etcd-json';root.mkdir();certs=root/'certs';generate(certs,peer_certificates=True)
    lab=EtcdCluster(root/'cluster',certs,identities=['dfsha-probe'])
    out=root/'bundle';render(inventory(),out)
    for i,member in enumerate(lab.members):
        flags=dict(a[2:].split('=',1) for a in member.args[1:])
        cfg=json.loads((out/'a/etcd.json').read_text())
        for k in ('name','data-dir','listen-client-urls','advertise-client-urls','listen-peer-urls',
                  'initial-advertise-peer-urls','initial-cluster','initial-cluster-token'):
            cfg[k]=flags[k]
        for section in ('client-transport-security','peer-transport-security'):
            cfg[section].update({'cert-file':str(certs/f'etcd-member-{i}.crt'),
                'key-file':str(certs/f'etcd-member-{i}.key'),'trusted-ca-file':str(certs/'ca.crt')})
        cfg['peer-transport-security']['allowed-cn']=['dfsha-etcd-member-0','dfsha-etcd-member-1','dfsha-etcd-member-2']
        path=root/f'm{i}.json';path.write_text(json.dumps(cfg));member.args=[member.args[0],'--config-file='+str(path)]
    with lab:
        state=lab.status()
        assert len({s['cluster'] for s in state})==1 and len({s['member'] for s in state})==3
        import http.client
        import ssl
        from urllib.parse import urlparse
        from test_stage8_etcd_security import request
        peer=json.loads((root/'m0.json').read_text())['listen-peer-urls']
        with pytest.raises((ssl.SSLError,ConnectionError,http.client.RemoteDisconnected)):
            request(urlparse(peer).netloc,certs,'etcd-probe')
        assert len(lab.status())==3
