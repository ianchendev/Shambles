import pytest
from shambles.release_assets import UnsupportedPlatform, release_asset

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
