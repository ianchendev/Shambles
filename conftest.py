import os
import threading
import time

import pytest

from shambles.paths import Paths

#: POSIX mode assertions. Windows has no chmod that can express 0700/0600 --
#: CPython maps os.chmod to the read-only attribute alone, so a directory
#: reports 0o777 and a file 0o666 no matter what was requested. Shambles skips
#: the chmod there by design (see TECH_SPEC 3.3); the files rely on the user
#: profile's ACLs, the same protection Claude Code's own credentials get.
posix_modes_only = pytest.mark.skipif(
    os.name == "nt",
    reason="Windows cannot express POSIX modes; credentials rely on ACLs there",
)


@pytest.fixture(autouse=True)
def predictable_motion(monkeypatch):
    """Pin animation on, whatever the developer's shell says.

    Same reasoning as ``fake_vendor`` pinning PATH: a rendering test must not
    change its answer because SHAMBLES_MOTION happened to be exported. Tests
    that want the reduced-motion path set it themselves.
    """
    monkeypatch.delenv("SHAMBLES_MOTION", raising=False)


@pytest.fixture(autouse=True)
def no_thread_outlives_its_test():
    """Let a test's background threads finish before the next test starts.

    ``shambles.login.LoginProcess`` pumps vendor output on a daemon thread,
    and ``fake_vendor`` can hand it a script that sleeps. A test that does not
    wait leaves that thread running, still calling back into the service, long
    after its own assertions have passed.

    The next test then drives Tk on the main thread. When the stray thread
    garbage-collects a Tk object, Tcl is entered from the wrong thread and
    aborts the interpreter outright:

        Fatal Python error: Aborted

    That kills the whole run rather than failing one test, so no retry can
    recover it. It is timing-dependent, which is why it showed up on one
    runner and not another.

    Joining is capped: a thread that will not end is left alone rather than
    hanging the suite, because a slow test is a better failure than a stuck
    one.
    """
    before = set(threading.enumerate())
    yield
    deadline = time.monotonic() + 5.0
    current = threading.current_thread()
    for thread in set(threading.enumerate()) - before:
        if thread is current or not thread.is_alive():
            continue
        thread.join(timeout=max(0.0, deadline - time.monotonic()))


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

    def _make(paths, *, platform="linux"):
        """Build the window against a synthetic home.

        The platform is pinned rather than inherited. These tests exercise
        rendering, and the fake home holds file-backed credentials -- but on
        Windows the provider spec resolves to the credential manager, so the
        window would look past the fixture at the real machine and report the
        user as signed out. Which store a platform picks is covered by the
        store and provider contract suites; it is not what a rendering test
        should be re-deciding.
        """
        tk = pytest.importorskip("tkinter")
        from shambles.gui import ShamblesApp
        try:
            app = ShamblesApp(paths, platform=platform)
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


posix_only = pytest.mark.skipif(
    os.name == "nt",
    reason="fake vendor binaries are /bin/sh scripts; the real flow is "
           "Linux/WSL-scoped anyway",
)


@pytest.fixture
def fake_vendor(tmp_path, monkeypatch):
    """Put a stand-in vendor binary on PATH.

    Never the real `claude` or `codex`: those would open a browser and try to
    authenticate. This prints what the real ones print when they cannot open a
    browser -- a URL to visit -- and exits with whatever code the test wants.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(bindir))

    def _make(name, *, exit_code=0, lines=("Visit https://example.test/auth",),
              linger=0):
        script = bindir / name
        body = "\n".join(f"echo {line!r}" for line in lines)
        script.write_text(
            f"#!/bin/sh\n{body}\nsleep {linger}\nexit {exit_code}\n",
            encoding="utf-8")
        script.chmod(0o755)
        return script

    return _make
