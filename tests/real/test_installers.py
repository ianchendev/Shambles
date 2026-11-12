"""The install scripts, run for real on the system they are for.

Same rules as the rest of this directory: disposable CI runners only. The
binary served is the one this job just built, from a local HTTP server laid
out like GitHub Releases, so the scripts' own platform detection, checksum
check and PATH handling all run unmodified. One test per system then points
the script at the real latest release, which is the only check anywhere that
the binaries actually published start on that system.
"""

import hashlib
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from shambles import release_assets
from tests.release_server import serve

REAL = (os.environ.get("SHAMBLES_REAL_MACHINE") == "1"
        and os.environ.get("GITHUB_ACTIONS") == "true")
BINARY = os.environ.get("SHAMBLES_BIN")

pytestmark = pytest.mark.skipif(
    not (REAL and BINARY),
    reason="runs the installers for real; needs a disposable CI runner and "
           "a built binary (SHAMBLES_BIN)")

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
WINDOWS = sys.platform == "win32"
posix_only = pytest.mark.skipif(WINDOWS, reason="install.sh")
windows_only = pytest.mark.skipif(not WINDOWS, reason="install.ps1")


def this_asset() -> str:
    return release_assets.release_asset(sys_platform=sys.platform,
                                        machine=platform.machine())


def show(done):
    print(f"-> exit {done.returncode}")
    if done.stdout.strip():
        print(done.stdout.strip())
    if done.stderr.strip():
        print("stderr:", done.stderr.strip()[:3000])
    return done


@pytest.fixture
def release(tmp_path):
    """This job's binary, served the way GitHub Releases serves one."""
    root = tmp_path / "served"
    root.mkdir()

    def publish(*, where="latest/download", names=None, corrupt_sums=False):
        folder = root / where
        folder.mkdir(parents=True, exist_ok=True)
        built = Path(BINARY)
        files = {}
        console = this_asset()
        if names is not None:
            console, windowed = names
        elif WINDOWS:
            windowed = console.replace("shambles-", "shamblesw-", 1)
        else:
            windowed = None
        files[console] = built.read_bytes()
        twin = built.with_name("shamblesw.exe")
        if windowed and twin.exists():
            files[windowed] = twin.read_bytes()
        lines = []
        for name, data in files.items():
            (folder / name).write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            if corrupt_sums:
                digest = "0" * 64
            lines.append(f"{digest}  {name}")
        (folder / "SHA256SUMS").write_text("\n".join(lines) + "\n")
        return files

    shutil.copy(SCRIPTS / "install.ps1", root / "install.ps1")
    shutil.copy(SCRIPTS / "install.sh", root / "install.sh")
    with serve(root) as base:
        publish.base = base
        publish.root = root
        yield publish


# -- macOS and Linux ----------------------------------------------------------


def run_sh(home, *args, base=None, **extra):
    env = dict(os.environ)
    env.pop("SHAMBLES_FORCE_ASSET", None)
    env["HOME"] = str(home)
    if base:
        env["SHAMBLES_RELEASE_BASE"] = base
    env.update(extra)
    return show(subprocess.run(["bash", str(SCRIPTS / "install.sh"), *args],
                               capture_output=True, text=True, env=env,
                               timeout=300))


@posix_only
def test_install_sh_installs_this_systems_binary_into_an_awkward_home(
        release, tmp_path):
    """No forced asset: the script works out the system and architecture
    itself, which is the part no other machine can check for this one."""
    home = tmp_path / "hôme with spaces 家"
    home.mkdir()
    served = release()
    done = run_sh(home, base=release.base)
    assert done.returncode == 0
    assert "Checksum verified." in done.stdout
    installed = home / ".local" / "bin" / "shambles"
    assert installed.read_bytes() == served[this_asset()]

    version = subprocess.run([str(installed), "--version"],
                             capture_output=True, text=True, timeout=120)
    assert version.returncode == 0 and version.stdout.startswith("shambles ")
    listing = subprocess.run(
        [str(installed), "list", "--json", "--home", str(home)],
        capture_output=True, text=True, timeout=120)
    assert listing.returncode == 0 and '"groups"' in listing.stdout


