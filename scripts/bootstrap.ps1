param([string]$PythonExe = "")
$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
if (-not $PythonExe) {
    $candidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path -LiteralPath $candidate) { $PythonExe = $candidate }
    else {
        $command = Get-Command python -ErrorAction SilentlyContinue
        if ($command) { $PythonExe = $command.Source }
        else { throw "Indique -PythonExe con un Python 3.12 existente; no se instala Python del sistema." }
    }
}
& $PythonExe -c "import sys; assert sys.version_info[:2] == (3, 12), sys.version"
if ($LASTEXITCODE) { throw "Se requiere Python 3.12" }
if (-not (Test-Path -LiteralPath ".venv-win\Scripts\python.exe")) {
    & $PythonExe -m venv .venv-win
    if ($LASTEXITCODE) { throw "No se pudo crear el entorno" }
}
$projectPython = Join-Path $projectRoot ".venv-win\Scripts\python.exe"
& $projectPython -m pip install --disable-pip-version-check --require-hashes -r requirements.lock
if ($LASTEXITCODE) { throw "Falló instalación fijada" }
& $projectPython -m pip install --disable-pip-version-check --no-deps --no-build-isolation -e .
if ($LASTEXITCODE) { throw "Falló instalación de DFSha" }
& $projectPython scripts/generate_proto.py
if ($LASTEXITCODE) { throw "Falló generación/importación" }
& $projectPython scripts/fetch_etcd.py
if ($LASTEXITCODE) { throw "Falló descarga verificada de etcd" }
& $projectPython -m pip check
if ($LASTEXITCODE) { throw "Conflicto de dependencias" }
