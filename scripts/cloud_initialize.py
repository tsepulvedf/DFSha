"""One-time etcd RBAC and protected metadata activation, from VM A administrative area."""
import argparse
import hashlib
import json
from pathlib import Path
import tomllib

from dfsha._vendor.etcd.api.etcdserverpb import rpc_pb2 as pb, rpc_pb2_grpc as api
from dfsha._vendor.etcd.api.authpb import auth_pb2 as auth
from dfsha.common.etcd_probe_client import EtcdProbeClient, prefix_end
from dfsha.common.protected import MetadataCipher
from dfsha.control.etcd_metadata import EtcdMetadataStore
from dfsha.control.migration import migrate


def initialize(config=Path('/etc/dfsha/control.toml'), admin=Path('/etc/dfsha/admin')):
    cfg=tomllib.loads(config.read_text())['distributed']
    identities=list(json.loads((config.parent/'control-identities.json').read_text()))
    prefix=(cfg['etcd_prefix']+'/').encode()
    with EtcdProbeClient(cfg['etcd_endpoints'][0],admin,'etcd-root') as root:
        status=root.auth.AuthStatus(pb.AuthStatusRequest(),timeout=5)
        if not status.enabled:
            # Requires a fresh cluster: stale partial bootstrap is reviewed explicitly.
            root.auth.UserAdd(pb.AuthUserAddRequest(name='root',options=auth.UserAddOptions(no_password=True)),timeout=5)
            root.auth.UserGrantRole(pb.AuthUserGrantRoleRequest(user='root',role='root'),timeout=5)
            root.auth.RoleAdd(pb.AuthRoleAddRequest(name='dfsha-service'),timeout=5)
            root.auth.RoleGrantPermission(pb.AuthRoleGrantPermissionRequest(name='dfsha-service',perm=auth.Permission(
                permType=auth.Permission.READWRITE,key=prefix,range_end=prefix_end(prefix))),timeout=5)
            for identity in identities:
                root.auth.UserAdd(pb.AuthUserAddRequest(name=identity,options=auth.UserAddOptions(no_password=True)),timeout=5)
                root.auth.UserGrantRole(pb.AuthUserGrantRoleRequest(user=identity,role='dfsha-service'),timeout=5)
            root.auth.AuthEnable(pb.AuthEnableRequest(),timeout=5)
        members=api.ClusterStub(root.channel).MemberList(pb.MemberListRequest(),timeout=5)
        if len(members.members)!=3:raise ValueError('Exigir tres miembros del mismo clúster')
    store=EtcdMetadataStore(cfg)
    try:
        if store.range(store.root_key):
            with store.transaction() as tx:
                system=tx.get('settings','system')
                if system['key_sha256']!=hashlib.sha256(Path(cfg['key_path']).read_bytes()).hexdigest():
                    raise ValueError('Autoridad existente no corresponde a estas claves')
                return dict(status='ALREADY_INITIALIZED',epoch=system['epoch'])
        return migrate(admin/'bootstrap.sqlite3',admin/'bootstrap-backup.sqlite3',store,MetadataCipher.configured(cfg))
    finally:store.channel.close()


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args(); result=initialize();args.output.write_text(json.dumps(result,indent=2));print(json.dumps(result))
