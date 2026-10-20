#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build Windows .exe for INF Avis using PyInstaller

.DESCRIPTION
    Creates a standalone .exe in dist/INF Avis/INF Avis.exe
    Run from the project root with the venv activated.

.PARAMETER Version
    Version string for the output (default: git describe or 'dev')

.EXAMPLE
    .\build_windows.ps1
    .\build_windows.ps1 -Version "1.2.3"
#>

param(
    [string]$Version = ""
)

if (-not $Version) {
    $Version = git describe --tags --always --dirty 2>$null
    if (-not $Version) { $Version = "dev" }
}

Write-Host "Building INF Avis $Version for Windows..." -ForegroundColor Cyan

# Clean previous builds
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

# Install PyInstaller if needed
try {
    python -m PyInstaller --version | Out-Null
} catch {
    Write-Host "Installing PyInstaller..." -ForegroundColor Yellow
    python -m pip install --quiet pyinstaller
}

# Build with PyInstaller
$args = @(
    "--clean"
    "--noconfirm"
    "--windowed"
    "--name", "INF Avis"
    "--add-data", "gui;gui"
    "--add-data", "api;api"
    "--add-data", "database.py;."
    "--add-data", "paths.py;."
    "--hidden-import", "PyQt6.QtSvg"
    "--hidden-import", "certifi"
    "--exclude-module", "tkinter"
    "--exclude-module", "matplotlib"
    "--exclude-module", "numpy"
    "--exclude-module", "pytest"
    "main.py"
)

python -m PyInstaller @args

if ($LASTEXITCODE -ne 0) {
    Write-Error "Build failed!"
    exit 1
}

Write-Host "`nBuild complete!" -ForegroundColor Green
Write-Host "Executable: dist\INF Avis\INF Avis.exe"
Write-Host "`nTo distribute, zip the entire 'dist\INF Avis' folder."
Write-Host "The .exe is self-contained - no Python install needed on target machine."