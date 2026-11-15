"""The start-up probe against the real PySide6: Qt aborts, Shambles does not.

`shambles gui` on a Linux box where PySide6 imported but no platform plugin
loaded used to die with "Aborted (core dumped)". An unknown platform name is
the portable way to make Qt abort exactly as it does there.
"""

import os
import sys

import pytest

pytest.importorskip("PySide6.QtQuick", exc_type=ImportError,
                    reason="PySide6 is not installed or cannot load")

import qt_support  # noqa: E402,F401  (offscreen platform, test paths)
from shambles.app import cli, window_check  # noqa: E402

# Taken before the root conftest's autouse fixture swaps it for a stand-in.
REAL_ENTRY = cli._window_entry

pytestmark = pytest.mark.skipif(
    not sys.platform.startswith("linux"),
    reason="the probe only runs on Linux; elsewhere Qt's plugins ship in "
           "the wheel")


def environment(platform):
    return {**os.environ, "QT_QPA_PLATFORM": platform}


def test_the_probe_passes_where_qt_can_start():
    assert window_check.start_failure(env=environment("offscreen")) is None


def test_the_probe_survives_qt_aborting_and_says_why():
    problem = window_check.start_failure(env=environment("bogus"))

    assert isinstance(problem, window_check.QtCannotStart)
    assert '"bogus"' in str(problem)


def test_the_window_entry_refuses_when_qt_would_abort(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "bogus")

    with pytest.raises(window_check.QtCannotStart, match="bogus"):
        REAL_ENTRY()


def test_the_window_entry_hands_back_the_window_when_qt_can_start(
        monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    run_window = REAL_ENTRY()

    from shambles.app.qt.application import run_window as real
    assert run_window is real


def test_gui_new_explains_instead_of_dumping_core(monkeypatch, capsys, home):
    """End to end through the CLI, with the real probe and real PySide6."""
    monkeypatch.setattr(cli, "_window_entry", REAL_ENTRY)
    monkeypatch.setenv("QT_QPA_PLATFORM", "bogus")

    assert cli.main(["gui", "--new", "--home", str(home)]) == cli.EXIT_FAILED

    err = capsys.readouterr().err
    assert "could not start" in err and '"bogus"' in err


def test_plain_gui_opens_the_classic_window_instead(monkeypatch, capsys,
                                                     home):
    from shambles import gui

    opened = []
    monkeypatch.setattr(cli, "_window_entry", REAL_ENTRY)
    monkeypatch.setattr(gui, "run",
                        lambda paths=None: opened.append(paths.home) or 0)
    monkeypatch.setenv("QT_QPA_PLATFORM", "bogus")

    assert cli.main(["gui", "--home", str(home)]) == 0

    assert opened == [home]
    assert "could not start here" in capsys.readouterr().err
