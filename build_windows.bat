@echo off
REM Build Windows release for INF Avis
REM Usage: build_windows.bat [version]

cd /d "%~dp0"
call build\windows\build_windows.bat %*