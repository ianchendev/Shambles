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
    after its own assertions have passed, and into whatever the next test set
    up. With the classic Tk window that aborted the whole interpreter: Tcl
    entered from the wrong thread.

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


@pytest.fixture(autouse=True)
def no_real_window(monkeypatch):
    """`shambles gui` must never open the real Qt window from a test.

    Qt is installed on CI, so a test that reaches ``cli.main(["gui"])``
    would otherwise start a real event loop and hang the run. Tests about
    the Qt window replace these two again with stand-ins of their own.
    """
    from shambles.app import cli, launch

    def unavailable():
        raise ImportError("the Qt window is switched off under test")

    monkeypatch.setattr(cli, "_window_entry", unavailable)
    monkeypatch.setattr(launch, "window_bundle", lambda **_kw: None)


@pytest.fixture
def home(tmp_path):
    """A synthetic home directory. Never the real one."""
    return tmp_path


@pytest.fixture
def paths(home):
    return Paths.for_home(home)


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

    ``linger`` keeps it running that many seconds, as a vendor waiting for
    its browser does, and then it exits 0 whatever ``exit_code`` says. The
    wait is an ``exec``: the stand-in becomes the waiting process rather than
    a shell with a child, as a real vendor on these systems is the process
    Shambles started. A shell killed while its ``sleep`` ran would leave that
    child holding the output pipe, and a cancel test would pass or fail on
    whether the shell had forked yet.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(bindir))

    def _make(name, *, exit_code=0, lines=("Visit https://example.test/auth",),
              linger=0):
        script = bindir / name
        body = "\n".join(f"echo {line!r}" for line in lines)
        tail = f"exec sleep {linger}\n" if linger else f"exit {exit_code}\n"
        script.write_text(f"#!/bin/sh\n{body}\n{tail}", encoding="utf-8")
        script.chmod(0o755)
        return script

    return _make