@posix_only
def test_install_sh_piped_into_bash_the_way_the_readme_says(release, tmp_path):
    release()
    env = dict(os.environ, HOME=str(tmp_path), SHAMBLES_RELEASE_BASE=release.base)
    done = show(subprocess.run(
        ["bash", "-c", f"curl -fsSL {release.base}/install.sh | bash"],
        capture_output=True, text=True, env=env, timeout=300))
    assert done.returncode == 0
    assert (tmp_path / ".local" / "bin" / "shambles").is_file()


@posix_only
def test_install_sh_refuses_a_download_that_fails_its_checksum(release, tmp_path):
    release(corrupt_sums=True)
    done = run_sh(tmp_path, base=release.base)
    assert done.returncode != 0
    assert "does not match" in done.stderr
    assert not (tmp_path / ".local" / "bin" / "shambles").exists()


@posix_only
def test_the_published_unix_release_installs_and_starts_here(tmp_path):
    """The real one-liner against the real latest release.

    Everything else in this file serves the binary this job built. This is
    the check that what was actually *published* for this system downloads,
    passes its checksum and runs.
    """
    done = run_sh(tmp_path)
    assert done.returncode == 0
    installed = tmp_path / ".local" / "bin" / "shambles"
    version = subprocess.run([str(installed), "--version"],
                             capture_output=True, text=True, timeout=120)
    print("published binary says:", version.stdout.strip(), version.stderr.strip())
    assert version.returncode == 0 and version.stdout.startswith("shambles ")


# -- Windows ------------------------------------------------------------------

SHELLS = [name for name in ("powershell", "pwsh") if shutil.which(name)]


def windows_env(local_app_data, base=None, **extra):
    env = dict(os.environ)
    for name in ("SHAMBLES_FORCE_ASSET", "SHAMBLES_VERSION", "SHAMBLES_NO_PATH"):
        env.pop(name, None)
    env["LOCALAPPDATA"] = str(local_app_data)
    if base:
        env["SHAMBLES_RELEASE_BASE"] = base
    env.update(extra)
    return env


def run_ps(shell, command, env, *, policy="Bypass"):
    return show(subprocess.run(
        [shutil.which(shell), "-NoProfile", "-ExecutionPolicy", policy,
         "-Command", command],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=600))


def user_path_raw():
    """``(value, kind)`` of the user's PATH, exactly as stored."""
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as key:
        try:
            return winreg.QueryValueEx(key, "Path")
        except FileNotFoundError:
            return "", None


@windows_only
@pytest.mark.parametrize("shell", SHELLS)
def test_install_ps1_piped_into_iex_under_a_restricted_policy(
        release, tmp_path, shell):
    """The README's one-liner, on a machine at the default client policy.

    Restricted forbids running script *files*. A script piped into ``iex``
    is not one, so the one-liner works where a saved copy would not. Run
    under both Windows PowerShell 5.1 and PowerShell 7, into a folder with
    spaces and non-ASCII characters in its name.
    """
    local = tmp_path / "Lôcal App Data 家"
    local.mkdir()
    served = release()
    done = run_ps(shell, f"irm {release.base}/install.ps1 | iex",
                  windows_env(local, release.base, SHAMBLES_NO_PATH="1"),
                  policy="Restricted")
    assert done.returncode == 0
    assert "Checksum verified" in done.stdout
    console = local / "Shambles" / "shambles.exe"
    assert console.read_bytes() == served[this_asset()]
    assert (local / "Shambles" / "shamblesw.exe").is_file()
    leftovers = [p.name for p in (local / "Shambles").iterdir()
                 if p.name not in ("shambles.exe", "shamblesw.exe")]
    assert leftovers == [], f"left behind: {leftovers}"

    version = subprocess.run([str(console), "--version"],
                             capture_output=True, text=True, timeout=120)
    assert version.returncode == 0 and version.stdout.startswith("shambles ")


