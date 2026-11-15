"""Can Qt open a window here? Asked of a child process, because Qt aborts.

A successful ``import PySide6`` proves only that the Python half is
installed. Whether Qt can reach a screen is settled later, when the first
``QGuiApplication`` loads a platform plugin, and when no plugin loads Qt
calls ``abort()``: no exception, nothing Python can catch, a core dump. With
PySide6 from pip on a bare Linux or WSL install that is the usual outcome,
because Qt's X11 plugin links against libraries only a desktop brings.

So on Linux the question goes first to a short-lived child process that
makes a ``QGuiApplication`` and exits. If the child dies, the window would
have died the same way, and ``shambles gui`` opens the classic window
instead and says why. The child costs about a tenth of a second.

Nothing here imports PySide6. This module runs exactly when PySide6 may be
broken, and also builds the advice for when it is not installed at all.
"""

import importlib.util
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

#: Every system library that Qt's X11 plugin and the Qt modules the window
#: loads link against directly, and the Debian/Ubuntu package that holds it.
#: Taken from the running window (``LD_DEBUG=files``) and ``readelf`` on each
#: Qt file it loaded, PySide6 6.9 (pyproject pins it below 6.10), on the
#: software and the OpenGL renderer. libc, libstdc++, libgcc, zlib and zstd
#: are left out: every Debian and Ubuntu system has them. The window
#: workflow installs exactly these in bare ubuntu:22.04 and ubuntu:24.04
#: containers, checks ``ldd`` finds everything, and opens the window.
LIBRARIES = {
    "libEGL.so.1": "libegl1",
    "libGL.so.1": "libgl1",
    "libfontconfig.so.1": "libfontconfig1",
    "libfreetype.so.6": "libfreetype6",
    "libglib-2.0.so.0": "libglib2.0-0",
    "libgthread-2.0.so.0": "libglib2.0-0",
    "libdbus-1.so.3": "libdbus-1-3",
    "libgssapi_krb5.so.2": "libgssapi-krb5-2",
    "libX11.so.6": "libx11-6",
    "libX11-xcb.so.1": "libx11-xcb1",
    "libxkbcommon.so.0": "libxkbcommon0",
    "libxkbcommon-x11.so.0": "libxkbcommon-x11-0",
    "libxcb.so.1": "libxcb1",
    "libxcb-cursor.so.0": "libxcb-cursor0",
    "libxcb-glx.so.0": "libxcb-glx0",
    "libxcb-icccm.so.4": "libxcb-icccm4",
    "libxcb-image.so.0": "libxcb-image0",
    "libxcb-keysyms.so.1": "libxcb-keysyms1",
    "libxcb-randr.so.0": "libxcb-randr0",
    "libxcb-render.so.0": "libxcb-render0",
    "libxcb-render-util.so.0": "libxcb-render-util0",
    "libxcb-shape.so.0": "libxcb-shape0",
    "libxcb-shm.so.0": "libxcb-shm0",
    "libxcb-sync.so.1": "libxcb-sync1",
    "libxcb-util.so.1": "libxcb-util1",
    "libxcb-xfixes.so.0": "libxcb-xfixes0",
    "libxcb-xkb.so.1": "libxcb-xkb1",
}

#: The packages to ``apt install``, each once, in the order printed.
APT_PACKAGES = tuple(dict.fromkeys(LIBRARIES.values()))

#: The ``[gui]`` extra in pyproject.toml, for installing Qt on its own.
PYSIDE_REQUIREMENT = "PySide6-Essentials>=6.8,<6.10"
SOURCE = "git+https://github.com/ianchendev/Shambles"

#: Long enough for a cold WSLg display to answer its first client.
PROBE_TIMEOUT_S = 30
LDD_TIMEOUT_S = 10

#: Run by the child. It gets the parent's ``sys.path`` so that it imports the
#: same PySide6, and runs isolated (``-I``) so nothing in the current
#: directory is imported in its place.
_PROBE = (
    "import sys\n"
    "sys.path[:] = {path!r}\n"
    "from PySide6.QtGui import QGuiApplication\n"
    "app = QGuiApplication(['shambles'])\n"
    "print(app.platformName())\n"
)

#: Lines Qt prints on the way to aborting that say nothing about why. The
#: xcb-cursor one appears whenever the X11 plugin fails to load, whatever
#: library is really missing, and "Reinstalling the application" does not
#: help either.
_UNHELPFUL = (
    re.compile(r"xcb-cursor0 or libxcb-cursor0 is needed"),
    re.compile(r"Could not load the Qt platform plugin"),
    re.compile(r"no Qt platform plugin could be initialized"),
    re.compile(r"^Available platform plugins are"),
)


class QtCannotStart(ImportError):
    """PySide6 imports, but Qt cannot open a window on this machine.

    An ImportError so that it takes the same road as PySide6 being absent:
    the window bundle if there is one, else the classic window. ``missing``
    holds the libraries ``ldd`` could not find, when that was the reason.
    """

    def __init__(self, reason, missing=()):
        super().__init__(reason)
        self.missing = list(missing)


def needs_probe(platform=None, frozen=None) -> bool:
    """Whether Qt's platform plugin can fail here for want of a library.

    Linux only: the Windows and macOS plugins ship inside the wheel and use
    only what the OS provides. Never in the window bundle, which carries
    its libraries and whose ``sys.executable`` is the bundle, not a Python
    that could run the probe.
    """
    platform = sys.platform if platform is None else platform
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    return platform.startswith("linux") and not frozen


