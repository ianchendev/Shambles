"""Pasting the code from Claude's sign-in page back to ``claude auth login``.

When the browser cannot reach Shambles' machine (another device, another
browser profile, or the link copied out of the window), Claude's page ends by
showing a code: ``<authorization code>#<state>``. ``claude auth login`` reads
that code as a line on its standard input. 2.1.270, 2.1.289 and 2.1.300 all
do it with a line reader on ``process.stdin`` and no check that it is a
terminal. Shambles used to give the vendor ``/dev/null`` there, so the code
had nowhere to go.

The stand-in below follows that protocol: it prints the two lines and the
prompt Claude prints, then reads lines until one holds a ``#`` with something
on both sides. It is started by absolute path through this interpreter, so
the same tests run on Windows, where there is no ``/bin/sh``.

The code is treated as a credential throughout: it is never repeated in an
error, a progress line or a result.
"""

import subprocess
import sys
import textwrap
import threading
import time

import pytest

from conftest import posix_only
from helpers import make_profile
from shambles import login, providers
from shambles.app.service import HIDDEN_LINE, ShamblesService


#: Distinctive enough that finding it anywhere it should not be is proof.
CODE = "Zq7authCODE-x91_marker#st4te-MARKER_y"

#: Claude 2.1.300's ``claude auth login``, as far as stdin and stdout go.
FAKE_CLAUDE_LOGIN = textwrap.dedent("""\
    import os, sys, time
    print("Opening browser to sign in...", flush=True)
    print("If the browser didn't open, visit: "
          "https://claude.ai/oauth/authorize?code=true&client_id=x&state=s",
          flush=True)
    sys.stdout.write("Paste code here if prompted > ")
    sys.stdout.flush()
    received = os.environ.get("FAKE_RECEIVED")
    for line in sys.stdin:
        code, _, state = line.strip().partition("#")
        if not code or not state:
            sys.stderr.write(
                "Invalid code. Please make sure the full code was copied.\\n")
            sys.stderr.flush()
            continue
        if received:
            with open(received, "a", encoding="utf-8") as fh:
                fh.write(line)
        if os.environ.get("FAKE_ECHO"):
            print("got " + line.strip(), flush=True)
        print("Login successful.", flush=True)
        sys.exit(0)
    # Standard input closed. Claude has no handler for that and goes on
    # waiting for the browser, which is what keeps today's process alive.
    time.sleep(float(os.environ.get("FAKE_LINGER", "30")))
    sys.exit(3)
""")


@pytest.fixture
def claude():
    return providers.load("claude")


@pytest.fixture
def codex():
    return providers.load("codex")


@pytest.fixture
def paste_vendor(tmp_path):
    """argv for the stand-in, runnable on every system."""
    script = tmp_path / "fake_claude_login.py"
    script.write_text(FAKE_CLAUDE_LOGIN, encoding="utf-8")
    return [sys.executable, str(script)]


class Run:
    """A started LoginProcess with its output and exit collected."""

    def __init__(self, argv, *, takes_input, env=None):
        self.lines, self.codes = [], []
        self.done = threading.Event()
        self.popens = []
        self.kwargs = {}

        def popen(cmd, **kwargs):
            self.kwargs = kwargs
            child = subprocess.Popen(cmd, **kwargs)
            self.popens.append(child)
            return child

        self.process = login.LoginProcess(argv, env=env, popen=popen,
                                          takes_input=takes_input)
        self.process.start(on_line=self.lines.append, on_exit=self._exit)

    def _exit(self, code):
        self.codes.append(code)
        self.done.set()

    def wait_for_line(self, fragment, timeout=10):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if any(fragment in line for line in self.lines):
                return True
            time.sleep(0.02)
        return False


# -- what counts as a code --------------------------------------------------


def test_only_a_provider_whose_spec_says_so_takes_a_pasted_code(claude, codex):
    assert login.accepts_code(claude) is True
    # `codex login` finishes through its own callback server and never asks
    # for a code; device codes (S2) are shown, not pasted.
    assert login.accepts_code(codex) is False


def test_surrounding_whitespace_is_stripped(claude):
    assert login.clean_code(claude, f"  \t{CODE}\r\n ") == CODE