@windows_only
@pytest.mark.parametrize("shell", SHELLS)
def test_the_installer_leaves_the_callers_session_as_it_found_it(
        release, tmp_path, shell):
    """Piped into ``iex`` a script runs in the caller's own session. The old
    one left ``$ErrorActionPreference = 'Stop'`` behind in the window that
    ran it, which changes how every later command in that window fails."""
    release()
    done = run_ps(
        shell,
        f"irm {release.base}/install.ps1 | iex; "
        "Write-Host \"PREFERENCE=$ErrorActionPreference\"; "
        "Write-Host \"LEAKED=$([bool](Get-Variable DestDir -ErrorAction SilentlyContinue))\"",
        windows_env(tmp_path, release.base, SHAMBLES_NO_PATH="1"))
    assert done.returncode == 0
    assert "PREFERENCE=Continue" in done.stdout
    assert "LEAKED=False" in done.stdout


@windows_only
def test_install_ps1_from_cmd_the_way_the_readme_says(release, tmp_path):
    release()
    env = windows_env(tmp_path, release.base, SHAMBLES_NO_PATH="1")
    done = show(subprocess.run(
        ["cmd", "/c", "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-Command", f"irm {release.base}/install.ps1 | iex"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env, timeout=600))
    assert done.returncode == 0
    assert (tmp_path / "Shambles" / "shambles.exe").is_file()


@windows_only
@pytest.mark.parametrize("shell", SHELLS)
def test_a_saved_copy_takes_a_version(release, tmp_path, shell):
    release(where="download/v9.9.9")
    done = show(subprocess.run(
        [shutil.which(shell), "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(SCRIPTS / "install.ps1"), "-Version", "v9.9.9"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=windows_env(tmp_path, release.base, SHAMBLES_NO_PATH="1"),
        timeout=600))
    assert done.returncode == 0
    assert (tmp_path / "Shambles" / "shambles.exe").is_file()


@windows_only
@pytest.mark.parametrize("shell", SHELLS)
def test_install_ps1_refuses_a_download_that_fails_its_checksum(
        release, tmp_path, shell):
    release(corrupt_sums=True)
    done = run_ps(shell, f"irm {release.base}/install.ps1 | iex",
                  windows_env(tmp_path, release.base, SHAMBLES_NO_PATH="1"))
    assert "does not match the release checksum" in (done.stdout + done.stderr)
    folder = tmp_path / "Shambles"
    assert not (folder / "shambles.exe").exists()
    assert [p.name for p in folder.iterdir()] == []


@windows_only
def test_a_release_with_only_the_x64_build_still_installs(release, tmp_path):
    """On Windows on Arm the installer asks for the native build first and
    falls back to x64, which Windows 11 runs under emulation. On x64 this is
    simply the normal path."""
    release(names=("shambles-windows-x64.exe", "shamblesw-windows-x64.exe"))
    done = run_ps(SHELLS[0], f"irm {release.base}/install.ps1 | iex",
                  windows_env(tmp_path, release.base, SHAMBLES_NO_PATH="1"))
    assert done.returncode == 0
    assert (tmp_path / "Shambles" / "shambles.exe").is_file()


@windows_only
def test_the_users_path_gains_one_entry_and_keeps_its_variables(release, tmp_path):
    """The stored PATH is a string with ``%VARIABLES%`` in it. Reading it
    the obvious way expands them, and writing that back replaces every
    variable in the user's PATH with whatever it meant today."""
    import winreg
    sentinel = r"%USERPROFILE%\shambles-ci-sentinel"
    before, _kind = user_path_raw()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                        winreg.KEY_SET_VALUE) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ,
                          ";".join(p for p in (before, sentinel) if p))
    release()
    target = str(tmp_path / "Shambles")
    try:
        for _ in range(2):  # the second run must not add it again
            done = run_ps(SHELLS[0], f"irm {release.base}/install.ps1 | iex",
                          windows_env(tmp_path, release.base))
            assert done.returncode == 0
        after, kind = user_path_raw()
        entries = after.split(";")
        assert sentinel in entries, "a %VARIABLE% entry was expanded or lost"
        assert entries.count(target) == 1
        assert kind == winreg.REG_EXPAND_SZ
    finally:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, before)


