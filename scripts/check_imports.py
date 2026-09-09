"""Importar todos los stubs desde el entorno instalado, sin PYTHONPATH añadido."""
import argparse
import importlib
import json
from pathlib import Path
import sys

import dfsha

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--require-installed", action="store_true")
args = parser.parse_args()
package = Path(dfsha.__file__).resolve().parent
if args.require_installed and not package.is_relative_to(Path(sys.prefix).resolve()):
    raise RuntimeError("Importación no procede del entorno limpio instalado")
modules = []
for source in sorted(package.rglob("*_pb2*.py")):
    module = ".".join(source.relative_to(package.parent).with_suffix("").parts)
    importlib.import_module(module)
    modules.append(module)
assert len(modules) == 34, modules
print(json.dumps({"status": "EJECUTADO", "modules": len(modules),
                  "package_directory": str(package), "python": sys.version.split()[0]}))
