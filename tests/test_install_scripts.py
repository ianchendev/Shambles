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
