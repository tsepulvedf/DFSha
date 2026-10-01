"""E8: recoverable execution journal, observed exits and atomic final report."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from uuid import uuid4

from runtime import ROOT


def utc():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    temporary = path.with_suffix('.pending')
    with temporary.open('w', encoding='utf-8', newline='\n') as out:
        json.dump(value, out, indent=2)
        out.write('\n')
        out.flush()
        os.fsync(out.fileno())
    os.replace(temporary, path)


def sources():
    files = [ROOT/'pyproject.toml', ROOT/'requirements.lock']
    for name in ('src', 'proto', 'tests', 'scripts', 'deploy'):
        files.extend(p for p in (ROOT/name).rglob('*') if p.is_file() and '__pycache__' not in p.parts
                     and not any(v.endswith('.egg-info') for v in p.parts))
    return {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--regression', action='store_true', help='Include all previous tests')
    parser.add_argument('--test', action='append', help='Select a pytest node/path; selection recorded explicitly')
    parser.add_argument('--measure', action='store_true', help='512 MiB protected HA with an ordinary user')
    parser.add_argument('--measure-only', action='store_true', help='Repeat interrupted measurement; tests are not counted again')
    args = parser.parse_args()
    if args.measure_only and (args.test or args.regression):
        parser.error('--measure-only cannot be combined with test selection or regression')
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+str(uuid4())[:8]
    directory = ROOT/'docs/evidencias/etapa8'/run_id
    private = ROOT/'.runtime/verification-e8'/run_id
    directory.mkdir(parents=True)
    private.mkdir(parents=True)
    report = dict(run_id=run_id, start=utc(), end=None, status='EN_CURSO', supervisor_pid=os.getpid(),
        argv=sys.argv, python=sys.version, platform=platform.platform(), source_sha256=sources(), commands=[],
        profile=platform.system()+' process simulation; protected HA; not hosts or Internet',
        scope='measurement-only' if args.measure_only else 'selection' if args.test else 'regression' if args.regression else 'stage8')
    commands = [[sys.executable, '-m', 'pip', 'check'],
                [sys.executable, 'scripts/generate_proto.py', '--check'],
                [sys.executable, '-m', 'pytest', '-v', *( args.test or (['tests'] if args.regression else
                    [str(p.relative_to(ROOT)) for p in sorted((ROOT/'tests').glob('test_stage8_*.py'))])),
                 '-p', 'stage8_journal', '--junitxml='+str(private/'pytest.xml')],
                [sys.executable, 'scripts/audit_stage2.py', '--evidence', str(directory/'catalog.json')]]
    env = dict(os.environ, PYTHONUTF8='1', PYTHONUNBUFFERED='1',
        PYTHONPATH=str(ROOT/'scripts')+os.pathsep+os.environ.get('PYTHONPATH', ''),
        DFSHA_TEST_JOURNAL=str(directory/'cases.jsonl'))
    if args.measure_only:
        commands = [command for command in commands if '-m' not in command or 'pytest' not in command]
    if args.measure or args.measure_only:
        commands.append([sys.executable, 'scripts/measure_stage7.py', '--protected', '--evidence', str(directory/'measurement.json')])
    try:
        for command in commands:
            entry = dict(argv=command, start=utc(), end=None, exit_code=None, status='EN_CURSO')
            report['commands'].append(entry)
            log = private/f'command-{len(report["commands"])}.log'
            entry['log'] = str(log)
            with log.open('wb') as out:
                child = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT, env=env,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                entry['pid'] = child.pid
                atomic_json(directory/'result.json', report)
                print(json.dumps(dict(run_id=run_id, pid=child.pid, command=command)), flush=True)
                entry['exit_code'] = child.wait()
            entry.update(end=utc(), status='APROBADO' if entry['exit_code'] == 0 else 'FALLIDO')
            atomic_json(directory/'result.json', report)
            print(json.dumps(dict(exit_code=entry['exit_code'], log=str(log))), flush=True)
            if entry['exit_code']:
                report['status'] = 'FALLIDO'
                break
        else:
            report['status'] = 'APROBADO'
    except BaseException:
        report['status'] = 'INTERRUMPIDO'
        raise
    finally:
        report['end'] = utc()
        report['source_unchanged'] = report['source_sha256'] == sources()
        if not report['source_unchanged']:
            report['status'] = 'CODIGO_MODIFICADO_DURANTE_EJECUCION'
        atomic_json(directory/'result.json', report)
        print(json.dumps(dict(status=report['status'], evidence=str(directory))), flush=True)
    return int(report['status'] != 'APROBADO')


if __name__ == '__main__':
    raise SystemExit(main())
