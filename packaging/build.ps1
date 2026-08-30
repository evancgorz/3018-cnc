$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$deployer = Join-Path $projectRoot ".venv\Scripts\pyside6-deploy.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "The project environment is missing. Run ..\setup.ps1 first."
}
if (-not (Test-Path -LiteralPath $deployer)) {
    throw "PySide6 deployment tooling is missing. Repair the environment with ..\setup.ps1 first."
}

Push-Location $projectRoot
try {
    & $deployer run.py --mode standalone --name "TTC 3018 Control" --extra-modules PySide6.QtQuick,PySide6.QtQml
    if ($LASTEXITCODE -ne 0) {
        throw "PySide6 deployment failed with exit code $LASTEXITCODE"
    }
}
finally {
    Pop-Location
}