@pytest.mark.parametrize("pasted", [
    "",
    "   \n",
    f"{CODE[:10]}\n{CODE[10:]}",          # a line break inside
    f"{CODE[:10]}\r{CODE[10:]}",          # a lone carriage return
    f"{CODE[:10]}\t{CODE[10:]}",          # a tab
    f"{CODE[:10]}\x00{CODE[10:]}",        # NUL
    f"{CODE[:10]}\x1b[2J{CODE[10:]}",     # an escape sequence
    f"{CODE[:10]}\x7f{CODE[10:]}",        # DEL
    f"{CODE[:10]}\u0085{CODE[10:]}",      # NEL, a line break to some readers
    f"{CODE[:10]} {CODE[10:]}",      # LINE SEPARATOR
    f"{CODE[:10]}​{CODE[10:]}",      # a zero-width space from a web page
    f"{CODE[:10]}é{CODE[10:]}",           # outside what OAuth allows
    CODE.replace("#", ""),                # no separator: half a code
    "#" + CODE.split("#")[1],             # nothing before it
    CODE.split("#")[0] + "#",             # nothing after it
    CODE + "#" + "x" * login.MAX_CODE_LENGTH,  # longer than any real code
])
def test_anything_but_one_whole_code_is_refused_without_repeating_it(
        claude, pasted):
    with pytest.raises(login.CodeRejectedError) as caught:
        login.clean_code(claude, pasted)
    message = str(caught.value)
    assert message.endswith(".")
    for piece in (CODE.split("#")[0], CODE.split("#")[1], "MARKER", "marker"):
        assert piece not in message
        assert piece not in repr(caught.value)


def test_a_provider_that_takes_no_code_refuses_one(codex):
    with pytest.raises(login.CodeRejectedError) as caught:
        login.clean_code(codex, CODE)
    assert "MARKER" not in str(caught.value)


# -- getting it to the vendor -----------------------------------------------


def test_only_a_vendor_that_takes_input_gets_an_open_pipe(paste_vendor):
    """Codex keeps the end-of-file stdin it has always had."""
    closed = Run(paste_vendor, takes_input=False)
    assert closed.kwargs["stdin"] is subprocess.DEVNULL
    closed.process.cancel(grace=2.0)
    assert closed.done.wait(timeout=10)

    open_ = Run(paste_vendor, takes_input=True)
    assert open_.kwargs["stdin"] is subprocess.PIPE
    open_.process.cancel(grace=2.0)
    assert open_.done.wait(timeout=10)


def test_a_pasted_code_reaches_the_vendor_as_one_line(
        paste_vendor, tmp_path, monkeypatch):
    received = tmp_path / "received.txt"
    monkeypatch.setenv("FAKE_RECEIVED", str(received))
    run = Run(paste_vendor, takes_input=True)
    assert run.wait_for_line("visit: https://claude.ai/oauth/authorize")

    assert run.process.send_line(CODE) is True

    assert run.done.wait(timeout=10), "the vendor never read the code"
    assert run.codes == [0]
    assert received.read_text(encoding="utf-8") == CODE + "\n"


def test_input_is_closed_once_the_vendor_exits(paste_vendor):
    run = Run(paste_vendor, takes_input=True)
    assert run.process.send_line(CODE) is True
    assert run.done.wait(timeout=10)

    assert run.popens[0].stdin.closed
    # Nothing left to write to, and no error for trying.
    assert run.process.send_line(CODE) is False


def test_text_that_is_not_one_line_is_never_written(
        paste_vendor, tmp_path, monkeypatch):
    received = tmp_path / "received.txt"
    monkeypatch.setenv("FAKE_RECEIVED", str(received))
    run = Run(paste_vendor, takes_input=True)

    # A second line would be a second answer the user never typed.
    assert run.process.send_line("abc#def\nxyz#uvw") is False
    assert run.process.send_line("abc#def\r") is False
    assert run.process.send_line(CODE) is True

    assert run.done.wait(timeout=10)
    assert received.read_text(encoding="utf-8") == CODE + "\n"


def test_a_process_that_takes_no_input_refuses_to_send(paste_vendor):
    run = Run(paste_vendor, takes_input=False)
    assert run.process.send_line(CODE) is False
    run.process.cancel(grace=2.0)
    assert run.done.wait(timeout=10)


def test_sending_before_start_is_refused(paste_vendor):
    process = login.LoginProcess(paste_vendor, takes_input=True)
    assert process.send_line(CODE) is False


def test_a_vendor_that_closed_its_input_is_a_failed_send_not_a_crash(tmp_path):
    script = tmp_path / "closes_stdin.py"
    script.write_text(textwrap.dedent("""\
        import os, sys, time
        sys.stdin.close()
        os.close(0)
        print("ready", flush=True)
        time.sleep(30)
    """), encoding="utf-8")
    run = Run([sys.executable, str(script)], takes_input=True)
    assert run.wait_for_line("ready")

    # The first write may land in the pipe's buffer before the broken pipe
    # shows; within a few it must be refused, and never raise.
    results = [run.process.send_line(CODE) for _ in range(50)]
    assert results[-1] is False

    run.process.cancel(grace=2.0)
    assert run.done.wait(timeout=10)


