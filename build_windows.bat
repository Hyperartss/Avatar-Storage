@echo off
REM Build a Windows release of INF Avis.
REM Usage: build_windows.bat [version]

cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build_windows.ps1" %*
