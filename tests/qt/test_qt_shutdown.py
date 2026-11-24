"""Ctrl+C and SIGTERM close the window.

Qt's event loop blocks in C++, and Python only runs signal handlers between
bytecodes. Without the timer ``run_window`` starts to hand control back, a
Ctrl+C is recorded and never delivered: the window looks frozen, the user
reaches for Ctrl+Z, and a stopped process cannot answer the window manager's
close request. Carried over from the classic Tk window's tests, where the
same trap was first found.

The window runs in a child process, offscreen, on a synthetic home.
"""

import os
import signal
import subprocess
import sys
import textwrap
import time

import pytest

pytest.importorskip("PySide6.QtQuick", exc_type=ImportError,
                    reason="PySide6 is not installed or cannot load")

import qt_support  # noqa: E402,F401  (offscreen platform, test paths)

REPO = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))
READY = "SHAMBLES-READY"

RUNNER = textwrap.dedent("""
    import sys
    sys.path.insert(0, {repo!r})
    from PySide6.QtCore import QTimer
    from shambles import providers
    from shambles.app.qt import application
    from shambles.app.service import ShamblesService
    from shambles.paths import Paths

    built = application.build

    def build(*args, **kwargs):
        made = built(*args, **kwargs)
        # Printed from inside the loop, so the parent knows the window is
        # really running rather than sleeping an arbitrary amount and hoping.
        QTimer.singleShot(0, lambda: print({ready!r}, flush=True))
        return made

    application.build = build
    service = ShamblesService(paths=Paths.for_home({home!r}),
                              providers=providers.all_providers(env={{}}),
                              platform=sys.platform)
    status = application.run_window(service, argv=["shambles"])
    print("EXITED", status, flush=True)
    raise SystemExit(status)
""")


def _launch(home):
    code = RUNNER.format(repo=REPO, home=str(home), ready=READY)
    # Never the real home, even for whatever Qt itself might write there.
    env = {**os.environ, "HOME": str(home), "QT_QPA_PLATFORM": "offscreen",
           "SHAMBLES_SCALE": "1"}
    proc = subprocess.Popen(
        [sys.executable, "-c", code], env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        line = proc.stdout.readline()
        if READY in line:
            return proc
        if proc.poll() is not None:
            pytest.fail(f"the window died before it was ready: "
                        f"{proc.stderr.read()}")
    proc.kill()
    pytest.fail("the window never said it was ready")


@pytest.mark.skipif(
    os.name == "nt",
    reason=(
        "Windows has no kill(pid, SIGINT): Ctrl+C there is a console "
        "CTRL_C_EVENT that cannot be sent to an unrelated process, and "
        "SIGTERM maps to TerminateProcess, which kills outright rather than "
        "unwinding. Windows users close the window with its own button."
    ),
)
@pytest.mark.parametrize("sig", [signal.SIGINT, signal.SIGTERM])
def test_a_signal_closes_the_window(tmp_path, sig):
    proc = _launch(tmp_path)
    proc.send_signal(sig)
    try:
        out, err = proc.communicate(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        pytest.fail(f"{sig.name} did not stop the event loop: the window "
                    f"would be unclosable, forcing the user to SIGSTOP it")

    assert proc.returncode == 0, err
    assert "EXITED 0" in out
