"""Render an absolute, persistent per-VM stop deadline. Does not call AWS or power off this host."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def expiry(deadline, now=None):
    value=datetime.fromisoformat(deadline.replace('Z','+00:00'))
    if value.tzinfo is None:raise ValueError('Deadline requiere zona UTC explicita')
    return value <= (now or datetime.now(timezone.utc))


GUARD = '''#!/usr/bin/python3
import json,sys,subprocess
from datetime import datetime,timezone
from pathlib import Path
try:
    d=json.loads(Path('/etc/dfsha-window.json').read_text())
    expired=datetime.now(timezone.utc).timestamp() >= d['deadline_unix']
except Exception:
    expired=True
if expired:
    # Orderly EC2 OS shutdown; RunInstances must explicitly set shutdown behavior=stop.
    subprocess.run(['/usr/bin/systemctl','--no-block','poweroff'],check=True)
    sys.exit(1)
'''

REFRESH = '''#!/usr/bin/python3
# Run only at boot as root. Updating EC2 user-data requires explicit administrative access.
import json,re,urllib.request,os
from datetime import datetime,timezone
from pathlib import Path
req=urllib.request.Request('http://169.254.169.254/latest/api/token',method='PUT',headers={'X-aws-ec2-metadata-token-ttl-seconds':'60'})
with urllib.request.urlopen(req,timeout=3) as r: token=r.read().decode()
req=urllib.request.Request('http://169.254.169.254/latest/user-data',headers={'X-aws-ec2-metadata-token':token})
with urllib.request.urlopen(req,timeout=3) as r: data=r.read(65536).decode()
matches=re.findall(r'^# DFSHA_DEADLINE_UNIX=([0-9]{10})$',data,re.M)
if len(matches)!=1: raise ValueError('Invalid window metadata')
deadline=int(matches[0]); now=datetime.now(timezone.utc).timestamp()
if deadline-now>8*3600: raise ValueError('Window exceeds eight hours')
p=Path('/etc/dfsha-window.json.pending')
p.write_text(json.dumps({'deadline_unix':deadline}))
os.chmod(p,0o644);os.replace(p,'/etc/dfsha-window.json')
'''


def render(deadline, output, now=None):
    now=now or datetime.now(timezone.utc)
    end=datetime.fromisoformat(deadline.replace('Z','+00:00'))
    if end.tzinfo is None or not 0 < (end-now).total_seconds() <= 8*3600:
        raise ValueError('Ventana futura explicita de hasta ocho horas; no autoriza gasto')
    out=Path(output);out.mkdir(parents=True,exist_ok=False)
    files={
      '/etc/dfsha-window.json':json.dumps({'deadline_unix':int(end.timestamp()),'deadline':end.isoformat()}),
      '/usr/local/sbin/dfsha-window-check':GUARD,
      '/usr/local/sbin/dfsha-window-refresh':REFRESH,
      '/etc/systemd/system/dfsha-window.service':'''[Unit]
Description=DFSha approved window guard (expired or unreadable -> poweroff)
Before=dfsha-etcd.service dfsha-control.service dfsha-data.service
[Service]
Type=oneshot
ExecStart=/usr/local/sbin/dfsha-window-check
[Install]
WantedBy=multi-user.target
''',
      '/etc/systemd/system/dfsha-window.timer':f'''[Unit]
Description=DFSha absolute laboratory deadline
[Timer]
OnCalendar={end.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC
OnBootSec=15s
OnUnitActiveSec=30s
Persistent=true
AccuracySec=1s
Unit=dfsha-window.service
[Install]
WantedBy=timers.target
'''}
    drop='[Unit]\nRequires=dfsha-window.timer\nAfter=dfsha-window.timer\n[Service]\nExecStartPre=/usr/local/sbin/dfsha-window-check\n'
    for role in ('etcd','control','data'):
        # Service users can check the nonsecret deadline. Only PID1/root guard powers off.
        files[f'/etc/systemd/system/dfsha-{role}.service.d/window.conf']=drop
    for name,data in files.items():
        target=out/name.lstrip('/');target.parent.mkdir(parents=True,exist_ok=True)
        target.write_text(data,encoding='utf-8',newline='\n')
    # cloud-init bootcmd runs every boot. No secrets, no AWS credentials, no paid scheduler.
    lines=['#cloud-config',f'# DFSHA_DEADLINE_UNIX={int(end.timestamp())}','bootcmd:',
           "  - [sh, -c, 'if [ -x /usr/local/sbin/dfsha-window-refresh ]; then /usr/local/sbin/dfsha-window-refresh || true; /usr/local/sbin/dfsha-window-check; fi']",'write_files:']
    for path,data in files.items():
        mode='0755' if '/sbin/' in path else '0644'
        lines += [f'  - path: {path}',f"    permissions: '{mode}'",'    owner: root:root','    content: |']
        lines += ['      '+line for line in data.splitlines()]
    lines += ['runcmd:','  - [systemctl, daemon-reload]',
              '  - [systemctl, enable, --now, dfsha-window.service, dfsha-window.timer]']
    (out/'user-data.yaml').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    return {'status':'PREPARADO_NO_INSTALADO','deadline':end.isoformat(),'files':len(files)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--deadline',required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();print(json.dumps(render(a.deadline,a.output)))
