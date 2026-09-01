param(
    [switch]$ShortcutOnly
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"

if (-not $ShortcutOnly) {
    if (-not (Test-Path -LiteralPath $python)) {
        throw "Python 3.14 was not found at $python"
    }

    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".venv"))) {
        & $python -m venv (Join-Path $projectRoot ".venv")
    }

    $venvPython = Join-Path $projectRoot ".venv\Scripts\python.exe"
    & $venvPython -m pip install --upgrade pip
    & $venvPython -m pip install -r (Join-Path $projectRoot "requirements-dev.txt")
}

$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "Pine.lnk"
$legacyShortcutPath = Join-Path $desktop "TTC 3018 Control.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = Join-Path $projectRoot "run.bat"
$shortcut.WorkingDirectory = $projectRoot
$shortcut.Description = "Launch Pine CNC Studio"
$shortcut.IconLocation = (Join-Path $projectRoot "src\ttc3018_control\qt\assets\pine.ico") + ",0"
$shortcut.Save()
if (Test-Path -LiteralPath $legacyShortcutPath) {
    Remove-Item -LiteralPath $legacyShortcutPath -Force
}

Write-Host "Setup complete. Desktop shortcut created: $shortcutPath"
Write-Host "You can also start the app with .\run.bat"

