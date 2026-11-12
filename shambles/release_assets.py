"""Map host OS/arch to GitHub Release artifact basenames.

Kept in Python so tests and docs stay honest. ``scripts/install.sh`` and
``scripts/install.ps1`` embed the same table; Task 2's sync test fails if they
drift.
"""

class UnsupportedPlatform(ValueError):
    pass

_LINUX = {
    "x86_64": "shambles-linux-x86_64",
    "amd64": "shambles-linux-x86_64",
    "aarch64": "shambles-linux-arm64",
    "arm64": "shambles-linux-arm64",
}
_DARWIN = {
    "x86_64": "shambles-macos-x86_64",
    "arm64": "shambles-macos-arm64",
}
_WIN = {
    "AMD64": "shambles-windows-x64.exe",
    "x86_64": "shambles-windows-x64.exe",
    "amd64": "shambles-windows-x64.exe",
    "ARM64": "shambles-windows-arm64.exe",
    "arm64": "shambles-windows-arm64.exe",
}

#: The windowed twin of the Windows binary. ``shambles.exe`` is
#: console-subsystem so it can print; a console-subsystem program launched
#: from a desktop shortcut also flashes a terminal, which is what this one
#: exists to avoid. Not in the platform table above because it is never the
#: answer to "which binary runs here", only an extra file to fetch alongside.
WINDOWED_WINDOWS = "shamblesw-windows-x64.exe"
WINDOWED_WINDOWS_ARM64 = "shamblesw-windows-arm64.exe"

ARTIFACTS = (frozenset(_LINUX.values()) | frozenset(_DARWIN.values())
             | frozenset(_WIN.values())
             | {WINDOWED_WINDOWS, WINDOWED_WINDOWS_ARM64})

#: The window, which ships beside the binary rather than inside it: Qt is
#: about three times the size of everything else, and unpacking it on every
#: launch would slow the commands that never open a window. One archive per
#: platform holding a ``shambles-window`` folder. Like the windowed twin, it
#: is never the answer to "which binary runs here", only an extra to fetch.
_WINDOW = {
    "shambles-linux-x86_64": "shambles-window-linux-x86_64.tar.gz",
    "shambles-linux-arm64": "shambles-window-linux-arm64.tar.gz",
    "shambles-macos-x86_64": "shambles-window-macos-x86_64.tar.gz",
    "shambles-macos-arm64": "shambles-window-macos-arm64.tar.gz",
    "shambles-windows-x64.exe": "shambles-window-windows-x64.zip",
    "shambles-windows-arm64.exe": "shambles-window-windows-arm64.zip",
}

WINDOW_ARTIFACTS = frozenset(_WINDOW.values())


def window_asset(*, sys_platform: str, machine: str) -> str:
    """The window archive that goes with this platform's binary."""
    return _WINDOW[release_asset(sys_platform=sys_platform, machine=machine)]

def release_asset(*, sys_platform: str, machine: str) -> str:
    table = {"linux": _LINUX, "darwin": _DARWIN, "win32": _WIN}.get(sys_platform)
    if table is None or machine not in table:
        raise UnsupportedPlatform(
            f"No Shambles binary for {sys_platform}-{machine} yet")
    return table[machine]