@windows_only
def test_reinstalling_over_a_running_shambles(release, tmp_path):
    """Windows will not overwrite a program that is running. The installer
    renames the old binary aside instead of failing with a sharing error."""
    release()
    env = windows_env(tmp_path, release.base, SHAMBLES_NO_PATH="1")
    command = f"irm {release.base}/install.ps1 | iex"
    assert run_ps(SHELLS[0], command, env).returncode == 0

    windowed = tmp_path / "Shambles" / "shamblesw.exe"
    scratch = tmp_path / "scratch home"
    scratch.mkdir()
    running = subprocess.Popen([str(windowed), "gui", "--home", str(scratch)])
    try:
        time.sleep(8)
        if running.poll() is not None:
            pytest.skip(f"the window did not stay open on this runner "
                        f"(exit {running.returncode}); nothing to replace")
        done = run_ps(SHELLS[0], command, env)
        assert done.returncode == 0, "reinstall failed while Shambles was open"
        assert windowed.is_file()
        version = subprocess.run(
            [str(tmp_path / "Shambles" / "shambles.exe"), "--version"],
            capture_output=True, text=True, timeout=120)
        assert version.returncode == 0
    finally:
        running.kill()
        running.wait(timeout=30)


@windows_only
def test_the_published_windows_release_installs_and_starts_here(tmp_path):
    """The real one-liner's script against the real latest release. On
    Windows on Arm this is also the check that the x64 build runs there."""
    done = show(subprocess.run(
        [shutil.which(SHELLS[0]), "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-File", str(SCRIPTS / "install.ps1")],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=windows_env(tmp_path, SHAMBLES_NO_PATH="1"), timeout=600))
    assert done.returncode == 0
    console = tmp_path / "Shambles" / "shambles.exe"
    version = subprocess.run([str(console), "--version"],
                             capture_output=True, text=True, timeout=120)
    print("published binary says:", version.stdout.strip(), version.stderr.strip())
    assert version.returncode == 0 and version.stdout.startswith("shambles ")



# -- the window ----------------------------------------------------------------


def window_zip(folder: Path) -> bytes:
    """A window archive shaped like the real one. The executable is this
    job's own binary under the window's name: the installer only needs a
    real file there, and the Start menu needs a real program to point at."""
    import io
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.write(BINARY, "shambles-window/shambles-window.exe")
        archive.writestr("shambles-window/shambles.png", b"png")
        archive.writestr("shambles-window/_internal/marker", b"new")
    return buffer.getvalue()


def publish_window(release, name):
    folder = Path(release.root) / "latest" / "download"
    data = window_zip(folder)
    (folder / name).write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    with open(folder / "SHA256SUMS", "a", encoding="utf-8") as sums:
        sums.write(f"{digest}  {name}\n")


def start_menu_shortcut(shell, expected):
    """``"MATCH"``, ``"OTHER"`` or ``"MISSING"``: whether the per-user
    Shambles shortcut points at ``expected``.

    Compared inside PowerShell, with the expected path handed over in the
    environment, so neither direction depends on the console's code page --
    the point of one of these tests is a path that code page cannot hold.
    Read through Shell.Application, which is Unicode, not WScript.Shell,
    which is not.
    """
    env = dict(os.environ)
    env["SHAMBLES_EXPECT"] = str(expected)
    done = run_ps(shell, (
        "$p = Join-Path ([Environment]::GetFolderPath('Programs')) "
        "'Shambles.lnk'; if (-not (Test-Path -LiteralPath $p)) { "
        "'MISSING'; return }; $l = (New-Object -ComObject "
        "Shell.Application).NameSpace((Split-Path $p)).ParseName("
        "'Shambles.lnk').GetLink; if ($l.Path -eq $env:SHAMBLES_EXPECT) "
        "{ 'MATCH' } else { 'OTHER' }"), env)
    words = done.stdout.split()
    return words[-1] if words else "MISSING"


