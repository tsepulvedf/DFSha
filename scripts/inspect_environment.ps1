param([string]$OutputPath = "docs/evidencias/etapa2/entorno-git.json", [switch]$Remote)
$ErrorActionPreference = "Continue"
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
function Invoke-Probe([string]$Tool, [string[]]$Arguments) {
    $output = & $Tool @Arguments 2>&1 | Out-String
    return @{ executable = $Tool; arguments = $Arguments; exit_code = $LASTEXITCODE; output = $output.Replace([string][char]0, "").Trim() }
}
$report = [ordered]@{ timestamp = [DateTime]::UtcNow.ToString("o"); cwd = $projectRoot; commands = @(); tools_on_path = @(); candidates = @() }
foreach ($toolName in @("git", "python", "python3", "py", "docker", "docker-compose", "wsl", "node")) {
    $found = Get-Command $toolName -ErrorAction SilentlyContinue
    $report.tools_on_path += @{ name = $toolName; path = if ($found) { $found.Source } else { $null } }
}
foreach ($candidate in @(
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"),
    (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin\docker.exe"),
    (Join-Path $env:ProgramFiles "Docker\Docker\Docker Desktop.exe"),
    (Join-Path $env:LOCALAPPDATA "Docker\resources\bin\docker.exe")
)) { $report.candidates += @{ path = $candidate; exists = (Test-Path -LiteralPath $candidate) } }
$report.services = @(Get-Service -Name "com.docker.service", "docker", "WslService", "LxssManager" -ErrorAction SilentlyContinue | Select-Object Name, Status)
$report.commands += Invoke-Probe "git" @("--version")
$report.commands += Invoke-Probe "git" @("status", "--short")
$report.commands += Invoke-Probe "git" @("remote", "-v")
$report.commands += Invoke-Probe "git" @("symbolic-ref", "--short", "HEAD")
$report.commands += Invoke-Probe "git" @("log", "-1", "--oneline")
$report.commands += Invoke-Probe "git" @("config", "--get-regexp", "^branch\.main\.")
$report.commands += Invoke-Probe "py" @("-0p")
$report.commands += Invoke-Probe "wsl" @("--status")
$report.commands += Invoke-Probe "wsl" @("--list", "--verbose")
$report.commands += Invoke-Probe ".\.venv-win\Scripts\python.exe" @("--version")
$report.commands += Invoke-Probe ".\.tools\etcd-3.6.14\windows-amd64\etcd.exe" @("--version")
if ($Remote) {
    $report.commands += Invoke-Probe "git" @("ls-remote", "--symref", "https://github.com/tsepulvedf/DFSha")
    try {
        $remoteInfo = Invoke-RestMethod -Uri "https://api.github.com/repos/tsepulvedf/DFSha" -Headers @{ "User-Agent" = "DFSha-stage2" }
        $report.github = $remoteInfo | Select-Object full_name, html_url, default_branch, size, private, created_at, updated_at
    } catch { $report.github_error = $_.Exception.Message }
}
$destination = [IO.Path]::GetFullPath((Join-Path $projectRoot $OutputPath))
if (Test-Path -LiteralPath $destination) { throw "La evidencia ya existe: elija otro -OutputPath" }
$null = New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destination)
[IO.File]::WriteAllText($destination, ($report | ConvertTo-Json -Depth 8), (New-Object Text.UTF8Encoding($false)))
Write-Output $destination
