"""Regresión H1 y E4, contratos y evidencias fechadas; --measure agrega medición real."""
import argparse
from datetime import datetime, timezone
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
from runtime import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measure', action='store_true')
    args = parser.parse_args()
    directory = ROOT / 'docs/evidencias/etapa4' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory.mkdir(parents=True)
    report = dict(status='PENDIENTE', python=sys.version, platform=platform.platform(), sqlite=sqlite3.sqlite_version,
        packages={x.metadata['Name']: x.version for x in importlib.metadata.distributions()}, commands=[])
    commands = [[sys.executable, '-m', 'pip', 'check'], [sys.executable, 'scripts/generate_proto.py', '--check'],
        [sys.executable, '-m', 'pytest', '-q', '--ignore-glob=tests/test_stage7*.py', '--ignore=tests/test_stage5.py', '--ignore=tests/test_stage6.py', '--junitxml=' + str(directory / 'pytest.xml')],
        [sys.executable, 'scripts/audit_stage2.py', '--evidence', str(directory / 'audit.json')]]
    if args.measure:
        commands.append([sys.executable, 'scripts/measure_hito2.py', '--evidence', str(directory / 'measurement.json')])
    for command in commands:
        print(subprocess.list2cmdline(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
            env=dict(os.environ, PYTHONUTF8='1'))
        report['commands'].append(dict(argv=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
        print(result.stdout[-4000:], flush=True)
        (directory / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        if result.returncode:
            report['status'] = 'FALLIDO'
            break
    else:
        report['status'] = 'EJECUTADO'
    xml = directory / 'pytest.xml'
    if xml.exists():
        report['tests'] = ET.parse(xml).getroot().find('testsuite').attrib
    files = [ROOT / 'pyproject.toml', ROOT / 'requirements.lock']
    for folder in ('src', 'proto', 'scripts', 'tests', 'deploy'):
        files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and
                     not any(part.endswith('.egg-info') for part in p.parts))
    report['source_sha256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
    (directory / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(directory))))
    return 0 if report['status'] == 'EJECUTADO' else 1


if __name__ == '__main__':
    raise SystemExit(main())
