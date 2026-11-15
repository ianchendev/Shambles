"""Deciding whether the Qt window can open, without letting Qt abort us.

None of this needs Qt: the child process and ``ldd`` are replaced by
stand-ins. ``tests/qt/test_qt_start_probe.py`` runs the real child against
the real PySide6.
"""

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

from shambles.app import cli, window_check

REPO = Path(__file__).resolve().parents[1]

#: What Qt 6.9 printed on a WSL machine with every library but two, before it
#: aborted. The cursor hint is wrong: libxcb-cursor0 was installed.
IAN_STDERR = """\
qt.qpa.plugin: Could not load the Qt platform plugin "wayland" in "" even though it was found.
qt.qpa.plugin: From 6.5.0, xcb-cursor0 or libxcb-cursor0 is needed to load the Qt xcb platform plugin.
qt.qpa.plugin: Could not load the Qt platform plugin "xcb" in "" even though it was found.
This application failed to start because no Qt platform plugin could be initialized. Reinstalling the application may fix this problem.

Available platform plugins are: minimalegl, offscreen, eglfs, wayland, vnc, xcb, wayland-egl, linuxfb, vkkhrdisplay, minimal.
"""

LDD_TWO_MISSING = """\
\tlinux-vdso.so.1 (0x00007ffd)
\tlibQt6XcbQpa.so.6 => /venv/PySide6/Qt/lib/libQt6XcbQpa.so.6 (0x00007f)
\tlibxcb-icccm.so.4 => not found
\tlibxcb-keysyms.so.1 => not found
\tlibxcb-cursor.so.0 => /lib/x86_64-linux-gnu/libxcb-cursor.so.0 (0x00007f)
\tlibxcb-icccm.so.4 => not found
"""


class Runs:
    """Stands in for ``subprocess.run``: the probe child, then ``ldd``."""

    def __init__(self, probe, ldd=""):
        self.probe, self.ldd, self.calls = probe, ldd, []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[0] == "ldd":
            return subprocess.CompletedProcess(command, 0, self.ldd, "")
        if isinstance(self.probe, BaseException):
            raise self.probe
        returncode, stderr = self.probe
        return subprocess.CompletedProcess(command, returncode, "", stderr)


@pytest.fixture
def plugin(monkeypatch, tmp_path):
    path = tmp_path / "libqxcb.so"
    path.write_bytes(b"\x7fELF")
    monkeypatch.setattr(window_check, "xcb_plugin", lambda: path)
    return path


# -- the probe ---------------------------------------------------------------

def test_a_child_that_starts_qt_means_the_window_can_open(plugin):
    runs = Runs((0, ""))

    assert window_check.start_failure(env={}, run=runs) is None
    assert len(runs.calls) == 1, "ldd only runs once something has failed"


def test_the_child_imports_the_same_pyside_and_nothing_from_the_cwd(plugin):
    runs = Runs((0, ""))

    window_check.start_failure(env={"X": "1"}, run=runs)

    command, kwargs = runs.calls[0]
    assert command[:3] == [sys.executable, "-I", "-c"]
    assert repr(list(sys.path)) in command[3]
    assert "QGuiApplication(" in command[3]
    assert kwargs["env"] == {"X": "1"}
    assert kwargs["stdin"] is subprocess.DEVNULL
    assert kwargs["timeout"] == window_check.PROBE_TIMEOUT_S


def test_an_aborted_child_names_the_libraries_ldd_cannot_find(plugin):
    """The case from Ian's machine: Qt's own message blames the wrong one."""
    runs = Runs((-6, IAN_STDERR), ldd=LDD_TWO_MISSING)

    problem = window_check.start_failure(env={}, run=runs)

    assert isinstance(problem, window_check.QtCannotStart)
    assert isinstance(problem, ImportError), "takes the no-PySide6 road"
    assert problem.missing == ["libxcb-icccm.so.4", "libxcb-keysyms.so.1"]
    assert str(problem) == (
        "Qt's X11 plugin needs libxcb-icccm.so.4 and libxcb-keysyms.so.1, "
        "which are not installed.")
    assert "cursor" not in str(problem)
    assert runs.calls[1][0] == ["ldd", str(plugin)]


