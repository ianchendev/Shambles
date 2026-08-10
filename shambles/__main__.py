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
shambles — switch between Claude and Codex accounts

  shambles                       open the window
  shambles list                  show every account and its state
  shambles list --json           emit the machine-readable contract
  shambles switch <provider> <account>
  shambles --version             print the version
  shambles --help                show this message

Profiles live in ~/.claude-profiles/. The active one is whichever
~/.claude currently points at.
"""

#: Subcommands answered on stdout instead of by opening a window.
#:
#: Not merely a convenience: a Windows tray app manages a different Claude Code
#: install from the one inside WSL, and only a CLI running inside WSL can reach
#: that one. The macOS menu bar app consumes `list --json` for the same reason.
COMMANDS = ("list", "switch")

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

    # Checked before Tkinter is imported so the CLI works on a headless box,
    # over SSH, and inside WSL. Scans every token rather than only the first:
    # global flags may precede the subcommand, as in
    # `shambles --home /tmp/x list --json`, and testing argv[0] alone sent that
    # to the window where it died on missing Tkinter.
    if any(token in COMMANDS for token in argv):
        from shambles.app.cli import main as cli_main
        return cli_main(argv)

    try:
        import tkinter  # noqa: F401
    except ModuleNotFoundError:
        sys.stderr.write(TK_MISSING)
        return 1

    from shambles.gui import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
