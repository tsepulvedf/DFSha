"""Iniciar/detener diagnóstico local mediante archivos de control propios."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from runtime import PROCESS_FLAGS, ROOT, wait_until


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop"])
    parser.add_argument('--profile', choices=['diagnostic', 'hito1'], default='diagnostic')
    args = parser.parse_args()
    runtime = ROOT / ('.runtime/dev-hito1' if args.profile == 'hito1' else '.runtime/dev')
    runtime.mkdir(parents=True, exist_ok=True)
    state_file = runtime / "active.json"
    if args.action == "stop":
        if not state_file.exists():
            raise SystemExit("No hay arranque registrado por este script")
        state = json.loads(state_file.read_text(encoding="utf-8"))
        stop = Path(state["stop_file"]).resolve()
        if not stop.is_relative_to(runtime.resolve()):
            raise SystemExit("Ruta de control fuera del directorio del diagnóstico")
        stop.touch()  # No enviar señales a un PID potencialmente reutilizado.
        print(json.dumps({"status": "EJECUTADO", "action": "stop_requested",
                          "verification": "wait for stopped event in server log"}))
        return
    if state_file.exists():
        state = json.loads(state_file.read_text(encoding="utf-8"))
        log = Path(state["log_file"])
        if not log.resolve().is_relative_to(runtime.resolve()) or not log.exists() or '"event": "stopped"' not in log.read_text(encoding="utf-8"):
            raise SystemExit("Hay un arranque sin cierre verificado; use stop y revise su log")
    run = runtime / str(uuid4())
    run.mkdir()
    ready, stop, log_file = run / "ready.json", run / "stop", run / "server.log"
    with log_file.open("wb") as log:
        process = subprocess.Popen([sys.executable, "-m", "dfsha.control.server", "--config",
            str(ROOT / ('deploy/monolith.example.toml' if args.profile == 'hito1' else 'deploy/local.example.toml')),
            "--ready-file", str(ready), "--stop-file", str(stop)],
            cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, creationflags=PROCESS_FLAGS)
    def available():
        if process.poll() is not None:
            raise RuntimeError(f"Servidor terminó; revisar {log_file}")
        if ready.exists():
            try:
                return json.loads(ready.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return None
        return None
    try:
        state = wait_until(available)
    except BaseException:
        stop.touch()
        process.wait(timeout=15)
        raise
    state.update(stop_file=str(stop), log_file=str(log_file))
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    print(json.dumps(state))


if __name__ == "__main__":
    main()
