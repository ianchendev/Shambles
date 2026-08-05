import pytest

from shambles.paths import Paths


@pytest.fixture
def home(tmp_path):
    """A synthetic home directory. Never the real one."""
    return tmp_path


@pytest.fixture
def paths(home):
    return Paths.for_home(home)


@pytest.fixture
def make_app():
    """Build a ShamblesApp, skipping when there is no usable display.

    Creates exactly one Tk root. Probing with a separate throwaway root first
    is fragile on Windows, where a second root in the same process can fail to
    locate init.tcl. Also destroys whatever it made, so a failing assertion
    cannot leak a window into the next test.
    """
    created = []

    def _make(paths):
        tk = pytest.importorskip("tkinter")
        from shambles.gui import ShamblesApp
        try:
            app = ShamblesApp(paths)
        except tk.TclError as exc:
            pytest.skip(f"no usable display: {exc}")
        created.append(app)
        return app

    yield _make

    for app in created:
        try:
            app.destroy()
        except Exception:
            pass
