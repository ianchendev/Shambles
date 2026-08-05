"""The packaging metadata has to stay in step with the code it ships."""

import os
import subprocess
import sys

import pytest

import shambles

try:
    import tomllib
except ModuleNotFoundError:  # stdlib only from 3.11; we still support 3.10
    tomllib = None

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _pyproject():
    if tomllib is None:
        pytest.skip("tomllib needs Python 3.11+; metadata checks run on newer jobs")
    with open(os.path.join(REPO, "pyproject.toml"), "rb") as fh:
        return tomllib.load(fh)


def test_version_matches_pyproject():
    """A release tag is cut from pyproject; --version reads the package. If
    they drift, users report a version that does not exist."""
    assert shambles.__version__ == _pyproject()["project"]["version"]


def test_console_script_points_at_a_real_callable():
    from shambles.__main__ import main

    target = _pyproject()["project"]["scripts"]["shambles"]
    assert target == "shambles.__main__:main"
    assert callable(main)


def test_declares_no_runtime_dependencies():
    """Tkinter ships with Python and is not installable from PyPI, so the
    dependency list must stay empty -- otherwise pipx install fails."""
    assert _pyproject()["project"].get("dependencies", []) == []


def test_every_module_is_packaged():
    packaged = _pyproject()["tool"]["setuptools"]["packages"]
    assert "shambles" in packaged


def test_version_flag_prints_and_exits_zero():
    out = subprocess.run(
        [sys.executable, "-m", "shambles", "--version"],
        capture_output=True, text=True, cwd=REPO,
    )
    assert out.returncode == 0
    assert shambles.__version__ in out.stdout


def test_help_flag_exits_zero_without_a_display():
    out = subprocess.run(
        [sys.executable, "-m", "shambles", "--help"],
        capture_output=True, text=True, cwd=REPO,
        env={**os.environ, "DISPLAY": "", "WAYLAND_DISPLAY": ""},
    )
    assert out.returncode == 0
    assert "shambles" in out.stdout.lower()
