# Build a Windows release of INF Avis.
# Usage: .\build_windows.ps1 [version]
#
# Output:
#   release/windows/inf-avis-<version>-win64\   (portable folder)
#   release/inf-avis-<version>-win64.zip        (distributable zip)

param(
    [string]$Version
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Definition
Set-Location $Root

if (-not $Version) {
    $Version = (git describe --tags --always --dirty 2>$null)
    if (-not $Version) { $Version = "dev" }
}
$Version = $Version.TrimStart("v")
$AppName = "inf-avis"

$PyInstaller = Join-Path $Root ".venv\Scripts\pyinstaller.exe"
if (-not (Test-Path $PyInstaller)) {
    $cmd = Get-Command pyinstaller -ErrorAction SilentlyContinue
    if (-not $cmd) {
        throw "PyInstaller not found. Run setup.bat first."
    }
    $PyInstaller = $cmd.Source
}

Write-Host "Building $AppName $Version for Windows..."

if (Test-Path "build\inf-avis") { Remove-Item -Recurse -Force "build\inf-avis" }
if (Test-Path "dist\inf-avis") { Remove-Item -Recurse -Force "dist\inf-avis" }
& $PyInstaller --clean --noconfirm inf-avis.spec
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed with exit code $LASTEXITCODE" }

$ReleaseDir = "release\windows\$AppName-$Version-win64"
if (Test-Path $ReleaseDir) { Remove-Item -Recurse -Force $ReleaseDir }
New-Item -ItemType Directory -Force -Path $ReleaseDir | Out-Null
Copy-Item -Recurse -Force "dist\$AppName\*" $ReleaseDir
Copy-Item "README.md" $ReleaseDir -ErrorAction SilentlyContinue
Copy-Item "LICENSE" $ReleaseDir -ErrorAction SilentlyContinue

$ZipPath = "release\$AppName-$Version-win64.zip"
if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path $ReleaseDir -DestinationPath $ZipPath

Write-Host ""
Write-Host "============================================"
Write-Host "Done! Release ready at:"
Write-Host "  Folder: $ReleaseDir\"
Write-Host "  Zip:    $ZipPath"
Write-Host "============================================"
