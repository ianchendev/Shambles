"""Entrypoint for both ``python -m shambles`` and the ``shambles`` script.

The only place that resolves the real home directory -- everything below takes
an injected :class:`~shambles.paths.Paths`, which is what lets the whole test
suite run against a temporary directory.
"""

import sys

from . import __version__

USAGE = """\
shambles — switch between Claude Code accounts

  shambles              open the window
  shambles --version    print the version
  shambles --help       show this message

Profiles live in ~/.claude-profiles/. The active one is whichever
~/.claude currently points at.
"""

TK_MISSING = """\
Shambles needs Tkinter, which is not installed.

  Debian/Ubuntu   sudo apt install python3-tk
  Fedora          sudo dnf install python3-tkinter
  Arch            sudo pacman -S tk

On Windows and macOS, Tkinter ships with Python — if you see this there,
reinstall Python from python.org rather than using the Store build.
"""


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)

    if "--version" in argv or "-V" in argv:
        print(f"shambles {__version__}")
        return 0
    if "--help" in argv or "-h" in argv:
        print(USAGE, end="")
        return 0

    try:
        import tkinter  # noqa: F401
    except ModuleNotFoundError:
        sys.stderr.write(TK_MISSING)
        return 1

    from .gui import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
