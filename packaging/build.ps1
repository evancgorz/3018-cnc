$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$icon = Join-Path $projectRoot ".venv\Lib\site-packages\PySide6\scripts\deploy_lib\pyside_icon.ico"
$outputDir = Join-Path $projectRoot "deployment"

if (-not (Test-Path -LiteralPath $python)) {
    throw "The project environment is missing. Run ..\setup.ps1 first."
}
if (-not (Test-Path -LiteralPath $icon)) {
    throw "The PySide6 application icon is missing: $icon"
}

Push-Location $projectRoot
$previousPath = $env:Path
$previousPythonPath = $env:PYTHONPATH
try {
    $env:Path = "$projectRoot\.venv\Scripts;$previousPath"
    $env:PYTHONPATH = Join-Path $projectRoot "src"
    & $python -m nuitka run.py `
        --standalone `
        --follow-imports `
        --enable-plugin=pyside6 `
        "--output-dir=$outputDir" `
        "--output-filename=TTC 3018 Control.exe" `
        "--windows-icon-from-ico=$icon" `
        "--include-data-dir=$projectRoot\src\ttc3018_control\qt\qml=ttc3018_control\qt\qml" `
        --include-qt-plugins=platforms,qml,qmllint,qmltooling,platforminputcontexts `
        --noinclude-qt-translations `
        --quiet
    if ($LASTEXITCODE -ne 0) {
        throw "Nuitka deployment failed with exit code $LASTEXITCODE"
    }
}
finally {
    $env:Path = $previousPath
    $env:PYTHONPATH = $previousPythonPath
    Pop-Location
}
