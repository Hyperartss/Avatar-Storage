@echo off
REM Build Windows .exe for INF Avis using PyInstaller
REM Run from the project root in a PowerShell or CMD with the venv activated

set VERSION=%1
if "%VERSION%"=="" (
    for /f "tokens=*" %%a in ('git describe --tags --always --dirty 2^>nul') do set VERSION=%%a
)
if "%VERSION%"=="" set VERSION=dev

echo Building INF Avis %VERSION% for Windows...

REM Clean previous builds
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

REM Install PyInstaller if needed
python -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo Installing PyInstaller...
    python -m pip install --quiet pyinstaller
)

REM Build with PyInstaller
python -m PyInstaller ^
    --clean ^
    --noconfirm ^
    --windowed ^
    --name "INF Avis" ^
    --add-data "gui;gui" ^
    --add-data "api;api" ^
    --add-data "database.py;." ^
    --add-data "paths.py;." ^
    --hidden-import=PyQt6.QtSvg ^
    --hidden-import=certifi ^
    --exclude-module=tkinter ^
    --exclude-module=matplotlib ^
    --exclude-module=numpy ^
    --exclude-module=pytest ^
    main.py

if errorlevel 1 (
    echo Build failed!
    exit /b 1
)

echo.
echo Build complete!
echo Executable: dist\INF Avis\INF Avis.exe
echo.
echo To distribute, zip the entire "dist\INF Avis" folder.
echo The .exe is self-contained - no Python install needed on target machine.