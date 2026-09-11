"""Revisión local de cambios publicables: sin claves, volúmenes ni archivos gigantes."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from runtime import ROOT


def main():
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8').splitlines()
    paths = set(git('diff', '--name-only', 'HEAD')) | set(git('ls-files', '--others', '--exclude-standard'))
    failures, files = [], {}
    forbidden = {'.key', '.pem', '.p12', '.pfx', '.crt', '.csr', '.blk', '.db', '.sqlite', '.sqlite3'}
    key_pattern = re.compile(rb'-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----\r?\n[A-Za-z0-9+/=]{40,}')
    for relative in sorted(paths):
        if relative == 'docs/evidencias/etapa5/delivery-review.json':
            continue  # The report cannot contain a stable hash of itself.
        path = ROOT / relative
        if not path.is_file():
            continue
        if path.suffix.lower() in forbidden or any(part.startswith(('.venv', '.runtime')) for part in path.parts):
            failures.append(relative + ': forbidden runtime/secret type')
        if path.stat().st_size > 5 * 1024 * 1024:
            failures.append(relative + ': exceeds delivery size limit')
            continue
        payload = path.read_bytes()
        if key_pattern.search(payload):
            failures.append(relative + ': private key content')
        files[relative] = hashlib.sha256(payload).hexdigest()
    result = subprocess.run(['git', 'diff', '--check'], cwd=ROOT, capture_output=True, text=True)
    if result.returncode:
        failures.append('git diff --check')
    evidence = ROOT / 'docs/evidencias/etapa5/delivery-review.json'
    report = dict(status='FALLIDO' if failures else 'EJECUTADO', checked_files=len(files),
        failures=failures, diff_check_exit_code=result.returncode, source_sha256=files,
        scope='Revisión de tipos/tamaños, claves privadas y whitespace; complementa revisión manual, no certifica ausencia de todo secreto posible')
    evidence.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(status=report['status'], checked_files=len(files), failures=failures)))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
