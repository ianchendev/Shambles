"""`shambles gui`: reaching the Qt window, and failing politely."""

import pytest

from shambles.app import cli


def test_gui_opens_the_window_on_the_requested_home(monkeypatch, home):
    seen = {}

    def run_window(service, *, motion=True):
        seen.update(home=service.paths.home, motion=motion)
        return 0

    monkeypatch.setattr(cli, "_window_entry", lambda: run_window)

    assert cli.main(["gui", "--home", str(home)]) == 0
    assert seen == {"home": home, "motion": True}


def test_gui_passes_no_motion_through(monkeypatch, home):
    seen = {}
    monkeypatch.setattr(cli, "_window_entry", lambda: (
        lambda service, *, motion=True: seen.update(motion=motion) or 0))

    cli.main(["--no-motion", "gui", "--home", str(home)])

    assert seen == {"motion": False}


@pytest.mark.parametrize("problem, advice", [
    (ModuleNotFoundError("No module named 'PySide6'", name="PySide6"),
     "PySide6-Essentials"),
    (ImportError("libEGL.so.1: cannot open shared object file: No such file "
                 "or directory"), "libegl1"),
])
def test_a_window_that_cannot_load_says_why_and_what_to_do(
        monkeypatch, capsys, home, problem, advice):
    """Not installed and installed-but-unloadable both arrive as ImportError,
    and each gets its own advice."""
    def missing():
        raise problem

    monkeypatch.setattr(cli, "_window_entry", missing)
    monkeypatch.setattr(cli.sys, "platform", "linux")

    assert cli.main(["gui", "--home", str(home)]) == cli.EXIT_FAILED
    err = capsys.readouterr().err
    assert advice in err
    if advice == "libegl1":
        assert str(problem) in err


@pytest.mark.parametrize("flag", [[], ["--new"]])
def test_gui_opens_the_window_and_new_is_the_same_thing(monkeypatch, home,
                                                        flag):
    seen = {}
    monkeypatch.setattr(cli, "_window_entry", lambda: (
        lambda service, *, motion=True: seen.update(home=service.paths.home)
        or 0))

    assert cli.main(["gui", *flag, "--home", str(home)]) == 0
    assert seen == {"home": home}


def test_gui_without_qt_explains_instead_of_opening_anything(monkeypatch,
                                                             capsys, home):
    """A bare pip install has no Qt and no bundle. There is no other window
    to open, so it says what to install and fails where a script can see."""
    assert cli.main(["gui", "--home", str(home)]) == cli.EXIT_FAILED

    err = capsys.readouterr().err
    # The root conftest's stand-in, quoted as the reason.
    assert "switched off under test" in err
    assert err.endswith("Run shambles for the terminal UI.\n")


def test_classic_says_it_was_retired_and_opens_nothing(monkeypatch, capsys,
                                                       home):
    """Kept for 2.3.0 so a script or shortcut naming it fails with a reason,
    not an unknown option, and not silently."""
    monkeypatch.setattr(cli, "_window_entry",
                        lambda: pytest.fail("opened the window"))

    assert cli.main(["gui", "--classic", "--home", str(home)]) == \
        cli.EXIT_USAGE

    out, err = capsys.readouterr()
    assert out == ""
    assert "retired in 2.3.0" in err
    assert "shambles gui" in err and "terminal UI" in err


def test_neither_retired_option_is_offered_in_help(capsys):
    with pytest.raises(SystemExit):
        cli.main(["gui", "--help"])

    out = capsys.readouterr().out
    assert "--classic" not in out and "--new" not in out
