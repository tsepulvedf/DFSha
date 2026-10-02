#!/usr/bin/env bash
# Dedicated NEW academic VM only. Does not provision, format or delete a disk.
set -euo pipefail
umask 077
[[ $(id -u) == 0 ]] || { echo 'Root required for installation only'; exit 2; }
[[ $# == 3 ]] || { echo 'Usage: install-host.sh BUNDLE WHEEL ETCD_DIRECTORY'; exit 2; }
bundle=$(realpath -- "$1")
wheel=$(realpath -- "$2")
etcd_bin=$(realpath -- "$3")
for command in python3.12 systemctl nft findmnt timedatectl sshd; do command -v "$command" >/dev/null; done
# No automatic mounting/formatting; operator must verify encrypted cloud disks first.
mountpoint -q /var/lib/dfsha || { echo 'Persistent data mount required at /var/lib/dfsha'; exit 2; }
python3.12 - "$bundle" "$wheel" <<'PY'
import hashlib,json,pathlib,sys
b=pathlib.Path(sys.argv[1]); r=json.loads((b/'bundle.json').read_text())
assert r['provisionable'], 'Provider attestation missing'
assert hashlib.file_digest(open(sys.argv[2],'rb'),'sha256').hexdigest()==r['artifact_sha256'], 'Wheel hash mismatch'
old=pathlib.Path('/etc/dfsha/provisioned.json')
assert not old.exists() or json.loads(old.read_text())['deployment_id']==r['deployment_id'], 'Foreign deployment'
for p in ('/etc/dfsha','/var/lib/dfsha','/opt/dfsha'):
 assert not pathlib.Path(p).is_symlink(), 'Symlink storage forbidden'
PY
# This script does not overwrite volumes, inventories, keys or existing installations.
[[ ! -e /etc/dfsha/provisioned.json ]] || { echo 'Already installed; use explicit update procedure'; exit 2; }
[[ ! -e /opt/dfsha/venv ]] || { echo 'Existing installation requires review'; exit 2; }
[[ -f "$bundle/requirements.lock" ]] || { echo 'Locked dependencies required in bundle'; exit 2; }
[[ -f "$bundle/etcd-sha256.json" ]] || { echo 'Pinned binary hashes required'; exit 2; }
python3.12 - "$bundle/etcd-sha256.json" "$etcd_bin" <<'PY'
import hashlib,json,pathlib,sys
expected=json.loads(pathlib.Path(sys.argv[1]).read_text())
for name in ('etcd','etcdctl','etcdutl'):
 assert hashlib.sha256((pathlib.Path(sys.argv[2])/name).read_bytes()).hexdigest()==expected[name], 'etcd binary hash mismatch'
PY
install -d -m 0755 /opt/dfsha /opt/dfsha/etcd /etc/dfsha
install -d -m 0700 /etc/dfsha/admin
python3.12 -m venv /opt/dfsha/venv
/opt/dfsha/venv/bin/python -m pip install --require-hashes -r "$bundle/requirements.lock"
/opt/dfsha/venv/bin/python -m pip install --no-deps "$wheel"
/opt/dfsha/venv/bin/python -m pip check
for role in control data etcd; do
  id "dfsha-$role" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "dfsha-$role"
  install -d -o "dfsha-$role" -g "dfsha-$role" -m 0700 "/var/lib/dfsha/$role"
  install -d -o root -g "dfsha-$role" -m 0750 "/etc/dfsha/secrets/$role"
  install -m 0644 "$bundle/dfsha-$role.service" "/etc/systemd/system/dfsha-$role.service"
done
for name in etcd etcdctl etcdutl; do install -m 0755 "$etcd_bin/$name" "/opt/dfsha/etcd/$name"; done
for name in control.toml data.toml etcd.json infrastructure.json authorized-nodes.json control-identities.json; do
  install -m 0644 "$bundle/$name" "/etc/dfsha/$name"
done
# Dedicated-host controls, no changes to a workstation or other deployment.
install -d /etc/systemd/coredump.conf.d /etc/systemd/journald.conf.d /etc/ssh/sshd_config.d
printf '[Coredump]\nStorage=none\nProcessSizeMax=0\n' > /etc/systemd/coredump.conf.d/dfsha.conf
printf '[Journal]\nSystemMaxUse=128M\nRuntimeMaxUse=32M\nMaxRetentionSec=7day\n' > /etc/systemd/journald.conf.d/dfsha.conf
printf 'PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n' > /etc/ssh/sshd_config.d/00-dfsha.conf
sshd -t
timedatectl set-ntp true
systemctl daemon-reload
install -m 0600 "$bundle/bundle.json" /etc/dfsha/provisioned.json
install -m 0600 "$bundle/firewall.nft" /etc/dfsha/firewall.nft
nft --check --file /etc/dfsha/firewall.nft
install -d -m 0755 /opt/dfsha/admin
for name in cloud_host.py cloud_bundle.py cloud_initialize.py runtime.py; do
  install -m 0644 "$bundle/$name" "/opt/dfsha/admin/$name"
done
cat > /etc/systemd/system/dfsha-firewall.service <<'EOF'
[Unit]
Description=DFSha dedicated-host firewall
Before=dfsha-etcd.service dfsha-control.service dfsha-data.service
[Service]
Type=oneshot
ExecStart=/opt/dfsha/venv/bin/python /opt/dfsha/admin/cloud_host.py firewall
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
echo 'Installed, NOT started. Verify host identity, provision role secrets, initialize etcd/RBAC, activate epoch and apply firewall explicitly.'
echo 'SSH policy requires reload and an independent successful login before closing the administrative session.'
