"""Build identified wheel and stage pinned Linux etcd/tools; never provision a VM."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
from runtime import ROOT


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args();out=args.output.resolve()
    if out.exists():raise FileExistsError('Use una raíz nueva')
    out.mkdir(parents=True)
    subprocess.run([sys.executable,str(ROOT/'scripts/fetch_etcd.py'),'--platform','linux-amd64','--tools'],check=True)
    subprocess.run([sys.executable,'-m','build','--wheel','--no-isolation','--outdir',str(out)],cwd=ROOT,check=True)
    binaries=out/'etcd';binaries.mkdir()
    hashes={}
    for name in ('etcd','etcdctl','etcdutl'):
        source=ROOT/'.tools/etcd-3.6.14/linux-amd64'/name
        shutil.copyfile(source,binaries/name);hashes[name]=hashlib.sha256(source.read_bytes()).hexdigest()
    (out/'etcd-sha256.json').write_text(json.dumps(hashes,indent=2))
    wheel=next(out.glob('*.whl'))
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    report=dict(status='ARTEFACTO_LOCAL',base_commit=commit,
        dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
        wheel=wheel.name,sha256=hashlib.sha256(wheel.read_bytes()).hexdigest(),etcd=hashes)
    (out/'artifact.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))


if __name__=='__main__':main()
