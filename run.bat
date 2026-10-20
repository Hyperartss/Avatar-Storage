@echo off
REM INF Avis - Windows launcher
REM Double-click this file to run, or run from Command Prompt

cd /d "%~dp0"

REM Check for venv first (development mode)
if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" main.py %*
    exit /b %errorlevel%
)

REM Check for system Python
python --version >nul 2>&1
if not errorlevel 1 (
    python main.py %*
    exit /b %errorlevel%
)

echo Error: Python not found.
echo.
echo Install Python 3.10+ from https://python.org
echo Or run setup.bat first to create a virtual environment.
pause
exit /b 1