@pytest.mark.parametrize("takes_input", [False, True])
def test_cancelling_with_nothing_pasted_still_ends_the_vendor(
        paste_vendor, monkeypatch, takes_input):
    """The open pipe must not change how a cancel ends the sign-in.

    The stand-in waits for its browser for thirty seconds either way: at end
    of file (today) or on a pipe nobody writes to (now). Ten seconds is the
    real assertion, as in ``test_cancelling_terminates_the_child``.
    """
    monkeypatch.setenv("FAKE_LINGER", "30")
    run = Run(paste_vendor, takes_input=takes_input)
    assert run.wait_for_line("Opening browser")

    run.process.cancel(grace=2.0)

    assert run.done.wait(timeout=10)
    assert run.process.running is False
    assert run.codes, "the exit callback must still fire for a cancel"
    if takes_input:
        assert run.popens[0].stdin.closed


# -- through the service ----------------------------------------------------


def service(paths):
    return ShamblesService(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux", clock_ms=lambda: 0)


@pytest.fixture
def held_login(monkeypatch):
    """The vendor replaced by a process that only records what it is sent."""
    processes = []

    class HeldLoginProcess:
        running = False

        def __init__(self, argv, **kwargs):
            self.takes_input = kwargs.get("takes_input", False)
            self.sent = []
            processes.append(self)

        def start(self, *, on_line, on_exit):
            self.running = True
            self.on_exit = on_exit

        def send_line(self, text):
            if not (self.running and self.takes_input):
                return False
            self.sent.append(text)
            return True

        def finish(self, code=0):
            self.running = False
            self.on_exit(code)

        def cancel(self):
            if self.running:
                self.finish(-15)

    monkeypatch.setattr("shambles.app.service.login.LoginProcess",
                        HeldLoginProcess)
    monkeypatch.setattr("shambles.app.service.login.available",
                        lambda provider: True)
    return processes


def _start(paths, provider_id):
    make_profile(paths, provider_id, "Personal", token=False)
    return service(paths).start_login(provider_id, "Personal",
                                      on_line=lambda line: None,
                                      on_done=lambda result: None)


def test_a_claude_sign_in_takes_a_code_and_codex_does_not(paths, held_login):
    assert _start(paths, "claude").accepts_code is True
    assert held_login[-1].takes_input is True
    assert _start(paths, "codex").accepts_code is False
    assert held_login[-1].takes_input is False


def test_a_good_code_is_sent_once_and_cleaned(paths, held_login):
    handle = _start(paths, "claude")

    result = handle.send_code(f"  {CODE}\n")

    assert result.ok is True
    assert held_login[0].sent == [CODE]


def test_a_bad_code_is_refused_in_words_that_do_not_repeat_it(
        paths, held_login):
    handle = _start(paths, "claude")
    bad = CODE.replace("#", "\n")

    result = handle.send_code(bad)

    assert result.ok is False
    assert result.error.code == "code_invalid"
    assert held_login[0].sent == []
    wire = repr(result.to_dict())
    for piece in ("MARKER", "marker", CODE.split("#")[0]):
        assert piece not in wire


def test_a_codex_sign_in_refuses_a_code(paths, held_login):
    result = _start(paths, "codex").send_code(CODE)
    assert result.ok is False
    assert result.error.code == "code_not_accepted"
    assert "MARKER" not in repr(result.to_dict())


def test_a_code_after_the_sign_in_ended_is_refused(paths, held_login):
    handle = _start(paths, "claude")
    held_login[0].finish(1)
    assert handle.wait(timeout=10)

    result = handle.send_code(CODE)

    assert result.ok is False
    assert result.error.code == "login_not_running"
    assert held_login[0].sent == []


def test_a_sign_in_that_never_started_refuses_a_code(paths, monkeypatch):
    monkeypatch.setattr("shambles.app.service.login.available",
                        lambda provider: False)
    handle = _start(paths, "claude")
    result = handle.send_code(CODE)
    assert result.ok is False
    assert result.error.code == "login_not_running"


@posix_only
def test_the_code_never_comes_back_as_progress_even_if_the_vendor_echoes_it(
        paths, fake_vendor, tmp_path, monkeypatch):
    """End to end, with a real process named ``claude`` on PATH.

    Through a pipe nothing echoes what is written, but a vendor that printed
    it back would still be filtered: every line that is not a supported
    sign-in link becomes the fixed progress line.
    """
    script = fake_vendor("claude")
    script.write_text(f"#!{sys.executable}\n" + FAKE_CLAUDE_LOGIN,
                      encoding="utf-8")
    received = tmp_path / "received.txt"
    monkeypatch.setenv("FAKE_RECEIVED", str(received))
    monkeypatch.setenv("FAKE_ECHO", "1")
    make_profile(paths, "claude", "Personal", token=False)
    lines, done = [], []

    handle = service(paths).start_login("claude", "Personal",
                                        on_line=lines.append,
                                        on_done=done.append)
    assert handle.send_code(CODE).ok is True
    assert handle.wait(timeout=10)

    assert received.read_text(encoding="utf-8") == CODE + "\n"
    assert lines, "the vendor's output should still arrive as progress"
    assert "MARKER" not in "\n".join(lines)
    assert set(lines) <= {HIDDEN_LINE} | {
        line for line in lines if line.startswith("https://")}
    # It exited 0 without writing a login, so the service says so.
    assert done[0].error.code == "login_not_written"
    assert "MARKER" not in repr(done[0].to_dict())


# -- what Claude Code 2.1.330 refuses, refused here with a reason ------------
#
# 2.1.330 checks a pasted line before using it: it wants code#state, and it
# refuses a localhost or web address and a 4-10 digit verification code,
# saying why on stderr (the review lane's reading of its binary). Shambles
# shows stderr only as "[vendor output hidden]", so a paste it passed on
# would sit there unexplained. The same refusals happen here first, each
# with a sentence of its own that never repeats what was pasted.

#: Shaped like a real paste: an authorization code, '#', a 43-character
#: base64url state. Made up.
REAL = ("Zq7wPLm0vB2cXk9-Tr4_YhGd8sNe1QaU3iJoF6lKpMnB"
        "#qW8eR5tY2uI0oP7aS4dF1gH6jK9lZ3xC0vB5nM2-_9")


@pytest.mark.parametrize("pasted", [
    "https://platform.claude.com/oauth/code/callback?code=abcMARK&state=xyz",
    "https://platform.claude.com/oauth/code/callback?code=abcMARK#xyz",
    "HTTPS://Claude.com/cai/oauth/authorize?code=true#MARK",
    "http://localhost:54545/callback?code=abcMARK&state=xyz",
    "localhost:54545/callback?code=abcMARK#xyz",
    "localhost/callback#MARK",
    "127.0.0.1:54545/callback?code=abc#MARK",
    "platform.claude.com/oauth/code/callback?code=abcMARK#xyz",
    "claude.ai/oauth/authorize#MARK",
])
def test_a_page_address_is_refused_as_an_address(claude, pasted):
    with pytest.raises(login.CodeRejectedError) as caught:
        login.clean_code(claude, pasted)
    assert str(caught.value) == login.CODE_IS_ADDRESS
    assert "MARK" not in str(caught.value) + repr(caught.value)


@pytest.mark.parametrize("pasted", ["1234", "482913", " 482913\n",
                                    "1234567890"])
def test_a_verification_code_is_refused_as_one(claude, pasted):
    with pytest.raises(login.CodeRejectedError) as caught:
        login.clean_code(claude, pasted)
    assert str(caught.value) == login.CODE_IS_VERIFICATION
    assert pasted.strip() not in str(caught.value)


@pytest.mark.parametrize("pasted", ["123", "12345678901"])
def test_digits_that_are_no_verification_code_are_only_part_of_one(
        claude, pasted):
    with pytest.raises(login.CodeRejectedError) as caught:
        login.clean_code(claude, pasted)
    assert str(caught.value) == login.CODE_INCOMPLETE


@pytest.mark.parametrize("pasted", [
    REAL,
    f"  {REAL}\n",
    CODE,
    # A code with a dot in it is not an address: no path, port or query.
    "abc.def-GHI#" + "s" * 43,
    # Digits before the '#' are a code, not a verification code.
    "482913#" + "s" * 43,
])
def test_a_real_code_and_state_still_pass(claude, pasted):
    assert login.clean_code(claude, pasted) == pasted.strip()


def test_the_service_says_why_without_the_paste(paths, held_login):
    handle = _start(paths, "claude")

    address = handle.send_code(
        "https://platform.claude.com/oauth/code/callback?code=MARKER&s=1")
    digits = handle.send_code("482913")

    assert (address.error.code, address.error.message) == (
        "code_invalid", login.CODE_IS_ADDRESS)
    assert (digits.error.code, digits.error.message) == (
        "code_invalid", login.CODE_IS_VERIFICATION)
    assert held_login[0].sent == []
    assert "MARKER" not in repr(address.to_dict())
    assert "482913" not in repr(digits.to_dict())


def test_a_provider_whose_spec_does_not_say_so_is_not_checked_this_way(
        claude, monkeypatch):
    """The refusals are Claude Code's, written in its spec; a provider that
    takes codes without them keeps only the general rules."""
    rules = dict(claude.spec["login"]["paste_code"])
    rules.pop("refuses", None)
    spec = {**claude.spec, "login": {**claude.spec["login"],
                                     "paste_code": rules}}
    monkeypatch.setattr(claude, "spec", spec)
    assert login.clean_code(claude, "482913#" + "s" * 43)
    with pytest.raises(login.CodeRejectedError) as caught:
        login.clean_code(claude, "482913")
    assert str(caught.value) == login.CODE_INCOMPLETE
