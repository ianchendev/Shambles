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

$DestDir = Join-Path $env:LOCALAPPDATA 'Shambles'
$Dest = Join-Path $DestDir 'shambles.exe'
New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

function Get-Binary($AssetName, $Target) {
    $Tmp = [System.IO.Path]::GetTempFileName()
    try {
        Write-Host "Downloading $AssetName…"
        $From = if ($Version) { "$Base/download/$Version/$AssetName" }
                else { "$Base/latest/download/$AssetName" }
        Invoke-WebRequest -Uri $From -OutFile $Tmp -UseBasicParsing
        Move-Item -Force $Tmp $Target
    } finally {
        if (Test-Path $Tmp) { Remove-Item -Force $Tmp }
    }
}

Get-Binary $Asset $Dest

# The windowed twin, for a desktop shortcut. shambles.exe is
# console-subsystem so --version and --help can print; launching that from a
# shortcut flashes a console, which shamblesw.exe exists to avoid. A release
# that predates it simply has no such asset, and the install still succeeds.
$Windowed = 'shamblesw-windows-x64.exe'
$DestW = Join-Path $DestDir 'shamblesw.exe'
$HasWindowed = $true
try {
    Get-Binary $Windowed $DestW
} catch {
    $HasWindowed = $false
    Write-Host "No windowed build in this release; skipping shamblesw.exe."
}

Write-Host "Installed to $Dest"
if ($HasWindowed) {
    Write-Host "Also installed $DestW, for a desktop shortcut with no console window."
}

$userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
$pathEntries = @()
if ($userPath) {
    $pathEntries = $userPath -split ';' | Where-Object { $_ -ne '' }
}
if ($pathEntries -notcontains $DestDir) {
    $newPath = ($pathEntries + $DestDir) -join ';'
    [Environment]::SetEnvironmentVariable('Path', $newPath, 'User')
    Write-Host "Added $DestDir to your user PATH."
}

# The stored PATH above only reaches processes started after this one, so the
# window that just ran the installer still cannot find shambles. Reinstalling
# made that worse: the entry was already stored, so the branch above said
# nothing and the install ended with a command-not-found and no explanation.
# Putting it on this session's PATH as well means `shambles` works in the
# terminal you are already standing in.
if (($env:Path -split ';') -notcontains $DestDir) {
    $env:Path = "$env:Path;$DestDir"
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

Write-Host "Run 'shambles' to start."
Write-Host 'Terminals opened before now will not find it until you start a new terminal.'
Write-Host 'Done.'
