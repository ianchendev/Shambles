import gc
import os
import sys
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


#: Environment variables that move a vendor's live login. Exported in the
#: shell that runs the suite, they would point any provider built from the
#: process environment at that person's real credential.
VENDOR_LOCATIONS = ("CLAUDE_CONFIG_DIR", "CLAUDE_SECURESTORAGE_CONFIG_DIR",
                    "CODEX_HOME")


@pytest.fixture(autouse=True)
def no_real_vendor_location(monkeypatch):
    """Never let a developer's vendor locations reach a test.

    Tests that want one set it themselves, on the provider's own ``env``.
    """
    for name in VENDOR_LOCATIONS:
        monkeypatch.delenv(name, raising=False)


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
    # The other half of the same crash. A Tk object left in a reference
    # cycle by an earlier test is freed whenever the collector next runs,
    # and the collector runs on whichever thread happens to allocate. If
    # that is a login worker, Tcl is entered from the wrong thread exactly
    # as above. Collecting here, on the main thread, before this test starts
    # any thread of its own, leaves nothing of Tk's for a worker to free.
    # Only once Tk has been loaded: before that there is nothing to guard.
    if "tkinter" in sys.modules:
        gc.collect()
    yield
    deadline = time.monotonic() + 5.0
    current = threading.current_thread()
    for thread in set(threading.enumerate()) - before:
        if thread is current or not thread.is_alive():
            continue
        thread.join(timeout=max(0.0, deadline - time.monotonic()))


@pytest.fixture(autouse=True)
def no_real_window(monkeypatch):
    """`shambles gui` must never open the real Qt window from a test.

    The Qt window is the default wherever Qt is installed, which includes
    CI. A test that reaches ``cli.main(["gui"])`` would otherwise start a
    real event loop and hang the run. Tests about the Qt window replace
    these two again with stand-ins of their own.
    """
    from shambles.app import cli, launch

    def unavailable():
        raise ImportError("the Qt window is switched off under test")

    monkeypatch.setattr(cli, "_window_entry", unavailable)
    monkeypatch.setattr(launch, "window_bundle", lambda **_kw: None)


#: Every native Tk dialog, and the answer that changes nothing: No, Cancel,
#: nothing typed. "ok" is what a message box returns once dismissed.
SAFE_ANSWERS = {
    "tkinter.messagebox": {
        "showinfo": "ok", "showwarning": "ok", "showerror": "ok",
        "askquestion": "no", "askokcancel": False, "askyesno": False,
        "askyesnocancel": None, "askretrycancel": False,
    },
    "tkinter.simpledialog": {
        "askstring": None, "askinteger": None, "askfloat": None,
    },
}


class RealDialogs:
    """The native dialogs a test opened without standing in for them."""

    def __init__(self):
        self.opened = []

    def verdict(self):
        if self.opened:
            pytest.fail(
                "a native dialog would have opened and waited for a person; "
                "stand in for it, as the tests that expect one do:\n"
                + "\n".join(f"  {kind}({title!r}, {text!r})"
                            for kind, title, text in self.opened),
                pytrace=False)


@pytest.fixture(autouse=True)
def no_real_dialogs(monkeypatch):
    """No test ever waits on a native dialog.

    They are modal, and on a CI runner nobody answers one: three Windows jobs
    sat in ``tests/test_gui_import.py`` until the six-hour job limit killed
    them, and the one ``faulthandler_timeout`` caught was parked in
    ``messagebox.askyesno`` behind a remove button no test had pressed. A
    retry cannot rescue a hang.

    So every dialog answers the safe way at once, and the test that opened
    one fails, naming it. Raising instead would not do: Tk prints an error
    from a callback and carries on, and the test would pass. Tests that
    expect a dialog patch it themselves, on top of this.
    """
    seen = RealDialogs()
    if "tkinter" not in sys.modules:
        try:
            import tkinter  # noqa: F401
        except ImportError:
            yield seen
            return
    import importlib

    def stand_in(kind, answer):
        def ask(title=None, message=None, *_args, **_kwargs):
            seen.opened.append((kind, title, message))
            return answer
        return ask

    for module_name, answers in SAFE_ANSWERS.items():
        module = importlib.import_module(module_name)
        for kind, answer in answers.items():
            monkeypatch.setattr(module, kind, stand_in(kind, answer))
    yield seen
    seen.verdict()


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
        if sys.platform == "win32":
            # A Windows runner shows these on a real desktop, and real input
            # landed on one: a click no test made pressed a remove button
            # and the job hung on the dialog it opened. A disabled window
            # takes no mouse or keyboard input from the OS; what a test sends
            # with event_generate goes through Tk's own queue and still
            # arrives.
            app.attributes("-disabled", True)
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
