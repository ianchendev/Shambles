"""Fixtures for the Qt window's tests, imported by the modules that use them.

Not a ``conftest.py``: the suite imports helpers from the root ``conftest``
by name, and a second module called ``conftest`` shadows it.

Everything here skips cleanly when PySide6 is not installed, or is installed
but cannot load (a Linux box with no libEGL, say): the window is an optional
extra, and the rest of the suite must not depend on it.
"""

import os
import sys
from pathlib import Path

import pytest

# tests/helpers.py, which builds synthetic homes. On sys.path already when
# the whole suite runs; not when this directory runs on its own.
_TESTS = str(Path(__file__).resolve().parents[1])
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")

# The offscreen platform has no system font database of its own. On Windows
# it looks in PySide6's lib/fonts, which Qt no longer ships, and says so once
# per process -- into whichever test first draws text, which then fails on
# the message (the window test did, on every Windows run, and only CI's
# retries, in a process that had already said it, let it pass). A real
# window uses the Windows font database, so give offscreen the same fonts.
if sys.platform == "win32" and os.environ.get("WINDIR"):
    os.environ.setdefault("QT_QPA_FONTDIR",
                          str(Path(os.environ["WINDIR"]) / "Fonts"))


@pytest.fixture(scope="session")
def qt_app():
    """One QGuiApplication for the whole run; Qt allows only one."""
    gui = pytest.importorskip(
        "PySide6.QtGui", reason="PySide6 is not installed or cannot load",
        exc_type=ImportError)
    return gui.QGuiApplication.instance() or gui.QGuiApplication([])


@pytest.fixture
def pump(qt_app):
    """Run the event loop until ``done()`` is true, or fail after a second."""
    import time

    def _pump(done=lambda: False, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            qt_app.processEvents()
            if done():
                return True
            time.sleep(0.005)
        return done()

    return _pump
