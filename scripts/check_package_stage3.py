"""Verificar wheel H1 en un venv de comprobación existente, sin reinstalar el stack."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', type=Path, required=True, help='Python del venv limpio de comprobación')
    parser.add_argument('--evidence', type=Path, default=ROOT / 'docs/evidencias/etapa3/paquete.json')
    args = parser.parse_args()
    directory = ROOT / 'build/wheels/etapa3'
    python = str(args.python.resolve())
    commands = [
        [sys.executable, '-m', 'build', '--no-isolation', '--wheel', '--outdir', str(directory)],
        [python, '-m', 'pip', 'install', '--no-deps', '--force-reinstall', str(directory / 'dfsha-0.3.0-py3-none-any.whl')],
        [python, '-m', 'pip', 'check'],
        [python, '-I', str(ROOT / 'scripts/check_imports.py'), '--require-installed'],
        [python, '-I', '-m', 'dfsha.client.cli', '--help'],
        [python, '-I', '-m', 'dfsha.admin', '--help'],
        [python, '-I', '-m', 'dfsha.datanode.server', '--help'],
    ]
    report = dict(status='PENDIENTE', scope='wheel H1 instalado sin editable; dependencias E2 reutilizadas', commands=[])
    for command in commands:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding='utf-8', errors='replace')
        report['commands'].append(dict(argv=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
        if result.returncode:
            report['status'] = 'FALLIDO'
            break
    else:
        report['status'] = 'EJECUTADO'
    evidence = args.evidence
    evidence.parent.mkdir(parents=True, exist_ok=True)
    evidence.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], evidence=str(evidence))))
    return 0 if report['status'] == 'EJECUTADO' else 1


if __name__ == '__main__':
    raise SystemExit(main())
