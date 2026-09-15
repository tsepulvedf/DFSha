"""Smoke HA from the installed wheel, using the existing isolated toolchain."""
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import dfsha
from ha_runtime import HACluster


def main():
    assert 'site-packages' in Path(dfsha.__file__).parts, dfsha.__file__
    root = ROOT/'.runtime/installed-e7'/str(uuid4())
    with HACluster(root) as lab:
        a = lab.client()
        b = lab.client(1, a.session)
        try:
            source = root/'source'
            source.write_bytes(b'installed HA snapshot')
            a.send(source, '/installed')
            handle = a.open('/installed', 'r+')
            b.renew_handle(handle)
            assert b.write(handle, 0, b'HA') == 2
            assert a.read(handle, 0, 9) == b'HAstalled'
            b.close(handle)
            output = root/'received'
            a.receive('/installed', output)
            report = dict(status='EJECUTADO', package=dfsha.__file__, python=sys.executable,
                sha256=hashlib.sha256(output.read_bytes()).hexdigest(),
                controls=[p.info['pid'] for p in lab.controls], members=lab.etcd.status(),
                nodes=[p.info['pid'] for p in lab.nodes[:3]], shared_handle=True, target_replicas=3, minimum_durable=2)
        finally:
            a.shutdown()
            b.shutdown()
    evidence = ROOT/'docs/evidencias/etapa7/installed-smoke.json'
    evidence.write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(evidence))))


if __name__ == '__main__':
    main()
