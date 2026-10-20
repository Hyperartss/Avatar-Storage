@echo off
REM INF Avis - Windows setup script
REM Creates a virtual environment and installs dependencies

cd /d "%~dp0"

echo Creating virtual environment...
python -m venv .venv
if errorlevel 1 (
    echo Error: Failed to create virtual environment.
    echo Make sure Python 3.10+ is installed and in PATH.
    pause
    exit /b 1
)

echo Upgrading pip...
.venv\Scripts\python.exe -m pip install --upgrade pip >nul

echo Installing dependencies...
.venv\Scripts\pip.exe install -r requirements.txt
if errorlevel 1 (
    echo Error: Failed to install dependencies.
    pause
    exit /b 1
)

echo.
echo Setup complete!
echo.
echo To run the app:
echo   run.bat
echo.
echo Or activate the environment manually:
echo   .venv\Scripts\Activate.bat
echo   python main.py
pause