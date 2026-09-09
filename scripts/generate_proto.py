"""Compilar fuentes propias y oficiales; --check comprueba reproducibilidad."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import grpc_tools
from grpc_tools import protoc

ROOT = Path(__file__).resolve().parents[1]


def generate(check: bool = False) -> dict:
    subprocess.run([sys.executable, str(ROOT / "scripts/vendor_etcd.py")], check=True)
    staging = ROOT / "build/proto"
    output = ROOT / "build/generated" / str(uuid4())
    output.mkdir(parents=True, exist_ok=True)
    inputs = []
    for original in sorted((ROOT / "third_party/proto").rglob("*.proto")):
        relative = Path("dfsha/_vendor") / original.relative_to(ROOT / "third_party/proto")
        adapted = re.sub(
            r'(import\s+(?:public\s+)?")((?!google/protobuf/)[^"]+)(";)',
            r'\1dfsha/_vendor/\2\3', original.read_text(encoding="utf-8"),
        )
        destination = staging / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(adapted, encoding="utf-8", newline="\n")
        inputs.append(str(relative).replace("\\", "/"))
    inputs.extend(str(p.relative_to(ROOT / "proto")).replace("\\", "/")
                  for p in sorted((ROOT / "proto").rglob("*.proto")))
    options = ["protoc", f"-I{ROOT / 'proto'}", f"-I{staging}",
               f"-I{Path(grpc_tools.__file__).parent / '_proto'}",
               f"--python_out={output}", f"--grpc_python_out={output}",
               f"--descriptor_set_out={ROOT / 'build/contracts.pb'}", "--include_imports"]
    if protoc.main(options + inputs):
        raise RuntimeError("Protobuf no compiló; no se modifica código generado")
    records = {}
    for generated in sorted(output.rglob("*_pb2*.py")):
        relative = generated.relative_to(output)
        destination = ROOT / "src" / relative
        payload = generated.read_bytes()
        if check:
            if not destination.exists() or destination.read_bytes() != payload:
                raise RuntimeError(f"Stubs desactualizados: {relative}")
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        records[relative.as_posix()] = hashlib.sha256(payload).hexdigest()
    for relative in records:
        importlib.import_module(relative[:-3].replace("/", "."))
    return {"status": "EJECUTADO", "check": check, "imported_modules": len(records),
            "generated_sha256": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    report = generate(args.check)
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "generated_sha256"}))
