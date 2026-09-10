"""Smoke distribuido desde wheel instalado, sin importar src/ ni usar editable."""
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))  # Sólo utilidades; nunca src/.
import dfsha
from hito2_runtime import Cluster
from runtime import PROCESS_FLAGS
from dfsha.common.domain import CHUNK


def main():
    assert 'site-packages' in Path(dfsha.__file__).parts, dfsha.__file__
    directory = ROOT / '.runtime/installed-h2' / str(uuid4())
    with Cluster(directory) as app:
        client = app.client()
        try:
            source = directory / 'source'
            with source.open('wb') as stream:
                for _ in range(32):
                    stream.write(b'a'*CHUNK)
            uploaded = client.send(source, '/installed')
            downloaded = client.receive('/installed', directory / 'output')
            assert downloaded['bytes'] == 8388608 and len(client.traffic) == 2
            assert bytes.fromhex(downloaded['sha256']) == uploaded.snapshot.file_sha256
            report = dict(status='EJECUTADO', python=sys.executable, package=dfsha.__file__,
                bytes=downloaded['bytes'], sha256=downloaded['sha256'], traffic=client.traffic,
                control_pid=app.control.info['pid'], datanode_pids=[x.info['pid'] for x in app.nodes[:3]])
        finally:
            client.shutdown()
    # Exercise the documented detached launcher and its stop signal with the same persisted volumes.
    for command in ('start', 'status', 'add-fourth', 'stop'):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/lab_hito2.py'), command, '--root', str(directory)],
            cwd=ROOT, capture_output=True, text=True, creationflags=PROCESS_FLAGS)
        assert result.returncode == 0, result.stderr
    report['launcher_commands'] = ['start', 'status', 'add-fourth', 'stop']
    evidence = ROOT / 'docs/evidencias/etapa4/installed-smoke.json'
    evidence.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(evidence))))


if __name__ == '__main__':
    main()
