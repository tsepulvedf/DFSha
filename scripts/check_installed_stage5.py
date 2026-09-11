"""RF3 real desde el wheel instalado en el entorno de comprobación, sin editable."""
import hashlib
import json
from pathlib import Path
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import dfsha
from hito2_runtime import Cluster
from dfsha.common.domain import CHUNK


def main():
    assert 'site-packages' in Path(dfsha.__file__).parts, dfsha.__file__
    root = ROOT / '.runtime/installed-e5' / str(uuid4())
    with Cluster(root, rf3=True) as lab:
        client = lab.client()
        try:
            source = root / 'source'
            with source.open('wb') as stream:
                for _ in range(32):
                    stream.write(b'A' * CHUNK)
            client.send(source, '/installed')
            writer = client.open('/installed', 'r+')
            reader = client.open('/installed')
            assert client.write(writer, 4194302, b'patch') == 5
            assert client.read(writer, 4194300, 9) == b'AApatchAA'
            assert client.read(reader, 4194300, 9) == b'A' * 9
            target = root / 'received'
            downloaded = client.receive('/installed', target)
            digest = hashlib.sha256()
            with target.open('rb') as stream:
                while chunk := stream.read(CHUNK):
                    digest.update(chunk)
            assert digest.hexdigest() == downloaded['sha256']
            client.close(writer)
            client.close(reader)
            report = dict(status='EJECUTADO', python=sys.executable, package=dfsha.__file__,
                bytes=8388608, delta_bytes=5, sha256=digest.hexdigest(), control_pid=lab.control.info['pid'],
                datanode_pids=[x.info['pid'] for x in lab.nodes[:3]], snapshots_verified=True)
        finally:
            client.shutdown()
    evidence = ROOT / 'docs/evidencias/etapa5/installed-smoke.json'
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(evidence))))


if __name__ == '__main__':
    main()
