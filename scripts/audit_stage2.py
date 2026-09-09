"""Inventario de RPC y coherencia documental, separado de pruebas funcionales."""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
from pathlib import Path
import re
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-catalog", action="store_true")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    records = []
    from dfsha.control.queries import Queries
    from dfsha.control.commands import Commands
    for module in ("diagnostic", "identity", "namespace", "control", "data", "nodes"):
        descriptor = importlib.import_module(f"dfsha.v1.{module}_pb2").DESCRIPTOR
        for service in descriptor.services_by_name.values():
            for method in service.methods:
                records.append({"rpc": f"{service.full_name}.{method.name}",
                    "path": f"/{service.full_name}/{method.name}",
                    "request": method.input_type.full_name, "response": method.output_type.full_name,
                    "client_streaming": method.client_streaming, "server_streaming": method.server_streaming,
                    "implementation": "DIAGNOSTIC" if module == "diagnostic" else
                        "HITO1" if method.name in ('Login', 'PutBlock', 'GetBlock') or
                        hasattr(Queries, method.name) or hasattr(Commands, method.name) else "UNIMPLEMENTED",
                    "source": f"proto/dfsha/v1/{module}.proto"})
    catalog = {"version": "dfsha.v1", "semantic_contract": "docs/protocolos.md", "rpcs": records}
    catalog_file = ROOT / "docs/rpc-catalog.json"
    serialized = json.dumps(catalog, indent=2) + "\n"
    if args.write_catalog:
        catalog_file.write_text(serialized, encoding="utf-8")
    if catalog_file.read_text(encoding="utf-8") != serialized:
        raise RuntimeError("Catálogo desactualizado: usar --write-catalog")
    protocols = (ROOT / "docs/protocolos.md").read_text(encoding="utf-8")
    for record in records:
        short = record["rpc"].removeprefix("dfsha.v1.")
        if f"| {short} " not in protocols:
            raise RuntimeError(f"RPC sin fila semántica: {short}")
    future = sum(r["implementation"] == "UNIMPLEMENTED" for r in records)
    if len(records) != 51 or future != 21:
        raise RuntimeError("Revisar número de RPC y evidencia")
    documents = [ROOT / "README.md"] + [ROOT / "docs" / name for name in (
        "estado.md", "especificacion.md", "arquitectura.md", "decisiones.md", "matriz-requisitos.md",
        "protocolos.md", "entorno.md", "hito1.md", "protocolos-hito1.md", "etapa3-diseno.md")]
    documents += [ROOT / "docs/evidencias/etapa2/README.md", ROOT / "docs/evidencias/etapa3/README.md"]
    links = 0
    for document in documents:
        content = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", content):
            if target.startswith(("http:", "https:", "#")):
                continue
            path = target.split("#", 1)[0].strip("<>")
            if path and not (document.parent / unquote(path)).exists():
                raise RuntimeError(f"Enlace local inexistente: {document.name} -> {target}")
            links += 1
    originals = {
        "docs/enunciado/SI3007-262-proyecto1-dfs.docx.pdf": "0ec8cc4cf92f9cf9345d5cf147d096a9cc74f78146aabce823d3890a31b446bf",
        "docs/propuesta/Prompts_Codex_DFSha_Opcion1_CS.md": "755d2bebc288133e54e4f3161a433c35e6d08a9f0a7c8dce9b9b031e41c902b3",
    }
    for path, expected in originals.items():
        if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != expected:
            raise RuntimeError(f"Fuente original modificada: {path}")
    report = {"status": "EJECUTADO", "rpcs": len(records), "future_unimplemented": future,
              "semantic_rows": len(records), "existing_local_links": links, "original_sha256": originals,
              "document_sha256": {p.relative_to(ROOT).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in documents}, "scope": "auditoría documental, no prueba RF/RNF"}
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if not k.endswith("sha256")}))


if __name__ == "__main__":
    main()
