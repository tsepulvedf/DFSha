"""Regresión completa E2 + RF1/RF2 y evidencia sanitizada. Medición opcional separada."""
from datetime import datetime, timezone
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measure', action='store_true')
    args = parser.parse_args()
    directory = ROOT / 'docs/evidencias/etapa3' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory.mkdir(parents=True)
    report = dict(status='PENDIENTE', python=sys.version, platform=platform.platform(), sqlite=sqlite3.sqlite_version,
                  packages={d.metadata['Name']: d.version for d in importlib.metadata.distributions()}, commands=[])
    commands = [
        [sys.executable, '-m', 'pip', 'check'],
        [sys.executable, 'scripts/generate_proto.py', '--check'],
        [sys.executable, '-m', 'pytest', '-q', '--ignore=tests/test_hito2.py', '--ignore=tests/test_stage5.py', f'--junitxml={directory / "pytest.xml"}'],
        [sys.executable, 'scripts/audit_stage2.py', '--evidence', str(directory / 'auditoria.json')],
    ]
    if args.measure:
        commands.append([sys.executable, 'scripts/measure_hito1.py', '--evidence', str(directory / 'medicion.json')])
    for command in commands:
        print(subprocess.list2cmdline(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
                                env=dict(os.environ, PYTHONUTF8='1'))
        report['commands'].append(dict(argv=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
        print(result.stdout[-2000:], flush=True)
        (directory / 'resultado.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if result.returncode:
            report['status'] = 'FALLIDO'
            break
    else:
        report['status'] = 'EJECUTADO'
    xml = directory / 'pytest.xml'
    if xml.exists():
        report['tests'] = ET.parse(xml).getroot().find('testsuite').attrib
    files = [ROOT / 'pyproject.toml', ROOT / 'requirements.lock']
    for name in ('src', 'tests', 'scripts', 'proto', 'deploy', 'third_party'):
        files.extend(p for p in (ROOT / name).rglob('*') if p.is_file() and '__pycache__' not in p.parts and
                     not any(part.endswith('.egg-info') for part in p.parts))
    report['source_sha256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    (directory / 'resultado.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(directory))))
    return 0 if report['status'] == 'EJECUTADO' else 1


if __name__ == '__main__':
    raise SystemExit(main())
