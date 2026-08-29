$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $projectRoot ".venv\Scripts\pythonw.exe"

if (-not (Test-Path -LiteralPath $python)) {
    throw "The project environment is missing. Run .\setup.ps1 first."
}

Start-Process -FilePath $python -ArgumentList (Join-Path $projectRoot "run.py") -WorkingDirectory $projectRoot

