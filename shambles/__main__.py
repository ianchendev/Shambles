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
shambles — switch between Claude Code and Codex accounts

  shambles                     open the terminal interface, on a terminal
  shambles tui                 open the terminal interface explicitly
  shambles gui                 open the window instead
  shambles list                list every account and its state
  shambles list --json         the same thing, machine-readable
  shambles switch claude Work  switch without opening an interface
  shambles --no-motion         disable nonessential terminal motion
  shambles --version           print the version
  shambles --help              show this message

  shambles config get update.check         are update checks on?
  shambles config set update.check true    ask GitHub for the latest release
                                           tag, at most once a day (off by
                                           default; sends nothing about you)

Profiles live in ~/.shambles/<provider>/<Name>/, and the active one is named
in ~/.shambles/<provider>/active.
"""

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

TEXTUAL_MISSING = """\
Shambles needs Textual for the terminal interface, and it is not installed.

Running from a clone? Install the package, which brings Textual with it:

  python3 -m venv .venv
  .venv/bin/pip install -e .
  .venv/bin/shambles

Otherwise: pip install textual

The window does not need it — try `shambles gui` instead.
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


def write_stream(stream, text):
    """Write ``text`` to ``stream``, tolerating a stream that is not there.

    A PyInstaller ``--windowed`` build on Windows allocates no console, so
    Python sets ``sys.stdout`` and ``sys.stderr`` to ``None``. The ``print``
    builtin checks for that and returns without writing; ``stream.write``
    does not, and 2.1.0 turned ``shambles --version`` into a crash dialog on
    every Windows machine as a result.

    Nothing printed here is worth failing over. If there is nowhere to write,
    there is nobody reading, so a missing, closed or detached handle is
    swallowed rather than raised.

    No annotations and no modern syntax: this file has to stay parseable on
    the old interpreters :data:`MIN_PYTHON` describes.
    """
    if stream is None or not text:
        return
    try:
        stream.write(text)
    except (OSError, ValueError):
        pass


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


def _home(argv):
    """The value of ``--home``, if the line carries one, else None.

    :func:`_command` already steps over this option on its way to the
    subcommand, but ``--version`` answers before the CLI parser ever runs, so
    it has to read the value itself or report on the wrong home directory.
    Validation still belongs to the parser; a malformed ``--home`` here just
    names a directory with nothing in it, which reads as "no notice".
    """
    tokens = iter(argv)
    for token in tokens:
        if token == "--home":
            return next(tokens, None)
        if token.startswith("--home="):
            return token[len("--home="):]
    return None


def _update_notice(argv):
    """A line about a newer release, or "" -- read from the cache, never fetched.

    ``update_check.TIMEOUT_S`` bounds one socket operation rather than a whole
    lookup, so a fetch in front of ``--version`` could hold up an install
    check for as long as DNS, connect and read take to each give up in turn.
    This reads what some earlier run already wrote and stops there.

    The imports are inside the body for the reason :data:`MIN_PYTHON` gives:
    those modules annotate with ``str | None``, which the interpreters this
    file still has to run on cannot evaluate. By the time anything reaches
    here, :func:`version_error` has already turned those interpreters away.

    Catch-all, because ``--version`` is what people run when everything else
    is broken. Whatever is wrong with the home directory, the version prints.
    """
    try:
        from shambles.paths import Paths
        from shambles.update_check import notice_from_cache

        home = _home(argv)
        notice = notice_from_cache(
            Paths.for_home(home) if home else Paths.real(),
            current_version=__version__)
    except Exception:
        return ""
    return notice + "\n" if notice else ""


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
        write_stream(sys.stderr, outdated)
        return 1

    if "--version" in argv or "-V" in argv:
        print(f"shambles {__version__}")
        # The notice goes to stderr on purpose. Installers and shell scripts
        # read this command's stdout, often whole -- a second line there
        # would break every one of them, while a person at a terminal sees
        # both streams either way.
        write_stream(sys.stderr, _update_notice(argv))
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
