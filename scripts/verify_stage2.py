"""Verificación real reproducible con evidencia por ejecución y sin mocks de etcd."""
from __future__ import annotations

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
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--clean-env", action="store_true", help="Reinstalar lock y wheel en venv nuevo")
    args = parser.parse_args()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    evidence = ROOT / "docs/evidencias/etapa2" / run_id
    evidence.mkdir(parents=True)
    report = {"status": "PENDIENTE", "run_id": run_id, "commands": [],
              "python": sys.version, "platform": platform.platform(), "sqlite": sqlite3.sqlite_version,
              "packages": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()},
              "scope": "E2; no acredita RF1/RF2/RF3, HA, distribución ni cloud"}
    result_file = evidence / "resultado.json"

    def save():
        result_file.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(command, cwd=ROOT):
        print(subprocess.list2cmdline([str(part) for part in command]), flush=True)
        started = time.monotonic()
        completed = subprocess.run(command, cwd=cwd, encoding="utf-8", errors="replace",
                                  capture_output=True, env=dict(os.environ, PYTHONUTF8="1"))
        item = {"argv": [str(part) for part in command], "cwd": str(cwd),
                "exit_code": completed.returncode, "elapsed_seconds": round(time.monotonic() - started, 3),
                "stdout": completed.stdout, "stderr": completed.stderr}
        report["commands"].append(item)
        save()
        print(completed.stdout[-1800:], flush=True)
        if completed.returncode:
            raise RuntimeError(f"Comando fallido; evidencia: {result_file}")

    try:
        run([sys.executable, "-m", "pip", "check"])
        run([sys.executable, "scripts/generate_proto.py", "--check", "--evidence", str(evidence / "contratos.json")])
        run([sys.executable, "-m", "pytest", "-q", f"--junitxml={evidence / 'pytest.xml'}"])
        suite = ET.parse(evidence / "pytest.xml").getroot().find("testsuite")
        report["tests"] = dict(suite.attrib)
        property_node = suite.find("./properties/property[@name='runtime_directory']")
        runtime = Path(property_node.attrib["value"]).resolve()
        if not runtime.is_relative_to((ROOT / ".runtime/tests").resolve()):
            raise RuntimeError("Ruta de evidencia runtime fuera de los tests propios")
        cleanup = json.loads((runtime / "etcd/cleanup.json").read_text(encoding="utf-8"))
        if cleanup["remaining_keys"] != 0:
            raise RuntimeError("El probe no limpió su prefijo")
        (evidence / "etcd-cleanup.json").write_text(json.dumps(cleanup, indent=2) + "\n", encoding="utf-8")
        from dfsha.common.telemetry import SAFE_FIELDS
        events = []
        for line in (runtime / "diagnostic/server.log").read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("{"):
                event = json.loads(line)
                if set(event) - SAFE_FIELDS - {"event"}:
                    raise RuntimeError("Campo no permitido en log de aplicación")
                events.append(event)
        if not events or events[-1]["event"] != "stopped":
            raise RuntimeError("Falta evidencia de cierre ordenado del servidor")
        (evidence / "server-events.json").write_text(json.dumps(events, indent=2) + "\n", encoding="utf-8")
        if args.clean_env:
            clean_env = ROOT / f".venv-verify-{run_id}"
            run([sys.executable, "-m", "venv", str(clean_env)])
            clean_python = clean_env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
            run([str(clean_python), "-m", "pip", "install", "--disable-pip-version-check", "--require-hashes",
                 "-r", str(ROOT / "requirements.lock")])
            wheel_dir = ROOT / "build/wheels" / run_id
            run([sys.executable, "-m", "build", "--no-isolation", "--wheel", "--outdir", str(wheel_dir)])
            wheel = next(wheel_dir.glob("dfsha-*.whl"))
            run([str(clean_python), "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", str(wheel)])
            run([str(clean_python), "-m", "pip", "check"])
            run([str(clean_python), str(ROOT / "scripts/generate_proto.py"), "--check"], cwd=clean_env)
            run([str(clean_python), "-I", str(ROOT / "scripts/check_imports.py"), "--require-installed"], cwd=clean_env)
            report["clean_environment"] = "EJECUTADO: lock + wheel, generación/importación sin editable ni PYTHONPATH"
        else:
            report["clean_environment"] = "PENDIENTE en esta ejecución; use --clean-env"
        code_files = []
        for directory in ("src", "proto", "scripts", "tests", "deploy", "third_party"):
            code_files.extend(p for p in (ROOT / directory).rglob("*") if p.is_file() and "__pycache__" not in p.parts
                              and not any(part.endswith(".egg-info") for part in p.parts))
        code_files.extend(ROOT / name for name in ("pyproject.toml", "requirements.lock", ".gitignore", ".gitattributes", "MANIFEST.in"))
        report["tested_file_sha256"] = {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                         for p in sorted(code_files)}
        report["status"] = "EJECUTADO"
    except Exception as error:
        report["status"] = "FALLIDO"
        report["error"] = str(error)
    save()
    print(json.dumps({"status": report["status"], "evidence": str(result_file)}), flush=True)
    return 0 if report["status"] == "EJECUTADO" else 1


if __name__ == "__main__":
    raise SystemExit(main())
