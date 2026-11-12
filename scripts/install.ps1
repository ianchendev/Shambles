# Install Shambles from GitHub Releases into %LOCALAPPDATA%\Shambles (no admin).
#
# From PowerShell (Windows PowerShell 5.1 or PowerShell 7):
#   irm https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.ps1 | iex
#
# From cmd.exe:
#   powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.ps1 | iex"
#
# A specific release:
#   $env:SHAMBLES_VERSION = 'v2.1.2'; irm .../scripts/install.ps1 | iex
#   .\install.ps1 -Version v2.1.2
#
# A saved copy is a script file, and Windows refuses to run those by default
# ("running scripts is disabled on this system"). The one-liner above is not
# affected; for a saved copy use:
#   powershell -ExecutionPolicy Bypass -File .\install.ps1
#
# This file is kept to plain ASCII on purpose. Windows PowerShell 5.1 reads a
# script with no byte-order mark in the legacy code page, where one
# typographic character turns into mojibake.
param(
    [string]$Version
)

# Everything runs inside one script block. Piped into iex, a script runs in
# the caller's own session: without this, the preferences set below and every
# variable would be left behind in the window that ran the installer.
& {
    param([string]$Version)

    $ErrorActionPreference = 'Stop'
    # Windows PowerShell draws a progress bar per chunk and a 17 MB download
    # takes minutes because of it.
    $ProgressPreference = 'SilentlyContinue'

    if (-not $Version -and $env:SHAMBLES_VERSION) { $Version = $env:SHAMBLES_VERSION }
    $Base = if ($env:SHAMBLES_RELEASE_BASE) { $env:SHAMBLES_RELEASE_BASE } else { 'https://github.com/ianchendev/Shambles/releases' }
    $SkipSmoke = ($env:SHAMBLES_SKIP_SMOKE -eq '1')
    $Release = if ($Version) { "$Base/download/$Version" } else { "$Base/latest/download" }
    $Pipx = 'pipx install git+https://github.com/ianchendev/Shambles'

    # Windows PowerShell 5.1 on an older Windows 10 offers TLS 1.0 by default,
    # and GitHub refuses it. Adding to the set leaves newer protocols alone.
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    } catch { }

    $arch = $env:PROCESSOR_ARCHITECTURE
    if ($env:PROCESSOR_ARCHITEW6432) { $arch = $env:PROCESSOR_ARCHITEW6432 }

    # Each entry is a console binary and its windowed twin. Windows on Arm
    # runs x64 programs under emulation, so the x64 pair is a fallback there
    # for a release that predates the native one.
    if ($env:SHAMBLES_FORCE_ASSET) {
        $Candidates = @(, @($env:SHAMBLES_FORCE_ASSET, $null))
    } elseif ($arch -in @('AMD64', 'x86_64')) {
        $Candidates = @(, @('shambles-windows-x64.exe', 'shamblesw-windows-x64.exe'))
    } elseif ($arch -eq 'ARM64') {
        $Candidates = @(
            @('shambles-windows-arm64.exe', 'shamblesw-windows-arm64.exe'),
            @('shambles-windows-x64.exe', 'shamblesw-windows-x64.exe')
        )
    } else {
        throw "No Shambles binary for Windows-$arch (32-bit Windows is not supported). Install from source instead: $Pipx"
    }

    if (-not $env:LOCALAPPDATA) { throw 'LOCALAPPDATA is not set, so there is nowhere to install to.' }
    $DestDir = Join-Path $env:LOCALAPPDATA 'Shambles'
    $Dest = Join-Path $DestDir 'shambles.exe'
    $DestW = Join-Path $DestDir 'shamblesw.exe'
    New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

    # Left by an earlier run that replaced a binary while it was in use.
    Get-ChildItem -LiteralPath $DestDir -Filter '*.old' -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue

    function New-TempName {
        # Beside the destination, so the final step is a rename and not a
        # copy; and ending in .exe, because Windows decides what can run by
        # its extension and the download is run once before it is installed.
        Join-Path $DestDir ('.shambles-download-' + [Guid]::NewGuid().ToString('N') + '.exe')
    }

    function Get-Download($Name, $Target) {
        Invoke-WebRequest -Uri "$Release/$Name" -OutFile $Target -UseBasicParsing
    }

    function Get-ExpectedHash($Name) {
        # $null when the release has no usable list; the caller says so.
        $sums = Join-Path $DestDir ('.shambles-sums-' + [Guid]::NewGuid().ToString('N'))
        try {
            Get-Download 'SHA256SUMS' $sums
            foreach ($line in Get-Content -LiteralPath $sums) {
                $parts = $line.Trim() -split '\s+', 2
                if ($parts.Count -eq 2 -and $parts[1].TrimStart('*') -eq $Name) {
                    return $parts[0].ToLowerInvariant()
                }
            }
            return $null
        } catch {
            return $null
        } finally {
            if (Test-Path -LiteralPath $sums) { Remove-Item -Force -LiteralPath $sums }
        }
    }

    function Get-Sha256($Path) {
        # Through .NET rather than Get-FileHash. In Windows PowerShell 5.1
        # that cmdlet lives in a script module, and under the Restricted
        # policy -- the default on a client -- script modules do not load.
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $sha = [System.Security.Cryptography.SHA256]::Create()
            try {
                return ([System.BitConverter]::ToString($sha.ComputeHash($stream)) -replace '-', '').ToLowerInvariant()
            } finally {
                $sha.Dispose()
            }
        } finally {
            $stream.Dispose()
        }
    }

    function Install-File($From, $To) {
        try {
            Move-Item -Force -LiteralPath $From -Destination $To
        } catch {
            # Windows will not overwrite a program that is running, but it
            # will rename one. Move the old binary aside and put the new one
            # in its place; the old one is removed on the next install.
            $aside = "$To.old"
            Remove-Item -Force -LiteralPath $aside -ErrorAction SilentlyContinue
            try {
                Move-Item -Force -LiteralPath $To -Destination $aside
                Move-Item -Force -LiteralPath $From -Destination $To
            } catch {
                throw "Could not replace $To. Close Shambles and run the installer again. ($($_.Exception.Message))"
            }
        }
    }

    function Get-Verified($Name, $Tmp) {
        # Downloads $Name to $Tmp and checks it against the release's list.
        # The list is served from the same place as the binary, so this
        # catches a truncated or mangled download, not a tampered release.
        Get-Download $Name $Tmp
        if ($env:SHAMBLES_SKIP_VERIFY -eq '1') {
            Write-Host 'Checksum not verified (SHAMBLES_SKIP_VERIFY=1).'
            return
        }
        $expected = Get-ExpectedHash $Name
        if (-not $expected) {
            Write-Warning "No checksum is published for $Name; the download was not verified."
            return
        }
        $actual = Get-Sha256 $Tmp
        if ($actual -ne $expected) {
            throw "The download of $Name does not match the release checksum, so nothing was installed. Expected $expected, got $actual. Try again; if it keeps happening, please open an issue."
        }
        Write-Host "Checksum verified for $Name."
    }

    $Asset = $null
    $Windowed = $null
    $Tmp = New-TempName
    $TmpW = New-TempName
    try {
        $lastError = $null
        foreach ($pair in $Candidates) {
            try {
                Write-Host "Downloading $($pair[0])..."
                Get-Verified $pair[0] $Tmp
                $Asset = $pair[0]
                $Windowed = $pair[1]
                break
            } catch {
                $lastError = $_
                if (Test-Path -LiteralPath $Tmp) { Remove-Item -Force -LiteralPath $Tmp }
                if ("$_" -match 'does not match the release checksum') { throw }
            }
        }
        if (-not $Asset) {
            throw "Could not download Shambles from $Release. ($lastError)"
        }

        # Before it replaces a working install, not after.
        if (-not $SkipSmoke) {
            if (-not (Test-Path -LiteralPath $Tmp)) {
                throw 'The download disappeared before it could be run. Security software on this machine may have removed it; the binaries are unsigned.'
            }
            $said = ''
            try { $said = (& $Tmp --version 2>&1 | Out-String).Trim() } catch { $said = "$_" }
            if ($LASTEXITCODE -ne 0 -or $said -notmatch 'shambles \d+\.\d+') {
                throw "The downloaded binary does not start on this system, so nothing was installed. It said: '$said'. Install from source instead: $Pipx"
            }
        }

        # The windowed twin, for a desktop shortcut. shambles.exe is
        # console-subsystem so --version and --help can print; launching that
        # from a shortcut flashes a console, which shamblesw.exe exists to
        # avoid. A release that predates it simply has no such asset, and the
        # install still succeeds.
        $HasWindowed = $false
        if ($Windowed) {
            try {
                Get-Verified $Windowed $TmpW
                $HasWindowed = $true
            } catch {
                if ("$_" -match 'does not match the release checksum') { throw }
                Write-Host 'No windowed build in this release; skipping shamblesw.exe.'
            }
        }

        Install-File $Tmp $Dest
        if ($HasWindowed) { Install-File $TmpW $DestW }
    } finally {
        foreach ($leftover in @($Tmp, $TmpW)) {
            if (Test-Path -LiteralPath $leftover) { Remove-Item -Force -LiteralPath $leftover -ErrorAction SilentlyContinue }
        }
    }

    Write-Host "Installed to $Dest"
    if ($HasWindowed) {
        Write-Host "Also installed $DestW, for a desktop shortcut with no console window."
    }
    if (-not $SkipSmoke) { Write-Host $said }

    # The window, unless $env:SHAMBLES_NO_WINDOW = '1'. It is its own archive
    # because it carries Qt, which is far larger than everything else, so it
    # is kept out of the binary every command starts. Optional: shambles.exe
    # is installed above and works without it, so nothing here can undo that.
    #
    # The archive that matches the binary chosen above, so a Windows on Arm
    # machine that fell back to the x64 binary gets the x64 window too.
    # Checked against the same SHA256SUMS, unpacked beside its final place,
    # and swapped in by renaming, so a failed or mismatched download leaves
    # the window that was there. A release from before the window existed has
    # no such archive, which is reported and is not an error.
    $WindowFor = @{
        'shambles-windows-x64.exe'   = 'shambles-window-windows-x64.zip'
        'shambles-windows-arm64.exe' = 'shambles-window-windows-arm64.zip'
    }
    $WindowAsset = $WindowFor[$Asset]
    $WindowDir = Join-Path $DestDir 'window'
    Get-ChildItem -LiteralPath $DestDir -Directory -Filter '.window-*' -ErrorAction SilentlyContinue |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
    if ($WindowAsset -and $env:SHAMBLES_NO_WINDOW -ne '1') {
        $WindowTmp = Join-Path $DestDir ('.window-download-' + [Guid]::NewGuid().ToString('N'))
        try {
            New-Item -ItemType Directory -Force -Path $WindowTmp | Out-Null
            $Zip = Join-Path $WindowTmp 'window.zip'
            Write-Host "Downloading $WindowAsset..."
            $fetched = $false
            try {
                Get-Verified $WindowAsset $Zip
                $fetched = $true
            } catch {
                if ("$_" -match 'does not match the release checksum') {
                    Write-Warning "The window download does not match the release checksum, so it was not installed. Shambles itself is installed. Run the installer again to retry the window."
                } else {
                    Write-Host "This release has no window to download; 'shambles gui' opens the classic one."
                }
            }
            if ($fetched) {
                Expand-Archive -LiteralPath $Zip -DestinationPath $WindowTmp -Force
                $Unpacked = Join-Path $WindowTmp 'shambles-window'
                if (-not (Test-Path -LiteralPath (Join-Path $Unpacked 'shambles-window.exe'))) {
                    throw 'The window archive did not hold a window.'
                }
                $Aside = Join-Path $DestDir '.window-old'
                if (Test-Path -LiteralPath $Aside) { Remove-Item -Recurse -Force -LiteralPath $Aside }
                if (Test-Path -LiteralPath $WindowDir) {
                    try {
                        Move-Item -LiteralPath $WindowDir -Destination $Aside
                    } catch {
                        throw 'The window is running. Close it and run the installer again to update it.'
                    }
                }
                Move-Item -LiteralPath $Unpacked -Destination $WindowDir
                Remove-Item -Recurse -Force -LiteralPath $Aside -ErrorAction SilentlyContinue
                Write-Host "Installed the window to $WindowDir"
                Write-Host '  shambles gui    opens it'

                # A Start menu shortcut, so the window can be found without a
                # terminal. Per-user, so no admin. Rewritten on every install
                # because it names the window by path. Its own try: a shortcut
                # that cannot be written is not a reason to fail the install.
                # $env:SHAMBLES_NO_DESKTOP = '1' skips it.
                if ($env:SHAMBLES_NO_DESKTOP -ne '1') {
                    try {
                        $WindowExe = Join-Path $WindowDir 'shambles-window.exe'
                        $Programs = [Environment]::GetFolderPath('Programs')
                        $Shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut(
                            (Join-Path $Programs 'Shambles.lnk'))
                        $Shortcut.TargetPath = $WindowExe
                        $Shortcut.WorkingDirectory = $WindowDir
                        $Shortcut.IconLocation = "$WindowExe,0"
                        $Shortcut.Description = 'Switch between Claude Code and Codex accounts'
                        $Shortcut.Save()
                        Write-Host 'Added Shambles to your Start menu.'
                    } catch {
                        Write-Host "Could not add a Start menu shortcut ($($_.Exception.Message)); the window is still installed."
                    }
                }
            }
        } catch {
            Write-Warning "The window was not installed: $($_.Exception.Message) Shambles itself is installed."
        } finally {
            if (Test-Path -LiteralPath $WindowTmp) {
                Remove-Item -Recurse -Force -LiteralPath $WindowTmp -ErrorAction SilentlyContinue
            }
        }
    }

    # The user's PATH, read and written without expanding it. The obvious
    # call, [Environment]::GetEnvironmentVariable('Path', 'User'), returns
    # entries such as %USERPROFILE%\bin already expanded, and writing that
    # back replaces every variable in the user's PATH with today's value.
    if ($env:SHAMBLES_NO_PATH -ne '1') {
        $key = [Microsoft.Win32.Registry]::CurrentUser.OpenSubKey('Environment', $true)
        try {
            $raw = [string]$key.GetValue('Path', '', [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
            $entries = @($raw -split ';' | Where-Object { $_ -ne '' })
            $present = $entries | Where-Object {
                [Environment]::ExpandEnvironmentVariables($_).TrimEnd('\') -ieq $DestDir.TrimEnd('\')
            }
            if (-not $present) {
                $kind = [Microsoft.Win32.RegistryValueKind]::ExpandString
                if ($raw -ne '') { $kind = $key.GetValueKind('Path') }
                $key.SetValue('Path', ((@($entries) + $DestDir) -join ';'), $kind)
                Write-Host "Added $DestDir to your user PATH."
                # Writing the registry directly tells nobody. Setting and
                # clearing a variable through .NET broadcasts the change, so
                # Explorer and newly started terminals pick up the new PATH.
                [Environment]::SetEnvironmentVariable('SHAMBLES_PATH_REFRESH', '1', 'User')
                [Environment]::SetEnvironmentVariable('SHAMBLES_PATH_REFRESH', $null, 'User')
            }
        } finally {
            $key.Close()
        }
    }

    # The stored PATH above only reaches processes started after this one, so
    # the window that just ran the installer still cannot find shambles.
    # Putting it on this session's PATH as well means `shambles` works in the
    # terminal you are already standing in.
    if (($env:Path -split ';') -notcontains $DestDir) {
        $env:Path = "$env:Path;$DestDir"
    }

    Write-Host 'Note: Shambles binaries are unsigned; Windows SmartScreen may warn on first run.'
    Write-Host "Run 'shambles' to start. See the README for what is supported on each system."
    Write-Host 'Terminals opened before now will not find it until you start a new terminal.'
    Write-Host 'Done.'
} $Version
