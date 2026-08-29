$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "Python 3.14 was not found at $python"
}

if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".venv"))) {
    & $python -m venv (Join-Path $projectRoot ".venv")
}

$venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
& $venvPython -m pip install --upgrade pip
& $venvPython -m pip install -r (Join-Path $projectRoot "requirements-dev.txt")

Write-Host "Setup complete. Start the app with .\run.ps1"