@windows_only
@pytest.mark.parametrize("shell", SHELLS)
def test_the_start_menu_shortcut_in_a_plain_folder(release, tmp_path, shell):
    """The shortcut on its own, in a folder whose name is plain ASCII, so a
    failure here cannot be the folder name's fault."""
    local = tmp_path / "plain"
    local.mkdir()
    release()
    window = this_asset().replace("shambles-windows-",
                                  "shambles-window-windows-") \
                         .replace(".exe", ".zip")
    publish_window(release, window)

    done = run_ps(shell, f"irm {release.base}/install.ps1 | iex",
                  windows_env(local, release.base, SHAMBLES_NO_PATH="1"))

    assert done.returncode == 0
    assert "Could not add a Start menu shortcut" not in done.stdout
    assert start_menu_shortcut(
        shell, local / "Shambles" / "window" / "shambles-window.exe") == "MATCH"


@windows_only
@pytest.mark.parametrize("shell", SHELLS)
def test_install_ps1_installs_the_window_and_a_start_menu_shortcut(
        release, tmp_path, shell):
    """The one part of the window's install that could only be read until
    now: unpacking the zip, swapping it in, and the shortcut, written by a
    COM object under Windows PowerShell 5.1 and PowerShell 7."""
    local = tmp_path / "Lôcal App Data 家"
    local.mkdir()
    release()
    asset = this_asset()
    window = asset.replace("shambles-windows-", "shambles-window-windows-") \
                  .replace(".exe", ".zip")
    assert window in release_assets.WINDOW_ARTIFACTS
    publish_window(release, window)

    done = run_ps(shell, f"irm {release.base}/install.ps1 | iex",
                  windows_env(local, release.base, SHAMBLES_NO_PATH="1"))

    assert done.returncode == 0
    installed_window = local / "Shambles" / "window" / "shambles-window.exe"
    assert installed_window.is_file()
    assert done.stdout.count("Checksum verified") >= 2, \
        "the window was not checked against SHA256SUMS"
    leftovers = [p.name for p in (local / "Shambles").iterdir()
                 if p.name not in ("shambles.exe", "shamblesw.exe", "window")]
    assert leftovers == [], f"left behind: {leftovers}"

    # The folder name holds characters outside the ANSI code page, which is
    # the case WScript.Shell refuses and the IShellLinkW fallback exists for.
    assert "Could not add a Start menu shortcut" not in done.stdout
    assert start_menu_shortcut(shell, installed_window) == "MATCH"

    # The shortcut is left for the next parametrisation to overwrite; the
    # runner is thrown away afterwards.


@windows_only
def test_a_window_that_fails_its_checksum_leaves_shambles_installed(
        release, tmp_path):
    release()
    window = this_asset().replace("shambles-windows-",
                                  "shambles-window-windows-") \
                         .replace(".exe", ".zip")
    folder = Path(release.root) / "latest" / "download"
    (folder / window).write_bytes(window_zip(folder))
    with open(folder / "SHA256SUMS", "a", encoding="utf-8") as sums:
        sums.write(f"{'0' * 64}  {window}\n")

    done = run_ps(SHELLS[0], f"irm {release.base}/install.ps1 | iex",
                  windows_env(tmp_path, release.base, SHAMBLES_NO_PATH="1",
                              SHAMBLES_NO_DESKTOP="1"))

    assert done.returncode == 0
    assert (tmp_path / "Shambles" / "shambles.exe").is_file()
    assert not (tmp_path / "Shambles" / "window").exists()
    assert "does not match" in done.stdout + done.stderr
