# SPDX-License-Identifier: AGPL-3.0-or-later
#Requires -Version 5.1
<#
  Build a portable Windows distribution for Pantheon.

  Output layout:
    dist\Pantheon\Pantheon.exe
    dist\Pantheon\static\...
    dist\Pantheon\scripts\...
    dist\Pantheon\mcp_servers\...
    dist\Pantheon\services\hwfit\data\...
    dist\Pantheon\licenses\...        (third-party notices — required, not optional)
    dist\Pantheon\{LICENSE,NOTICE,CREDITS.md}

  The app then keeps using its normal filesystem layout when frozen.

  What goes in the bundle is one list, Pantheon.spec's (`B1666`): this builds
  from it rather than passing its own --add-data list, which had drifted from
  the spec (no docker/build-realesrgan-wheels.sh, `B373`) and, by naming a
  script instead of the spec, made PyInstaller write a fresh Pantheon.spec over
  the committed one on every build. The spec ships Pantheon's JavaScript
  without its comments through scripts/strip-js-comments.mjs, as the image
  does (`D-2026-10-29-03` section 4), so the build needs Node.js and acorn.

  Usage:
    powershell -ExecutionPolicy Bypass -File .\build-windows-portable.ps1
#>

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

function Write-Step($msg) { Write-Host ""; Write-Host ("==> " + $msg) -ForegroundColor Cyan }
function Fail($msg) {
    Write-Host ""
    Write-Host ("ERROR: " + $msg) -ForegroundColor Red
    exit 1
}

Write-Step "Checking for Python"
$pyExe = $null
if (Test-Path ".\.venv\Scripts\python.exe") {
    $pyExe = (Resolve-Path ".\.venv\Scripts\python.exe").Path
} else {
    foreach ($c in @("py", "python")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { $pyExe = $cmd.Source; break }
    }
    if ($pyExe -like "*WindowsApps*python.exe") {
        $pyCmd = Get-Command py -ErrorAction SilentlyContinue
        if ($pyCmd) {
            $pyExe = $pyCmd.Source
        }
    }
}
if (-not $pyExe) {
    Fail "Python not found on PATH. Install Python 3.11+ first."
}
Write-Host ("Using Python: " + $pyExe)

Write-Step "Installing build dependencies"
& $pyExe -m pip install --upgrade pip --quiet
& $pyExe -m pip install -r requirements.txt pyinstaller pystray Pillow
if ($LASTEXITCODE -ne 0) { Fail "Dependency install failed." }

# `B1666`. The stripper's parser, acorn, at the exact version and sha512
# package-lock.json names - the install the image's stage and CI's suite run.
Write-Step "Installing the JavaScript comment stripper (acorn, from package-lock.json)"
$npmCmd = Get-Command npm -ErrorAction SilentlyContinue
if (-not (Get-Command node -ErrorAction SilentlyContinue) -or -not $npmCmd) {
    Fail "Node.js not found on PATH. The bundle ships Pantheon's JavaScript without its comments, through scripts/strip-js-comments.mjs, which runs on Node.js: install it from nodejs.org, open a new terminal and run this again."
}
& $npmCmd.Source ci --omit=dev --ignore-scripts --no-audit --no-fund
if ($LASTEXITCODE -ne 0) { Fail "npm ci failed, so the comment stripper has no parser. Its output above says why." }

Write-Step "Building portable exe bundle"
Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue

# Pantheon.spec is the bundle: its data (static/ without comments, scripts,
# the licences MIT, BSD and OFL require to travel with a redistributed copy),
# its icon (static/icon.ico), one folder, no console.
& $pyExe -m PyInstaller --noconfirm --clean Pantheon.spec
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller build failed." }

Write-Host ""
Write-Host "Build complete." -ForegroundColor Green
Write-Host "Portable app folder: $PSScriptRoot\dist\Pantheon" -ForegroundColor Green
Write-Host "Distribute the whole folder (or zip it) so static assets and scripts stay with the exe." -ForegroundColor Green