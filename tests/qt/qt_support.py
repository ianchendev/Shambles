"""Fixtures for the Qt window's tests, imported by the modules that use them.

Not a ``conftest.py``: the suite imports helpers from the root ``conftest``
by name, and a second module called ``conftest`` shadows it.

Everything here skips cleanly when PySide6 is not installed, or is installed
but cannot load (a Linux box with no libEGL, say): the window is an optional
extra, and the rest of the suite must not depend on it.
"""

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")
os.environ.setdefault("QT_QUICK_CONTROLS_STYLE", "Basic")


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
