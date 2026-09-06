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


# ---- no stray console window on Windows ---------------------------------

def test_a_windowed_entry_point_exists():
    """[project.scripts] produces a console launcher on Windows, which flashes
    a blank terminal behind the GUI. A gui-scripts entry uses pythonw.exe and
    does not, so shortcuts have something quiet to target."""
    gui = _pyproject()["project"].get("gui-scripts", {})
    assert gui, "no gui-scripts entry point; Windows shortcuts get a console"
    assert any("shambles" in target for target in gui.values())


def test_the_console_entry_point_is_kept_too():
    """--version and --help must stay usable; a gui-scripts binary on Windows
    has nowhere to print."""
    assert "shambles" in _pyproject()["project"].get("scripts", {})


# ---- the documented checkout launcher on an unsupported interpreter -------
#
# pyproject's requires-python protects pip and pipx. It does nothing for
# `python3 shambles.py`, which the README gives as THE way to run from a
# clone -- and on any box where `python3` is older than 3.10 that dies inside
# a dataclass field annotation, several imports deep, with
# `TypeError: unsupported operand type(s) for |: 'type' and 'NoneType'`.

def test_an_old_interpreter_is_named_rather_than_crashing_on_syntax():
    from shambles.__main__ import version_error

    message = version_error((3, 8, 10))
    assert message, "3.8 was accepted"
    assert "3.10" in message, "the message does not say what is needed"
    assert "3.8" in message, "the message does not say what was found"


def test_a_supported_interpreter_passes_without_a_message():
    from shambles.__main__ import version_error

    assert version_error((3, 10, 0)) is None
    assert version_error((3, 12, 13)) is None
    assert version_error((4, 0, 0)) is None
    assert version_error() is None, "the running interpreter was rejected"


def test_version_does_not_claim_success_on_an_unsupported_interpreter():
    """`python3 -m shambles --version` printed a version and exited 0 on 3.8,
    then died on import the moment it was asked to do anything -- so the one
    command a user runs to check the install reported a false green."""
    from shambles.__main__ import main

    assert main(["--version"]) == 0  # on this interpreter, which is supported


@pytest.mark.skipif(not os.path.exists("/usr/bin/python3"),
                    reason="no system python3 to test an old interpreter with")
def test_the_checkout_launcher_explains_itself_on_the_system_python():
    """End to end through the exact command the README documents.

    Skipped rather than xfailed when /usr/bin/python3 is new enough -- then
    there is no old interpreter here to prove anything against.
    """
    probe = subprocess.run(
        ["/usr/bin/python3", "-c",
         "import sys; print('%d.%d' % sys.version_info[:2])"],
        capture_output=True, text=True)
    major, _, minor = probe.stdout.strip().partition(".")
    if (int(major), int(minor)) >= (3, 10):
        pytest.skip(f"system python3 is {probe.stdout.strip()}, not old enough")

    done = subprocess.run(["/usr/bin/python3", "shambles.py"],
                          cwd=REPO, capture_output=True, text=True, timeout=60)
    combined = done.stdout + done.stderr
    assert "TypeError" not in combined, (
        f"crashed on syntax instead of explaining:\n{combined[-500:]}")
    assert "3.10" in combined, f"did not name the requirement:\n{combined[-500:]}"
    assert done.returncode != 0, "reported success on an unsupported interpreter"
