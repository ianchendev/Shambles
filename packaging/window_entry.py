"""Entry point of the window bundle built by ``packaging/window.spec``.

The bundle is the whole of Shambles plus Qt, started with the window as its
default instead of the terminal dashboard. Anything on the command line is
passed through, so ``shambles-window --home /tmp/scratch`` works the way
``shambles gui --new --home /tmp/scratch`` does, and ``--version`` and
``--help`` still answer.

Absolute imports only: PyInstaller runs this file as a top-level script.
"""

import sys

from shambles.__main__ import main

PASS_THROUGH = ("--version", "-V", "--help", "-h")


def arguments(argv):
    if any(flag in argv for flag in PASS_THROUGH):
        return list(argv)
    return ["gui", "--new", *argv]


if __name__ == "__main__":
    raise SystemExit(main(arguments(sys.argv[1:])))