def test_without_a_missing_library_qts_own_reason_is_kept(plugin):
    stderr = ("qt.qpa.xcb: could not connect to display :7\n" + IAN_STDERR)

    problem = window_check.start_failure(env={}, run=Runs((-6, stderr)))

    assert str(problem) == "Qt could not open a window: could not connect " \
                           "to display :7"
    assert problem.missing == []


def test_an_unknown_platform_is_reported_as_qt_said_it(plugin):
    stderr = ('qt.qpa.plugin: Could not find the Qt platform plugin "bogus" '
              'in ""\n' + IAN_STDERR.split("\n", 3)[3])
    runs = Runs((-6, stderr), ldd=LDD_TWO_MISSING)

    problem = window_check.start_failure(env={"QT_QPA_PLATFORM": "bogus"},
                                         run=runs)

    assert str(problem) == ('Qt could not open a window: Could not find the '
                            'Qt platform plugin "bogus" in ""')
    assert len(runs.calls) == 1, "not the X11 plugin, so ldd is not asked"


def test_a_child_that_says_nothing_useful_still_gets_a_sentence(plugin):
    problem = window_check.start_failure(env={}, run=Runs((-6, IAN_STDERR)))
    assert str(problem) == "Qt could not open a window (it stopped with " \
                           "status -6)."


def test_a_python_error_in_the_child_is_quoted(plugin):
    stderr = ("Traceback (most recent call last):\n  File \"<string>\"\n"
              "ImportError: libGL.so.1: cannot open shared object file\n")
    problem = window_check.start_failure(env={}, run=Runs((1, stderr)))
    assert str(problem).endswith("ImportError: libGL.so.1: cannot open "
                                 "shared object file")


def test_a_child_that_hangs_is_given_up_on(plugin):
    runs = Runs(subprocess.TimeoutExpired("python", 30))
    problem = window_check.start_failure(env={}, run=runs)
    assert str(problem) == "Qt did not start within 30 seconds."


def test_no_child_at_all_lets_the_window_try_as_before(plugin):
    assert window_check.start_failure(env={},
                                      run=Runs(OSError("no fork"))) is None


@pytest.mark.parametrize("platform, frozen, expected", [
    ("linux", False, True),
    ("linux", True, False),     # the bundle carries its libraries
    ("win32", False, False),
    ("darwin", False, False),
])
def test_only_linux_outside_the_bundle_is_probed(platform, frozen, expected):
    assert window_check.needs_probe(platform, frozen) is expected


def test_ldd_without_the_plugin_or_without_ldd_finds_nothing(monkeypatch):
    monkeypatch.setattr(window_check, "xcb_plugin", lambda: None)
    assert window_check.missing_libraries(env={}) == []


def test_no_ldd_finds_nothing(plugin):
    def run(command, **_kw):
        raise FileNotFoundError(command[0])
    assert window_check.missing_libraries(env={}, run=run) == []


# -- the advice --------------------------------------------------------------

def test_a_pipx_install_is_told_to_reinstall_with_the_extra(tmp_path):
    (tmp_path / "pipx_metadata.json").write_text("{}")

    assert window_check.install_command(prefix=tmp_path, windows=False) == (
        "pipx install --force "
        "'shambles[gui] @ git+https://github.com/ianchendev/Shambles'")


def test_anything_else_installs_pyside_with_this_pythons_pip(tmp_path):
    """Shambles is not on PyPI: `pip install shambles[gui]` is a stranger's
    project, or nothing."""
    command = window_check.install_command(
        prefix=tmp_path, executable="/opt/py env/bin/python", windows=False)

    assert command == ("'/opt/py env/bin/python' -m pip install "
                       "'PySide6-Essentials>=6.8,<6.10'")


def test_windows_gets_quotes_cmd_understands(tmp_path):
    command = window_check.install_command(
        prefix=tmp_path, executable=r"C:\Py\python.exe", windows=True)

    assert command == (r'C:\Py\python.exe -m pip install '
                       r'"PySide6-Essentials>=6.8,<6.10"')


