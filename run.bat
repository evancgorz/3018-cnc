@echo off
setlocal

rem Always run relative to this file so double-clicking works from Explorer.
cd /d "%~dp0"
set "TTC3018_PYTHON=%CD%\.venv\Scripts\python.exe"

if not exist "%TTC3018_PYTHON%" (
    echo Pine needs its Python environment. Running setup now...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\setup.ps1"
    if errorlevel 1 goto :setup_failed
)

if not exist "%TTC3018_PYTHON%" goto :setup_failed

"%TTC3018_PYTHON%" -c "import serial, PySide6" >nul 2>nul
if errorlevel 1 (
    echo Pine is updating its Qt environment. Running setup now...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\setup.ps1"
    if errorlevel 1 goto :setup_failed
)

if /i "%~1"=="--check" goto :check

echo Starting Pine...
"%TTC3018_PYTHON%" "%CD%\run.py"
set "TTC3018_EXIT=%errorlevel%"

if not "%TTC3018_EXIT%"=="0" (
    echo.
    echo Pine stopped with error code %TTC3018_EXIT%.
    echo The error details are shown above. Press any key to close this window.
    pause >nul
)

exit /b %TTC3018_EXIT%

:check
"%TTC3018_PYTHON%" "%CD%\run.py" --check
exit /b %errorlevel%

:setup_failed
echo.
echo Setup failed. Confirm Python 3.14 is installed, then run setup.ps1 and try again.
pause
exit /b 1
