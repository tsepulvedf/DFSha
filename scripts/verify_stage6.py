"""Regresión H1/H2/E5/E6 y medición real R3/W2; no cuenta pruebas omitidas."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
import platform
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from runtime import ROOT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--measure', action='store_true')
    parser.add_argument('--replication-only', action='store_true', help='Solo E6; no acredita regresión H1/H2/E5')
    args = parser.parse_args()
    directory = ROOT / 'docs/evidencias/etapa6' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory.mkdir(parents=True)
    report = dict(status='PENDIENTE', python=sys.version, platform=platform.platform(), sqlite=sqlite3.sqlite_version,
        packages={x.metadata['Name']: x.version for x in importlib.metadata.distributions()}, commands=[], replication_only=args.replication_only)
    commands = [[sys.executable, '-m', 'pip', 'check'], [sys.executable, 'scripts/generate_proto.py', '--check'],
        [sys.executable, '-m', 'pytest', '-q', '--ignore-glob=tests/test_stage7*.py', 'tests/test_stage6.py' if args.replication_only else 'tests', '--junitxml=' + str(directory / 'pytest.xml')],
        [sys.executable, 'scripts/audit_stage2.py', '--evidence', str(directory / 'audit.json')]]
    if args.measure:
        commands.append([sys.executable, 'scripts/measure_stage6.py', '--evidence', str(directory / 'measurement.json')])
    try:
        for command in commands:
            print(subprocess.list2cmdline(command), flush=True)
            result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace',
                env=dict(os.environ, PYTHONUTF8='1'))
            report['commands'].append(dict(argv=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
            print(result.stdout[-5000:], flush=True)
            if result.returncode:
                report['status'] = 'FALLIDO'
                break
        else:
            report['status'] = 'EJECUTADO'
    finally:
        if (directory / 'pytest.xml').exists():
            report['tests'] = ET.parse(directory / 'pytest.xml').getroot().find('testsuite').attrib
        files = [ROOT / 'pyproject.toml', ROOT / 'requirements.lock']
        for folder in ('src', 'proto', 'scripts', 'tests', 'deploy'):
            files.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and
                         not any(x.endswith('.egg-info') for x in p.parts))
        report['source_sha256'] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
        (directory / 'result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(directory))))
    return int(report['status'] != 'EJECUTADO')


if __name__ == '__main__':
    raise SystemExit(main())