def test_only_a_missing_pyside_counts_as_not_installed():
    assert window_check.not_installed(ModuleNotFoundError(name="PySide6"))
    assert window_check.not_installed(
        ModuleNotFoundError(name="shiboken6.Shiboken"))
    assert not window_check.not_installed(ModuleNotFoundError(name="textual"))
    assert not window_check.not_installed(ImportError("libEGL.so.1: x"))
    assert not window_check.not_installed(
        window_check.QtCannotStart("no plugin"))


def test_the_apt_command_wraps_into_lines_a_shell_joins_back():
    command = window_check.apt_command()

    lines = command.splitlines()
    assert all(len(line) <= 72 for line in lines)
    assert all(line.endswith(" \\") for line in lines[:-1])
    joined = command.replace(" \\\n", " ").split()
    assert joined[:3] == ["sudo", "apt", "install"]
    assert tuple(joined[3:]) == window_check.APT_PACKAGES


# -- through `shambles gui` -------------------------------------------------

def cannot_start(monkeypatch, problem):
    def entry():
        raise problem
    monkeypatch.setattr(cli, "_window_entry", entry)


def test_gui_new_explains_a_missing_library_and_lists_every_package(
        monkeypatch, capsys, home):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    cannot_start(monkeypatch, window_check.QtCannotStart(
        "Qt's X11 plugin needs libxcb-icccm.so.4, which is not installed.",
        ["libxcb-icccm.so.4"]))

    assert cli.main(["gui", "--new", "--home", str(home)]) == cli.EXIT_FAILED

    err = capsys.readouterr().err
    assert "needs libxcb-icccm.so.4" in err
    assert window_check.apt_command() in err
    assert "pip install" not in err, "PySide6 is installed; that is not it"


def test_gui_new_does_not_offer_packages_for_a_missing_display(
        monkeypatch, capsys, home):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    cannot_start(monkeypatch, window_check.QtCannotStart(
        "Qt could not open a window: could not connect to display"))

    assert cli.main(["gui", "--new", "--home", str(home)]) == cli.EXIT_FAILED

    err = capsys.readouterr().err
    assert "could not connect to display" in err
    assert "apt install" not in err


def test_an_unimportable_pyside_on_linux_gets_the_package_list(
        monkeypatch, capsys, home):
    monkeypatch.setattr(cli.sys, "platform", "linux")
    cannot_start(monkeypatch, ImportError(
        "libEGL.so.1: cannot open shared object file: No such file"))

    cli.main(["gui", "--new", "--home", str(home)])

    err = capsys.readouterr().err
    assert "libEGL.so.1" in err and "libegl1" in err


def test_a_broken_pyside_elsewhere_is_told_to_reinstall(monkeypatch, capsys,
                                                         home):
    monkeypatch.setattr(cli.sys, "platform", "win32")
    cannot_start(monkeypatch, ImportError("DLL load failed while importing"))

    cli.main(["gui", "--new", "--home", str(home)])

    err = capsys.readouterr().err
    assert "DLL load failed" in err
    assert "Reinstalling PySide6" in err and "PySide6-Essentials" in err
    assert "apt install" not in err


def test_a_missing_pyside_in_pipx_is_given_the_pipx_command(
        monkeypatch, capsys, tmp_path, home):
    (tmp_path / "pipx_metadata.json").write_text("{}")
    monkeypatch.setattr(window_check.sys, "prefix", str(tmp_path))
    cannot_start(monkeypatch, ModuleNotFoundError(
        "No module named 'PySide6'", name="PySide6"))

    cli.main(["gui", "--new", "--home", str(home)])

    err = capsys.readouterr().err
    assert "not installed here" in err
    assert "pipx install --force" in err and "shambles[gui] @ git+" in err
    assert "pip install 'shambles[gui]'" not in err


