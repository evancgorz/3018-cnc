@echo off
setlocal

cd /d "%~dp0"
set "TTC3018_PYTHON=%CD%\.venv\Scripts\python.exe"

if not exist "%TTC3018_PYTHON%" (
    echo TTC 3018 Control needs its Python environment. Running setup now...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\setup.ps1"
    if errorlevel 1 goto :setup_failed
)

"%TTC3018_PYTHON%" -c "import PySide6" >nul 2>nul
if errorlevel 1 (
    echo TTC 3018 Control is installing the Qt interface. Running setup now...
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%CD%\setup.ps1"
    if errorlevel 1 goto :setup_failed
)

if /i "%~1"=="--check" goto :check

echo Starting TTC 3018 Control Qt Preview...
"%TTC3018_PYTHON%" "%CD%\run_qt.py"
set "TTC3018_EXIT=%errorlevel%"

if not "%TTC3018_EXIT%"=="0" (
    echo.
    echo TTC 3018 Qt Preview stopped with error code %TTC3018_EXIT%.
    pause
)
exit /b %TTC3018_EXIT%

:check
"%TTC3018_PYTHON%" "%CD%\run_qt.py" --check
exit /b %errorlevel%

:setup_failed
echo.
echo Setup failed. Run setup.ps1 and try again.
pause
exit /b 1
