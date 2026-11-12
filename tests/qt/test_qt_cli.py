"""`shambles gui --new`: reaching the Qt window, and failing politely."""

import pytest

from shambles.app import cli


def test_gui_new_opens_the_window_on_the_requested_home(monkeypatch, home):
    seen = {}

    def run_window(service, *, motion=True):
        seen.update(home=service.paths.home, motion=motion)
        return 0

    monkeypatch.setattr(cli, "_window_entry", lambda: run_window)

    assert cli.main(["gui", "--new", "--home", str(home)]) == 0
    assert seen == {"home": home, "motion": True}


def test_gui_new_passes_no_motion_through(monkeypatch, home):
    seen = {}
    monkeypatch.setattr(cli, "_window_entry", lambda: (
        lambda service, *, motion=True: seen.update(motion=motion) or 0))

    cli.main(["--no-motion", "gui", "--new", "--home", str(home)])

    assert seen == {"motion": False}


@pytest.mark.parametrize("reason", [
    "No module named 'PySide6'",
    "libEGL.so.1: cannot open shared object file: No such file or directory",
])
def test_a_window_that_cannot_load_says_why_and_what_to_do(
        monkeypatch, capsys, home, reason):
    """Not installed and installed-but-unloadable both arrive as ImportError."""
    def missing():
        raise ImportError(reason)

    monkeypatch.setattr(cli, "_window_entry", missing)

    assert cli.main(["gui", "--new", "--home", str(home)]) == cli.EXIT_FAILED
    err = capsys.readouterr().err
    assert reason in err
    assert "shambles[gui]" in err and "libegl1" in err


def test_plain_gui_still_opens_the_classic_window(monkeypatch, home):
    """The new window is opt-in until the cutover."""
    from shambles import gui

    opened = []
    monkeypatch.setattr(gui, "run", lambda paths=None: opened.append(paths) or 0)
    monkeypatch.setattr(cli, "_window_entry",
                        lambda: pytest.fail("opened the new window unasked"))

    assert cli.main(["gui", "--home", str(home)]) == 0
    assert len(opened) == 1


def test_the_window_package_ships_its_qml_and_fonts():
    """Read from disk at runtime; undeclared, an installed copy opens blank."""
    from pathlib import Path

    # stdlib only from 3.11, and 3.10 is still supported; the same metadata
    # is checked on the newer jobs.
    tomllib = pytest.importorskip("tomllib")
    root = Path(__file__).resolve().parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text())
    setuptools = project["tool"]["setuptools"]
    assert "shambles.app.qt" in setuptools["packages"]
    declared = setuptools["package-data"]["shambles.app.qt"]
    assert "qml/*.qml" in declared and "fonts/*.ttf" in declared

    package = root / "shambles" / "app" / "qt"
    assert (package / "qml" / "Main.qml").is_file()
    assert len(list((package / "fonts").glob("*.ttf"))) == 3
    assert (package / "fonts" / "OFL.txt").is_file(), \
        "the typeface's licence must ship with it"
    assert "icons/*" in declared
    assert (package / "icons" / "shambles.png").is_file()
    assert (root / "packaging" / "shambles.ico").is_file()