def test_plain_gui_falls_back_and_says_why(monkeypatch, capsys, home):
    from shambles import gui

    opened = []
    monkeypatch.setattr(gui, "run",
                        lambda paths=None: opened.append(paths.home) or 0)
    cannot_start(monkeypatch, window_check.QtCannotStart(
        "Qt's X11 plugin needs libxcb-keysyms.so.1, which is not installed.",
        ["libxcb-keysyms.so.1"]))

    assert cli.main(["gui", "--home", str(home)]) == 0

    assert opened == [home]
    err = capsys.readouterr().err
    assert "could not start here" in err
    assert "libxcb-keysyms.so.1" in err
    assert "shambles gui --new" in err


def test_plain_gui_without_pyside_keeps_the_short_note(monkeypatch, capsys,
                                                        home):
    from shambles import gui

    monkeypatch.setattr(gui, "run", lambda paths=None: 0)
    cannot_start(monkeypatch, ModuleNotFoundError(
        "No module named 'PySide6'", name="PySide6"))

    cli.main(["gui", "--home", str(home)])

    assert "not installed here" in capsys.readouterr().err


# -- one list, everywhere it is written down ---------------------------------

def apt_lists(text):
    """Every `sudo apt install ...` in a text, as tuples of package names.

    Follows backslash continuations and Markdown line wrapping inside a
    backtick span, the two ways the list is split across lines.
    """
    found = []
    for match in re.finditer(r"sudo apt install((?:[ \t]*\\?\n?[ \t]*"
                             r"[a-z0-9][a-z0-9.+-]*)+)", text):
        words = match.group(1).replace("\\", " ").split()
        found.append(tuple(words))
    return found


@pytest.mark.parametrize("where", [
    "README.md",
    ".github/workflows/release.yml",
])
def test_every_written_down_list_is_the_full_one(where):
    qt = set(window_check.APT_PACKAGES)
    # Lists for anything else, `python3-tk` for the classic window, say.
    lists = [packages for packages
             in apt_lists((REPO / where).read_text(encoding="utf-8"))
             if qt & set(packages)]

    assert lists, f"{where} no longer says what to apt install"
    for packages in lists:
        assert packages == window_check.APT_PACKAGES, where


def test_the_message_carries_the_full_list():
    from shambles.__main__ import QT_FIX_LIBRARIES

    text = QT_FIX_LIBRARIES.format(apt=window_check.apt_command())
    assert apt_lists(text) == [window_check.APT_PACKAGES]


def test_nothing_still_tells_anyone_to_pip_install_shambles_by_name():
    """Not on PyPI: the name could be claimed by anyone."""
    for where in ("README.md", ".github/workflows/release.yml",
                  "shambles/__main__.py"):
        text = (REPO / where).read_text(encoding="utf-8")
        assert not re.search(r"pip install '?shambles\[gui\]'?(?!\s*@)(\s|$)",
                             text), where


def test_the_pyside_requirement_is_the_gui_extra():
    tomllib = pytest.importorskip("tomllib")
    project = tomllib.loads((REPO / "pyproject.toml").read_text())
    assert project["project"]["optional-dependencies"]["gui"] == [
        window_check.PYSIDE_REQUIREMENT]


def test_the_pipx_source_is_the_one_the_readme_installs_from():
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert f"pipx install 'shambles[gui] @ {window_check.SOURCE}'" in readme


def test_the_package_list_names_each_package_once():
    assert len(set(window_check.APT_PACKAGES)) == \
        len(window_check.APT_PACKAGES)
    assert all(re.fullmatch(r"[a-z0-9][a-z0-9.+-]+", package)
               for package in window_check.APT_PACKAGES)


@pytest.mark.skipif(not sys.platform.startswith("linux"),
                    reason="ldd and libqxcb.so are Linux things")
def test_this_machines_x11_plugin_needs_nothing_outside_the_list():
    """Where PySide6 is installed, everything its X11 plugin links against
    and the system lacks must be a library the list covers."""
    plugin = window_check.xcb_plugin()
    if plugin is None:
        pytest.skip("PySide6 is not installed here")
    # The Qt tests set QT_QPA_PLATFORM=offscreen for the whole run, which
    # would make this ask nothing.
    env = {k: v for k, v in os.environ.items() if k != "QT_QPA_PLATFORM"}
    missing = window_check.missing_libraries(env=env)
    assert set(missing) <= set(window_check.LIBRARIES), missing
