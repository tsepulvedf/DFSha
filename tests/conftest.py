from pathlib import Path
import sys
from uuid import uuid4

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))  # Utilidades de test, no stubs ni paquetes de aplicación.
from generate_certs import generate
from runtime import diagnostic_process


@pytest.fixture(scope="session")
def run_dir(record_testsuite_property):
    directory = ROOT / ".runtime/tests" / str(uuid4())
    directory.mkdir(parents=True)
    record_testsuite_property("runtime_directory", str(directory))
    return directory


@pytest.fixture(scope="session")
def certs(run_dir):
    directory = run_dir / "certs"
    generate(directory)
    return directory


@pytest.fixture(scope="session")
def server(run_dir, certs):
    with diagnostic_process(run_dir / "diagnostic", certs) as (process, ready):
        yield ready
    assert process.returncode == 0, "Servidor no cerró ordenadamente"
