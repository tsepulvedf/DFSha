"""Probar los comandos manuales start/cliente/stop y conservar salidas sin secretos."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys

from runtime import ROOT, wait_until


def main():
    commands = []
    def run(*arguments):
        command = [sys.executable, *arguments]
        completed = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=40)
        commands.append({"argv": command, "exit_code": completed.returncode,
                         "stdout": completed.stdout, "stderr": completed.stderr})
        if completed.returncode:
            raise RuntimeError(completed.stdout + completed.stderr)
        return completed
    certs = ROOT / ".runtime/certs"
    if not certs.exists():
        run("scripts/generate_certs.py")
    started = False
    try:
        run("scripts/dev.py", "start")
        started = True
        public = run("-m", "dfsha.client.diagnostic", "--target", "localhost:17443")
        internal = run("-m", "dfsha.client.diagnostic", "--target", "localhost:17445", "--identity", "client")
        assert json.loads(public.stdout)["listener"] == "public"
        assert json.loads(internal.stdout)["listener"] == "internal"
    finally:
        if started:
            run("scripts/dev.py", "stop")
            state = json.loads((ROOT / ".runtime/dev/active.json").read_text(encoding="utf-8"))
            log = Path(state["log_file"]).resolve()
            if not log.is_relative_to((ROOT / ".runtime/dev").resolve()):
                raise RuntimeError("Log fuera del directorio propio")
            wait_until(lambda: '"event": "stopped"' in log.read_text(encoding="utf-8"), 10)
    evidence = ROOT / "docs/evidencias/etapa2" / ("manual-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + ".json")
    evidence.write_text(json.dumps({"status": "EJECUTADO", "commands": commands,
                                    "orderly_stop_observed": True}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": "EJECUTADO", "evidence": str(evidence)}))


if __name__ == "__main__":
    main()
