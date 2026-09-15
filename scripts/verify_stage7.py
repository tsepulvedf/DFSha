"""Verificación E7 con procesos reales; alcance y omisiones explícitos."""
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
    parser.add_argument('--ha-only', action='store_true', help='Solo E7; no acredita regresión H1/H2/E5/E6')
    args = parser.parse_args()
    directory = ROOT / 'docs/evidencias/etapa7' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    directory.mkdir(parents=True)
    report = dict(status='PENDIENTE', python=sys.version, platform=platform.platform(), sqlite=sqlite3.sqlite_version,
        packages={x.metadata['Name']: x.version for x in importlib.metadata.distributions()}, commands=[], ha_only=args.ha_only)
    commands = [[sys.executable, '-m', 'pip', 'check'], [sys.executable, 'scripts/generate_proto.py', '--check'],
        [sys.executable, '-m', 'pytest', '-v', *(['tests/test_block_path_race.py', 'tests/test_control_failover_transport.py', 'tests/test_stage7_metadata.py', 'tests/test_stage7_control.py', 'tests/test_stage7_authorization.py'] if args.ha_only else ['tests']), '--junitxml=' + str(directory / 'pytest.xml')],
        [sys.executable, 'scripts/audit_stage2.py', '--evidence', str(directory / 'audit.json')]]
    if args.measure:
        commands.append([sys.executable, 'scripts/measure_stage7.py', '--evidence', str(directory / 'measurement.json')])
    try:
        for index, command in enumerate(commands):
            print(subprocess.list2cmdline(command), flush=True)
            stdout_path, stderr_path = directory/f'command-{index}.stdout.txt', directory/f'command-{index}.stderr.txt'
            current = dict(argv=command, exit_code=None, stdout_file=stdout_path.name, stderr_file=stderr_path.name)
            report['commands'].append(current)
            # Keep an honest recovery point even if this supervisor is killed.
            (directory/'result.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
            with stdout_path.open('wb') as output, stderr_path.open('wb') as errors:
                result = subprocess.run(command, cwd=ROOT, stdout=output, stderr=errors,
                    env=dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1'))
            current.update(exit_code=result.returncode, stdout=stdout_path.read_text(encoding='utf-8', errors='replace'),
                stderr=stderr_path.read_text(encoding='utf-8', errors='replace'))
            print(current['stdout'][-5000:], flush=True)
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