def start_failure(*, env=None, run=subprocess.run,
                  timeout=PROBE_TIMEOUT_S):
    """A :class:`QtCannotStart` saying why Qt cannot open a window here, or
    None when it can.

    ``env`` is what the window itself will start with, so the child loads
    the plugin the window would.
    """
    if not sys.executable:
        return None
    command = [sys.executable, "-I", "-c",
               _PROBE.format(path=list(sys.path))]
    try:
        done = run(command, stdin=subprocess.DEVNULL, capture_output=True,
                   text=True, errors="replace", timeout=timeout, env=env)
    except subprocess.TimeoutExpired:
        return QtCannotStart(f"Qt did not start within {timeout} seconds.")
    except OSError:
        # No child, no answer. Opening the window is what happened before
        # this check existed, and is still the likeliest thing to work.
        return None
    if done.returncode == 0:
        return None
    missing = missing_libraries(env=env, run=run)
    return QtCannotStart(describe(done.stderr, done.returncode,
                                  missing=missing), missing)


def describe(stderr, returncode, *, missing=()) -> str:
    """One sentence on why the child could not start Qt."""
    if missing:
        verb = "is" if len(missing) == 1 else "are"
        return (f"Qt's X11 plugin needs {_and(missing)}, which {verb} "
                "not installed.")
    lines = [line.strip() for line in (stderr or "").splitlines()]
    lines = [line for line in lines if line]
    for line in lines:
        if line.startswith("qt.") and not _unhelpful(line):
            return "Qt could not open a window: " + _strip_category(line)
    useful = [line for line in lines if not _unhelpful(line)]
    if useful:
        return "Qt could not open a window: " + useful[-1][:300]
    return f"Qt could not open a window (it stopped with status {returncode})."


def missing_libraries(*, env=None, run=subprocess.run) -> list:
    """The libraries the X11 plugin needs and ``ldd`` cannot find.

    Qt itself does not name them, even when asked to explain its plugins
    it names only the first, so ``ldd`` is asked for the whole list. Empty
    when the window is not going to use the X11 plugin, or nothing is
    missing, or there is no ``ldd``.
    """
    chosen = (os.environ if env is None else env).get("QT_QPA_PLATFORM", "")
    if chosen and "xcb" not in chosen:
        return []
    plugin = xcb_plugin()
    if plugin is None:
        return []
    try:
        done = run(["ldd", str(plugin)], stdin=subprocess.DEVNULL,
                   capture_output=True, text=True, errors="replace",
                   timeout=LDD_TIMEOUT_S, env=env)
    except (OSError, subprocess.SubprocessError):
        return []
    missing = []
    for line in done.stdout.splitlines():
        name, arrow, where = line.strip().partition(" => ")
        if arrow and where.strip() == "not found" and name not in missing:
            missing.append(name)
    return missing


def xcb_plugin():
    """Path of PySide6's X11 platform plugin, or None."""
    try:
        spec = importlib.util.find_spec("PySide6")
    except (ImportError, ValueError):
        return None
    if spec is None or not spec.origin:
        return None
    plugin = (Path(spec.origin).parent / "Qt" / "plugins" / "platforms"
              / "libqxcb.so")
    return plugin if plugin.is_file() else None


def not_installed(exc) -> bool:
    """True when PySide6 is simply absent, not present and failing."""
    name = getattr(exc, "name", None) or ""
    return (isinstance(exc, ModuleNotFoundError)
            and name.split(".")[0] in ("PySide6", "shiboken6"))


def in_pipx(prefix=None) -> bool:
    """Whether this Python is a pipx-managed environment.

    pipx writes ``pipx_metadata.json`` at the root of every environment it
    makes, wherever ``PIPX_HOME`` puts them.
    """
    prefix = sys.prefix if prefix is None else prefix
    return (Path(prefix) / "pipx_metadata.json").is_file()


def install_command(*, prefix=None, executable=None, windows=None) -> str:
    """The command that adds Qt to the environment Shambles runs in.

    A pipx environment is reinstalled with the extra, the way the README
    installs it; pip run inside that environment would not survive pipx's
    next upgrade. Anything else gets PySide6 itself, installed by this
    interpreter's pip, so it lands next to Shambles however Shambles got
    there: from a clone, a git URL or a wheel. Shambles is not on PyPI,
    so ``pip install shambles[gui]`` would fetch somebody else's project or
    nothing.
    """
    if in_pipx(prefix):
        words = ["pipx", "install", "--force", f"shambles[gui] @ {SOURCE}"]
    else:
        words = [executable or sys.executable, "-m", "pip", "install",
                 PYSIDE_REQUIREMENT]
    windows = (os.name == "nt") if windows is None else windows
    return _windows_join(words) if windows else shlex.join(words)


def apt_command(indent="    ", width=72) -> str:
    """``sudo apt install`` and every package, wrapped for a terminal."""
    lines, line = [], "sudo apt install"
    for package in APT_PACKAGES:
        if len(line) + 1 + len(package) + 2 > width:
            lines.append(line + " \\")
            line = indent + package
        else:
            line += " " + package
    lines.append(line)
    return "\n".join(lines)


def _windows_join(words) -> str:
    """Quote for cmd.exe and PowerShell alike, where ``'`` does not quote."""
    plain = re.compile(r"^[\w\-.:\\/]+$")
    return " ".join(word if plain.match(word) else f'"{word}"'
                    for word in words)


def _unhelpful(line) -> bool:
    return any(pattern.search(line) for pattern in _UNHELPFUL)


def _strip_category(line) -> str:
    """``qt.qpa.xcb: could not connect`` -> ``could not connect``."""
    head, colon, rest = line.partition(": ")
    return rest if colon and " " not in head else line


def _and(names) -> str:
    names = list(names)
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]
