"""The window must be closable by every ordinary means.

Tk's mainloop blocks inside C waiting on X events, and Python only dispatches
signal handlers between bytecode instructions. Left alone, Ctrl+C is recorded
and never delivered: the app appears frozen, the user reaches for Ctrl+Z, and
a SIGSTOPped process cannot answer the window manager's close request. The
result is a window that nothing on the desktop can shut.
"""

import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

tk = pytest.importorskip("tkinter")

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
READY = "SHAMBLES-READY"

RUNNER = textwrap.dedent("""
    import sys
    sys.path.insert(0, {repo!r})
    from shambles.gui import ShamblesApp
    from shambles.paths import Paths

    app = ShamblesApp(Paths.for_home({home!r}))
    # Printed from inside the loop, so the parent knows the app is really
    # running rather than sleeping an arbitrary amount and hoping.
    app.after(0, lambda: (print({ready!r}, flush=True)))
    app.mainloop()
    try:
        app.destroy()
    except Exception:
        pass
    print("EXITED", flush=True)
""")


def _display_or_skip():
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.destroy()


def _launch(home):
    code = RUNNER.format(repo=REPO, home=str(home), ready=READY)
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        line = proc.stdout.readline()
        if READY in line:
            return proc
        if proc.poll() is not None:
            pytest.fail(f"app died before ready: {proc.stderr.read()}")
    proc.kill()
    pytest.fail("app never signalled ready")


def _expect_exit(proc, sig, timeout=15):
    proc.send_signal(sig)
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        pytest.fail(f"{sig.name} did not stop the mainloop — the window would "
                    f"be unclosable, forcing the user to SIGSTOP it")
    return proc.returncode


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "Windows has no kill(pid, SIGINT): Ctrl+C there is a console "
        "CTRL_C_EVENT that cannot be sent to an unrelated process, and "
        "SIGTERM maps to TerminateProcess, which kills outright rather than "
        "unwinding. Windows users close the window with the X button, which "
        "test_wm_delete_window_is_handled covers on every platform."
    ),
)
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_signal_closes_the_window(tmp_path, sig):
    """Ctrl+C must work. Without it users reach for Ctrl+Z and strand the
    window in a state no window manager can close."""
    _display_or_skip()
    proc = _launch(tmp_path)
    assert _expect_exit(proc, sig) == 0


def test_wm_delete_window_is_handled(tmp_path, make_app):
    """The title-bar X routes through our own close path, so tooltips are
    torn down rather than orphaned."""
    from shambles.paths import Paths

    app = make_app(Paths.for_home(tmp_path))
    app.update()
    assert app.protocol("WM_DELETE_WINDOW"), "no close handler registered"
    app.on_close()


def test_tooltip_dies_with_its_widget(tmp_path, make_app):
    """A tooltip is an override-redirect Toplevel: the window manager draws no
    frame and cannot close it. If its owner is destroyed while it is visible --
    which refresh() does on every switch -- it would be orphaned on screen
    forever."""
    from shambles import gui
    from shambles.paths import Paths

    app = make_app(Paths.for_home(tmp_path))
    holder = tk.Frame(app)
    holder.pack()
    label = tk.Label(holder, text="hover me")
    label.pack()
    tip = gui.Tooltip(label, "some help")
    app.update()

    tip._show()
    app.update()
    assert tip.tip is not None and tip.tip.winfo_exists()

    holder.destroy()          # exactly what refresh() does to every row
    app.update()
    assert tip.tip is None, "tooltip outlived the widget it belonged to"



def test_close_tears_down_every_open_tooltip(tmp_path, make_app):
    from shambles import gui
    from shambles.paths import Paths

    app = make_app(Paths.for_home(tmp_path))
    label = tk.Label(app, text="x")
    label.pack()
    tip = gui.Tooltip(label, "help")
    app.update()
    tip._show()
    app.update()

    app.on_close()
    assert tip.tip is None, "close left a frameless tooltip on screen"
