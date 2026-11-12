"""The installers, against a release served from this machine.

``install.sh`` runs for real here: a local HTTP server stands in for GitHub
Releases, and the "binary" is a shell script that answers ``--version``.
``install.ps1`` cannot run on this platform, so what is checked locally is
what can be read off its text; the real-machine workflow runs it under
Windows PowerShell 5.1 and PowerShell 7.
"""

import hashlib
import os
import stat
import subprocess
from pathlib import Path

import pytest

from release_server import serve
from shambles import release_assets
from shambles.app import launch

#: Taken at import: conftest's ``no_real_window`` replaces it for each test.
REAL_WINDOW_BUNDLE = launch.window_bundle

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
ASSET = "shambles-linux-x86_64"
GOOD_BINARY = b"#!/bin/sh\necho 'shambles 9.9.9'\n"
BROKEN_BINARY = b"#!/bin/sh\necho 'cannot start: GLIBC_2.99 not found' >&2\nexit 127\n"

bash_only = pytest.mark.skipif(os.name == "nt", reason="bash installer")


@pytest.fixture
def release(tmp_path):
    """A directory served over HTTP, laid out like GitHub Releases."""
    root = tmp_path / "served"
    (root / "latest" / "download").mkdir(parents=True)

    def publish(binary, *, where="latest/download", sums=True, asset=ASSET):
        folder = root / where
        folder.mkdir(parents=True, exist_ok=True)
        (folder / asset).write_bytes(binary)
        if sums is True:
            digest = hashlib.sha256(binary).hexdigest()
            (folder / "SHA256SUMS").write_text(f"{digest}  {asset}\n")
        elif sums:
            (folder / "SHA256SUMS").write_text(sums)
        else:
            (folder / "SHA256SUMS").unlink(missing_ok=True)

    with serve(root) as base:
        publish.base = base
        publish.root = root
        yield publish


def install(release, home, *args, **env):
    full = {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "SHAMBLES_RELEASE_BASE": release.base,
        "SHAMBLES_FORCE_ASSET": ASSET,
        **env,
    }
    return subprocess.run(["bash", str(SCRIPTS / "install.sh"), *args],
                          capture_output=True, text=True, env=full, timeout=60)


def installed(home) -> Path:
    return Path(home) / ".local" / "bin" / "shambles"


@bash_only
def test_install_sh_installs_a_binary_that_runs(release, tmp_path):
    release(GOOD_BINARY)
    done = install(release, tmp_path)
    assert done.returncode == 0, done.stderr
    assert installed(tmp_path).read_bytes() == GOOD_BINARY
    assert installed(tmp_path).stat().st_mode & stat.S_IXUSR
    assert "Checksum verified." in done.stdout
    assert "shambles 9.9.9" in done.stdout


@bash_only
def test_install_sh_works_in_a_home_with_spaces_and_non_ascii_characters(
        release, tmp_path):
    home = tmp_path / "hôme with spaces 家"
    home.mkdir()
    release(GOOD_BINARY)
    done = install(release, home)
    assert done.returncode == 0, done.stderr
    assert installed(home).read_bytes() == GOOD_BINARY


@bash_only
def test_install_sh_fetches_a_pinned_release(release, tmp_path):
    release(GOOD_BINARY, where="download/v9.9.9")
    done = install(release, tmp_path, "v9.9.9")
    assert done.returncode == 0, done.stderr
    assert installed(tmp_path).is_file()


@bash_only
def test_a_download_that_does_not_match_its_checksum_is_not_installed(
        release, tmp_path):
    """And an install that was already there is left exactly as it was."""
    installed(tmp_path).parent.mkdir(parents=True)
    installed(tmp_path).write_bytes(b"the previous version")
    release(GOOD_BINARY, sums=f"{'0' * 64}  {ASSET}\n")
    done = install(release, tmp_path)
    assert done.returncode != 0
    assert "does not match" in done.stderr
    assert installed(tmp_path).read_bytes() == b"the previous version"
    assert sorted(p.name for p in installed(tmp_path).parent.iterdir()) == [
        "shambles"], "a temporary file was left behind"


@bash_only
def test_a_binary_that_cannot_start_is_not_installed(release, tmp_path):
    """The old script moved it into place first and then reported "Done".

    On a too-old glibc that left a broken ``shambles`` on PATH and no
    explanation. The check now runs before anything is replaced, shows what
    the loader said, and names the install that does work there.
    """
    installed(tmp_path).parent.mkdir(parents=True)
    installed(tmp_path).write_bytes(b"the previous version")
    release(BROKEN_BINARY)
    done = install(release, tmp_path)
    assert done.returncode != 0
    assert "GLIBC_2.99 not found" in done.stderr
    assert "pipx install" in done.stderr
    assert installed(tmp_path).read_bytes() == b"the previous version"


