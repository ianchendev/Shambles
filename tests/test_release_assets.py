from pathlib import Path

import pytest
from shambles.release_assets import (ARTIFACTS, WINDOWED_WINDOWS,
                                     UnsupportedPlatform, release_asset)

@pytest.mark.parametrize("sys_platform,machine,want", [
    ("linux", "x86_64", "shambles-linux-x86_64"),
    ("linux", "amd64", "shambles-linux-x86_64"),
    ("linux", "aarch64", "shambles-linux-arm64"),
    ("linux", "arm64", "shambles-linux-arm64"),
    ("darwin", "x86_64", "shambles-macos-x86_64"),
    ("darwin", "arm64", "shambles-macos-arm64"),
    ("win32", "AMD64", "shambles-windows-x64.exe"),
    ("win32", "x86_64", "shambles-windows-x64.exe"),
])
def test_release_asset_mapping(sys_platform, machine, want):
    assert release_asset(sys_platform=sys_platform, machine=machine) == want

def test_unsupported_platform_is_clear():
    with pytest.raises(UnsupportedPlatform, match="freebsd"):
        release_asset(sys_platform="freebsd", machine="x86_64")

def test_install_sh_mentions_every_unix_artifact():
    text = Path("scripts/install.sh").read_text(encoding="utf-8")
    for name in ARTIFACTS:
        if name.endswith(".exe"):
            continue
        assert name in text, f"install.sh missing {name}"

def test_install_ps1_mentions_windows_artifact():
    text = Path("scripts/install.ps1").read_text(encoding="utf-8")
    assert "shambles-windows-x64.exe" in text


def test_windows_ships_a_windowed_binary_too():
    """Two Windows binaries, on purpose.

    ``shambles.exe`` is console-subsystem so ``--version``, ``--help`` and
    ``list --json`` can actually print. 2.1.0 shipped only a ``--windowed``
    build under that name, which has no console at all: it printed nothing and
    crashed on the first write to stderr. ``shamblesw.exe`` is the windowed
    one, for a desktop shortcut that should not drag a console behind it.
    """
    assert WINDOWED_WINDOWS == "shamblesw-windows-x64.exe"
    assert WINDOWED_WINDOWS in ARTIFACTS


def test_install_ps1_installs_both_windows_binaries():
    text = Path("scripts/install.ps1").read_text(encoding="utf-8")
    assert "shambles-windows-x64.exe" in text
    assert WINDOWED_WINDOWS in text


def test_install_ps1_puts_shambles_on_path_for_the_current_terminal():
    """A persisted PATH only reaches processes started after it.

    The window that ran the installer was opened before it, so `shambles`
    was not found in the very terminal that had just installed it. Worse,
    the "open a new terminal" hint only printed when the entry was newly
    added, so anyone reinstalling got no explanation at all.
    """
    text = Path("scripts/install.ps1").read_text(encoding="utf-8")
    assert "$env:Path" in text, "must update PATH for the running session"
    assert "new terminal" in text.lower()
