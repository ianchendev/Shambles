"""Cancelling a sign-in on Windows ends the vendor, not just its launcher.

npm installs ``claude.cmd`` and ``codex.cmd``. What Shambles starts is then
``cmd.exe``, and the vendor is its child (``node``, and under Codex's
launcher the native ``codex.exe`` below that). ``Popen.terminate()`` on
Windows is ``TerminateProcess`` on that one process: ``cmd.exe`` goes, the
vendor stays, still holding its callback port and Shambles' output pipe. The
cancel's result only arrived when the vendor gave up on its own.

So on Windows a cancel ends the whole tree under Shambles' own child with
``taskkill /F /T /PID``, which is as forceful as ``TerminateProcess`` was,
and falls back to ``terminate()`` when that cannot run. POSIX is unchanged:
there the vendor is the process Shambles started, and Codex's npm launcher
forwards SIGTERM to its native binary (``codex-cli/bin/codex.js``).
"""

import subprocess
import sys
import textwrap
import threading
import time

import pytest

from shambles import login

windows_only = pytest.mark.skipif(sys.platform != "win32",
                                  reason="a .cmd shim needs cmd.exe")

TASKKILL = r"C:\Windows\System32\taskkill.exe"


class Ran:
    def __init__(self, returncode=0, raises=None):
        self.returncode = returncode
        self.raises = raises
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), kwargs))
        if self.raises is not None:
            raise self.raises
        return subprocess.CompletedProcess(argv, self.returncode)


# -- the command ------------------------------------------------------------


def test_the_tree_is_ended_by_the_child_s_own_pid():
    ran = Ran()
    assert login.kill_tree(4242, timeout=5, run=ran,
                           which=lambda name: TASKKILL) is True
    argv, kwargs = ran.calls[0]
    assert argv == [TASKKILL, "/F", "/T", "/PID", "4242"]
    assert kwargs["timeout"] == 5
    # Never through a shell, and nothing of taskkill's reaches the window.
    assert not kwargs.get("shell")
    assert kwargs["stdout"] is subprocess.DEVNULL
    assert kwargs["stderr"] is subprocess.DEVNULL


@pytest.mark.parametrize("ran", [
    Ran(returncode=128),                                   # no such process
    Ran(returncode=1),                                     # access denied
    Ran(raises=OSError("cannot start")),
    Ran(raises=subprocess.TimeoutExpired("taskkill", 5)),
])
def test_a_taskkill_that_does_not_succeed_reports_false(ran):
    assert login.kill_tree(4242, timeout=5, run=ran,
                           which=lambda name: TASKKILL) is False


def test_without_taskkill_nothing_is_run(monkeypatch):
    monkeypatch.delenv("SystemRoot", raising=False)
    monkeypatch.delenv("windir", raising=False)
    ran = Ran()
    assert login.kill_tree(4242, timeout=5, run=ran,
                           which=lambda name: None) is False
    assert ran.calls == []


def test_taskkill_is_found_under_the_system_root_when_path_lacks_it(
        tmp_path, monkeypatch):
    system32 = tmp_path / "System32"
    system32.mkdir()
    exe = system32 / "taskkill.exe"
    exe.write_bytes(b"")
    monkeypatch.setenv("SystemRoot", str(tmp_path))
    ran = Ran()
    assert login.kill_tree(7, timeout=5, run=ran,
                           which=lambda name: None) is True
    assert ran.calls[0][0][0] == str(exe)


# -- when cancel uses it ----------------------------------------------------


class Child:
    """A Popen that is still running until something ends it."""

    pid = 4242

    def __init__(self, *, stays_after_tree_kill=False):
        self.returncode = None
        self.terminated = self.killed = False
        self.stays = stays_after_tree_kill
        self.tree_killed = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        if self.returncode is None:
            raise subprocess.TimeoutExpired("vendor", timeout)
        return self.returncode

    def terminate(self):
        self.terminated = True
        self.returncode = 1

    def kill(self):
        self.killed = True
        self.returncode = 1


def _running(child, monkeypatch, *, tree, tree_result):
    """A LoginProcess whose child is ``child``, with the tree kill faked."""
    calls = []

    def fake_kill_tree(pid, *, timeout):
        calls.append((pid, timeout))
        if tree_result and not child.stays:
            child.tree_killed = True
            child.returncode = 1
        return tree_result

    monkeypatch.setattr(login, "KILL_TREE", tree)
    monkeypatch.setattr(login, "kill_tree", fake_kill_tree)
    process = login.LoginProcess(["vendor"])
    process._process = child
    return process, calls


def test_on_windows_a_cancel_ends_the_tree_and_nothing_else(monkeypatch):
    child = Child()
    process, calls = _running(child, monkeypatch, tree=True, tree_result=True)

    process.cancel(grace=2.0)

    assert calls == [(4242, 2.0)]
    assert child.tree_killed
    assert not child.terminated and not child.killed


def test_when_taskkill_fails_cancel_falls_back_to_terminate(monkeypatch):
    child = Child()
    process, calls = _running(child, monkeypatch, tree=True,
                              tree_result=False)

    process.cancel(grace=2.0)

    assert calls == [(4242, 2.0)]
    assert child.terminated


def test_a_child_that_outlives_the_tree_kill_is_terminated(monkeypatch):
    child = Child(stays_after_tree_kill=True)
    process, _ = _running(child, monkeypatch, tree=True, tree_result=True)

    process.cancel(grace=0.1)

    assert child.terminated


def test_elsewhere_cancel_is_unchanged(monkeypatch):
    child = Child()
    process, calls = _running(child, monkeypatch, tree=False,
                              tree_result=True)

    process.cancel(grace=2.0)

    assert calls == []
    assert child.terminated


def test_a_finished_child_is_left_alone(monkeypatch):
    child = Child()
    child.returncode = 0
    process, calls = _running(child, monkeypatch, tree=True, tree_result=True)

    process.cancel(grace=2.0)

    assert calls == []
    assert not child.terminated


def test_kill_tree_is_on_for_windows_only():
    assert login.KILL_TREE is (sys.platform == "win32")


# -- the real thing, on Windows ---------------------------------------------


@windows_only
def test_cancel_ends_a_vendor_started_through_a_cmd_shim(tmp_path):
    """The shape npm gives every vendor CLI on Windows, end to end."""
    beat = tmp_path / "heartbeat.txt"
    child = tmp_path / "vendor.py"
    child.write_text(textwrap.dedent(f"""\
        import time
        print("started", flush=True)
        while True:
            with open({str(beat)!r}, "a") as fh:
                fh.write("x")
            time.sleep(0.1)
    """), encoding="utf-8")
    shim = tmp_path / "vendor.cmd"
    shim.write_text(f'@"{sys.executable}" "{child}" %*\r\n', encoding="utf-8")

    lines, codes, done = [], [], threading.Event()
    process = login.LoginProcess([str(shim)])
    process.start(on_line=lines.append,
                  on_exit=lambda code: (codes.append(code), done.set()))
    deadline = time.monotonic() + 30
    while "started" not in lines and time.monotonic() < deadline:
        time.sleep(0.05)
    assert "started" in lines, "the vendor behind the shim never started"

    process.cancel(grace=5.0)

    # The exit arrives only once nothing holds the output pipe, and the
    # vendor behind cmd.exe holds it until it is gone.
    assert done.wait(timeout=15), "the vendor behind the shim was left running"
    size = beat.stat().st_size
    time.sleep(0.5)
    assert beat.stat().st_size == size, "the vendor is still writing"