@bash_only
def test_a_release_without_checksums_installs_and_says_it_was_not_verified(
        release, tmp_path):
    release(GOOD_BINARY, sums=False)
    done = install(release, tmp_path)
    assert done.returncode == 0, done.stderr
    assert "not verified" in done.stderr
    assert installed(tmp_path).is_file()


@bash_only
def test_a_checksum_list_in_binary_mode_format_is_understood(release, tmp_path):
    """``sha256sum -b`` writes ``<hash> *<name>``."""
    digest = hashlib.sha256(GOOD_BINARY).hexdigest()
    release(GOOD_BINARY, sums=f"{'1' * 64}  other-file\n{digest} *{ASSET}\n")
    done = install(release, tmp_path)
    assert done.returncode == 0, done.stderr
    assert "Checksum verified." in done.stdout


@bash_only
def test_a_missing_release_fails_without_leaving_anything(release, tmp_path):
    done = install(release, tmp_path, "v0.0.0-does-not-exist")
    assert done.returncode != 0
    assert "Could not download" in done.stderr
    assert not installed(tmp_path).exists()
    assert list(installed(tmp_path).parent.iterdir()) == []


@bash_only
def test_install_sh_says_when_local_bin_is_not_on_path(release, tmp_path):
    release(GOOD_BINARY)
    done = install(release, tmp_path)
    assert 'export PATH="$HOME/.local/bin:$PATH"' in done.stdout
    on_path = install(
        release, tmp_path,
        PATH=f"{tmp_path}/.local/bin:{os.environ['PATH']}")
    assert "export PATH" not in on_path.stdout


def test_the_installers_name_exactly_the_assets_a_release_publishes():
    """Three places hold the table: the Python module, and each installer.
    An asset renamed in one of them is an install that 404s."""
    sh = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
    ps1 = (SCRIPTS / "install.ps1").read_text(encoding="utf-8")
    for asset in release_assets.ARTIFACTS:
        script = ps1 if asset.endswith(".exe") else sh
        assert asset in script, f"{asset} is published but no installer fetches it"


def test_install_ps1_is_plain_ascii():
    """Windows PowerShell 5.1 reads a script file with no byte-order mark in
    the system's legacy code page. One typographic character in a string and
    a saved copy of the installer prints mojibake -- or, with the wrong
    byte, stops parsing."""
    raw = (SCRIPTS / "install.ps1").read_bytes()
    offenders = sorted({chr(b) for b in raw if b > 0x7F})
    assert raw.isascii(), f"non-ASCII bytes in install.ps1: {offenders}"


def test_install_ps1_turns_on_tls_1_2_before_downloading():
    """Windows PowerShell 5.1 on an older Windows 10 offers TLS 1.0 by
    default, and GitHub refuses it."""
    text = (SCRIPTS / "install.ps1").read_text(encoding="utf-8")
    assert "Tls12" in text
    assert text.index("Tls12") < text.index("Invoke-WebRequest")



# -- the window ----------------------------------------------------------------

WINDOW = "shambles-window-linux-x86_64.tar.gz"


def window_archive(tmp_path, marker="new") -> bytes:
    """A window archive shaped like the real one: a ``shambles-window``
    folder holding the executable, its libraries and its icon."""
    import io
    import tarfile

    folder = tmp_path / "build" / marker / "shambles-window"
    (folder / "_internal").mkdir(parents=True)
    exe = folder / "shambles-window"
    exe.write_text("#!/bin/sh\necho window\n", encoding="utf-8")
    exe.chmod(0o755)
    (folder / "_internal" / "marker").write_text(marker, encoding="utf-8")
    (folder / "shambles.png").write_bytes(b"png")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        tar.add(folder, arcname="shambles-window")
    return buffer.getvalue()


def publish_window(release, data, *, listed=True, sum_of=None):
    """Put the window beside the binary and list it in SHA256SUMS, the way
    the release workflow's `sha256sum *` does."""
    folder = release.root / "latest" / "download"
    (folder / WINDOW).write_bytes(data)
    if listed:
        digest = hashlib.sha256(sum_of if sum_of is not None else data)
        with open(folder / "SHA256SUMS", "a", encoding="utf-8") as sums:
            sums.write(f"{digest.hexdigest()}  {WINDOW}\n")


def window_dir(home) -> Path:
    return Path(home) / ".local" / "share" / "shambles" / "window"


def desktop_entry(home) -> Path:
    return Path(home) / ".local" / "share" / "applications" / "shambles.desktop"


@bash_only
def test_install_sh_installs_and_verifies_the_window(release, tmp_path):
    release(GOOD_BINARY)
    publish_window(release, window_archive(tmp_path))
    home = tmp_path / "home"
    home.mkdir()

    done = install(release, home)

    assert done.returncode == 0, done.stderr
    assert done.stdout.count("Checksum verified.") == 2, \
        "the window was not checked against SHA256SUMS"
    exe = window_dir(home) / "shambles-window"
    assert exe.is_file() and exe.stat().st_mode & stat.S_IXUSR
    assert sorted(p.name for p in window_dir(home).parent.iterdir()) == \
        ["window"], "a temporary folder was left behind"


