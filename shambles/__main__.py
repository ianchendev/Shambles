"""Entrypoint for both ``python -m shambles`` and the ``shambles`` script.

The only place that resolves the real home directory -- everything below takes
an injected :class:`~shambles.paths.Paths`, which is what lets the whole test
suite run against a temporary directory.
"""

import sys

# Absolute, not relative. PyInstaller runs this file as a top-level script
# rather than as a module inside its package, so `from . import ...` raises
# "attempted relative import with no known parent package" and the bundled
# binary dies on startup. Absolute imports work in both contexts.
from shambles import __version__

USAGE = """\
shambles — switch between Claude Code accounts

  shambles              open the terminal interface on an interactive terminal
  shambles tui          explicitly open the terminal interface
  shambles gui          open the window instead
  shambles list         list accounts
  shambles switch ...   switch accounts without opening an interface
  shambles --no-motion  disable nonessential terminal motion
  shambles --version    print the version
  shambles --help       show this message

Profiles live in ~/.claude-profiles/. The active one is whichever
~/.claude currently points at.
"""

#: Every subcommand `shambles.app.cli` knows how to dispatch. `list` and
#: `switch` are answered on stdout rather than by opening anything -- a
#: Windows tray app manages a different Claude Code install from the one
#: inside WSL, and only a CLI running inside WSL can reach that one, and the
#: macOS menu bar app consumes `list --json` for the same reason. `tui` and
#: `gui` open a frontend instead, chosen by :func:`selected_frontend` below.
COMMANDS = ("list", "switch", "tui", "gui")

#: Flags that do not, by themselves, stop a bare invocation from being
#: "bare". Present or not, `shambles --no-motion` on an interactive terminal
#: still opens the TUI -- just with less motion -- rather than falling
#: through to a usage message the way an unrecognized subcommand would.
_TUI_FLAGS = ("--no-motion",)

TK_MISSING = """\
Shambles needs Tkinter, which is not installed.

  Debian/Ubuntu   sudo apt install python3-tk
  Fedora          sudo dnf install python3-tkinter
  Arch            sudo pacman -S tk

On Windows and macOS, Tkinter ships with Python — if you see this there,
reinstall Python from python.org rather than using the Store build.
"""


#: The syntax this package is written in. Everything below __main__ uses PEP
#: 604 unions (``str | None``) in dataclass fields and signatures, which are
#: evaluated at import time -- so an older interpreter does not fail when it
#: reaches an unsupported feature, it fails while importing, several modules
#: deep, with "unsupported operand type(s) for |: 'type' and 'NoneType'".
#:
#: pyproject's requires-python covers pip and pipx. It does nothing for
#: `python3 shambles.py`, which is how the README says to run from a clone,
#: and on plenty of boxes `python3` is still the distro's 3.8.
#:
#: This file therefore has to stay parseable and runnable on those versions:
#: no unions in its own annotations, nothing newer than 3.8 syntax.
MIN_PYTHON = (3, 10)

TOO_OLD = """\
Shambles needs Python {need} or newer -- this is {have}.

Nothing is wrong with your checkout. The modules are written with syntax
{have} cannot parse, so it fails on import rather than at runtime.

Point a newer interpreter at it directly:
    python3.12 shambles.py

or install it, which picks a supported interpreter for you:
    pipx install git+https://github.com/ianchendev/Shambles
"""


def version_error(version_info=None):
    """The message to print when this interpreter is too old, else None.

    Takes the version tuple as an argument so the decision is testable on a
    supported interpreter -- there is otherwise no way to check it without an
    old Python to hand.
    """
    info = tuple((sys.version_info if version_info is None else version_info)[:2])
    if info >= MIN_PYTHON:
        return None
    return TOO_OLD.format(need=".".join(str(part) for part in MIN_PYTHON),
                          have=".".join(str(part) for part in info))


def _command(argv):
    """Find the subcommand without mistaking an option value for one.

    Argument validation belongs to the CLI parser. This only identifies an
    implicit TUI invocation before either frontend is imported.
    """
    tokens = iter(argv)
    for token in tokens:
        if token == "--home":
            next(tokens, None)
        elif token in _TUI_FLAGS or token.startswith("--home="):
            continue
        else:
            return token
    return None


def selected_frontend(argv):
    command = _command(argv)
    if command in ("gui", "tui"):
        return command
    if command is None and all(
        stream is not None and stream.isatty()
        for stream in (sys.stdin, sys.stdout)
    ):
        return "tui"
    return "cli"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)

    # First, before --version and before any import of the package
    # proper. --version used to print a number and exit 0 here on an
    # interpreter that could not import a single module, which is the
    # worst possible answer to "is this installed?".
    outdated = version_error()
    if outdated:
        sys.stderr.write(outdated)
        return 1

    if "--version" in argv or "-V" in argv:
        print(f"shambles {__version__}")
        return 0
    if "--help" in argv or "-h" in argv:
        print(USAGE, end="")
        return 0

    if selected_frontend(argv) == "tui" and _command(argv) is None:
        argv.append("tui")

    # Frontend imports happen only in their CLI handlers, after validation.
    # With no subcommand the parser prints help and returns EXIT_USAGE.
    from shambles.app.cli import main as cli_main
    return cli_main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
