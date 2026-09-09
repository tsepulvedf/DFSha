"""Mantenimiento explícito: resolver juntos compilador, runtime y bibliotecas."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
env = dict(os.environ, CUSTOM_COMPILE_COMMAND="python scripts/lock_dependencies.py")
subprocess.run([sys.executable, "-m", "piptools", "compile", "--extra", "dev", "--allow-unsafe",
                "--generate-hashes", "--strip-extras", "--output-file", "requirements.lock",
                "pyproject.toml"], cwd=ROOT, env=env, check=True)
