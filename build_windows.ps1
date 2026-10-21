#!/usr/bin/env pwsh
# Build Windows release for INF Avis
# Usage: .\build_windows.ps1 [version]

$ROOT = Split-Path -Parent $PSScriptRoot
& "$ROOT\build\windows\build_windows.ps1" $args