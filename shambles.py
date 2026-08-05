#!/usr/bin/env python3
"""Entrypoint. The one place that resolves the real home directory."""

import sys


def main() -> int:
    try:
        import tkinter  # noqa: F401
    except ModuleNotFoundError:
        sys.stderr.write(
            "Shambles needs Tkinter, which is not installed.\n\n"
            "    sudo apt install python3-tk\n\n"
        )
        return 1

    from shambles.gui import run
    return run()


if __name__ == "__main__":
    raise SystemExit(main())
