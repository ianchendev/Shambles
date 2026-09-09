# Install Shambles from GitHub Releases into %LOCALAPPDATA%\Shambles (no admin).
# Usage:
#   irm …/scripts/install.ps1 | iex
#   irm …/scripts/install.ps1 | iex; install.ps1 -Version v2.1.0   # or save and run:
#   .\install.ps1 -Version v2.1.0
param(
    [string]$Version
)

$ErrorActionPreference = 'Stop'

$Base = if ($env:SHAMBLES_RELEASE_BASE) { $env:SHAMBLES_RELEASE_BASE } else { 'https://github.com/ianchendev/Shambles/releases' }
$SkipSmoke = if ($env:SHAMBLES_SKIP_SMOKE) { $env:SHAMBLES_SKIP_SMOKE } else { '0' }

$arch = $env:PROCESSOR_ARCHITECTURE
if ($env:PROCESSOR_ARCHITEW6432) {
    $arch = $env:PROCESSOR_ARCHITEW6432
}

if ($env:SHAMBLES_FORCE_ASSET) {
    $Asset = $env:SHAMBLES_FORCE_ASSET
} elseif ($arch -in @('AMD64', 'x86_64')) {
    $Asset = 'shambles-windows-x64.exe'
} else {
    Write-Error "No Shambles binary for Windows-$arch yet"
    exit 1
}

if ($Version) {
    $Url = "$Base/download/$Version/$Asset"
} else {
    $Url = "$Base/latest/download/$Asset"
}

$DestDir = Join-Path $env:LOCALAPPDATA 'Shambles'
$Dest = Join-Path $DestDir 'shambles.exe'
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

$Tmp = [System.IO.Path]::GetTempFileName()
try {
    Write-Host "Downloading $Asset…"
    Invoke-WebRequest -Uri $Url -OutFile $Tmp -UseBasicParsing
    Move-Item -Force $Tmp $Dest
} finally {
    if (Test-Path $Tmp) {
        Remove-Item -Force $Tmp
    }
}

Write-Host "Installed to $Dest"

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$pathEntries = @()
if ($userPath) {
    $pathEntries = $userPath -split ';' | Where-Object { $_ -ne '' }
}
if ($pathEntries -notcontains $DestDir) {
    $newPath = ($pathEntries + $DestDir) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Host "Added $DestDir to your user PATH (open a new terminal to use shambles)."
}

Write-Host 'Note: Shambles binaries are unsigned; Windows SmartScreen may warn on first run.'
Write-Host 'Note: a successful install does not mean account switching is supported on this OS.'
Write-Host 'See the README support matrix for Linux / macOS / Windows status.'

if ($SkipSmoke -ne '1') {
    try {
        & $Dest --version | Write-Host
    } catch {
        Write-Warning 'Smoke check skipped or failed (binary may need a real Release asset).'
    }
}

Write-Host 'Done.'
