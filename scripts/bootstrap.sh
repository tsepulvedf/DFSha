#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
project_python="${DFSHA_PYTHON:-python3.12}"
"$project_python" -c 'import sys; assert sys.version_info[:2] == (3, 12), sys.version'
if [[ ! -f .venv-linux/bin/python ]]; then
  "$project_python" -m venv .venv-linux
fi
.venv-linux/bin/python -m pip install --disable-pip-version-check --require-hashes -r requirements.lock
.venv-linux/bin/python -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e .
.venv-linux/bin/python scripts/generate_proto.py
.venv-linux/bin/python scripts/fetch_etcd.py
.venv-linux/bin/python -m pip check