@bash_only
def test_the_installer_puts_the_window_where_shambles_looks(release, tmp_path):
    release(GOOD_BINARY)
    publish_window(release, window_archive(tmp_path))
    home = tmp_path / "home"
    home.mkdir()
    install(release, home)

    found = REAL_WINDOW_BUNDLE(env={}, platform="linux",
                               executable=installed(home), home=home)
    assert found == window_dir(home) / "shambles-window"


@bash_only
def test_a_window_that_fails_its_checksum_is_not_installed(release, tmp_path):
    """Shambles itself still installs; the window that was there stays."""
    release(GOOD_BINARY)
    publish_window(release, window_archive(tmp_path), sum_of=b"something else")
    home = tmp_path / "home"
    (window_dir(home)).mkdir(parents=True)
    (window_dir(home) / "shambles-window").write_text("previous")

    done = install(release, home)

    assert done.returncode == 0, done.stderr
    assert installed(home).read_bytes() == GOOD_BINARY
    assert "does not match" in done.stderr
    assert (window_dir(home) / "shambles-window").read_text() == "previous"
    assert sorted(p.name for p in window_dir(home).parent.iterdir()) == \
        ["window"], "a temporary folder was left behind"
    assert not desktop_entry(home).exists()


@bash_only
def test_a_new_window_replaces_the_old_one_completely(release, tmp_path):
    """A library left over from the previous version must not survive inside
    the new one, where the new Qt would try to load it."""
    release(GOOD_BINARY)
    publish_window(release, window_archive(tmp_path))
    home = tmp_path / "home"
    (window_dir(home) / "_internal").mkdir(parents=True)
    (window_dir(home) / "_internal" / "stale.so").write_text("old")

    install(release, home)

    assert not (window_dir(home) / "_internal" / "stale.so").exists()
    assert (window_dir(home) / "_internal" / "marker").read_text() == "new"


@bash_only
def test_a_release_with_no_window_still_installs(release, tmp_path):
    release(GOOD_BINARY)
    home = tmp_path / "home"
    home.mkdir()

    done = install(release, home)

    assert done.returncode == 0, done.stderr
    assert installed(home).is_file()
    assert "classic one" in done.stdout
    assert not window_dir(home).exists()
    assert not desktop_entry(home).exists()


@bash_only
def test_the_window_and_its_launcher_can_be_skipped(release, tmp_path):
    release(GOOD_BINARY)
    publish_window(release, window_archive(tmp_path))
    home = tmp_path / "home"
    home.mkdir()

    install(release, home, SHAMBLES_NO_DESKTOP="1")
    assert window_dir(home).is_dir() and not desktop_entry(home).exists()

    other = tmp_path / "other"
    other.mkdir()
    install(release, other, SHAMBLES_NO_WINDOW="1")
    assert not window_dir(other).exists()


@bash_only
def test_install_sh_adds_a_launcher_entry_for_the_window(release, tmp_path):
    release(GOOD_BINARY)
    publish_window(release, window_archive(tmp_path))
    home = tmp_path / "hôme with spaces"
    home.mkdir()

    done = install(release, home)

    assert done.returncode == 0, done.stderr
    entry = dict(line.split("=", 1) for line in
                 desktop_entry(home).read_text().splitlines() if "=" in line)
    assert entry["Type"] == "Application" and entry["Name"] == "Shambles"
    assert entry["Terminal"] == "false"
    # Quoted, so a home directory with a space in it still launches.
    assert entry["Exec"] == f'"{window_dir(home)}/shambles-window"'
    assert Path(entry["Exec"].strip('"')).is_file()
    assert Path(entry["Icon"]).is_file()


def test_every_binary_has_its_window_named_by_its_installer():
    """The window archives are a second table in three places, like the
    binaries above."""
    sh = (SCRIPTS / "install.sh").read_text(encoding="utf-8")
    ps1 = (SCRIPTS / "install.ps1").read_text(encoding="utf-8")
    for asset in release_assets.WINDOW_ARTIFACTS:
        script = ps1 if asset.endswith(".zip") else sh
        assert asset in script, f"{asset} is published but no installer fetches it"


def test_install_ps1_adds_a_per_user_start_menu_shortcut():
    """Read here; run for real by tests/real/test_installers.py."""
    text = (SCRIPTS / "install.ps1").read_text(encoding="utf-8")
    start = text.index("# A Start menu shortcut")
    block = text[start:start + 1500]
    assert "GetFolderPath('Programs')" in block, "must be the per-user menu"
    assert "shambles-window.exe" in block and "Shambles.lnk" in block
    assert "SHAMBLES_NO_DESKTOP" in block
