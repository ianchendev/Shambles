#!/usr/bin/env python3
"""Convenience launcher for running straight from a checkout.

Installed users get the ``shambles`` console script instead. The real
entrypoint is ``shambles/__main__.py``; this only exists so that
``python3 shambles.py`` keeps working in a clone.
"""

from shambles.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
