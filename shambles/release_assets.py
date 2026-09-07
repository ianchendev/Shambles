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
}

ARTIFACTS = frozenset(_LINUX.values()) | frozenset(_DARWIN.values()) | frozenset(_WIN.values())

def release_asset(*, sys_platform: str, machine: str) -> str:
    table = {"linux": _LINUX, "darwin": _DARWIN, "win32": _WIN}.get(sys_platform)
    if table is None or machine not in table:
        raise UnsupportedPlatform(
            f"No Shambles binary for {sys_platform}-{machine} yet")
    return table[machine]
