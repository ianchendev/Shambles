"""Handing a lapsed profile to the vendor's own login flow.

The only module in Shambles that spawns a process.

DD-2 concluded that login must not be implemented inside this tool, and that
conclusion still holds completely: **no OAuth code lives here**. Both vendors
ship a one-shot command that opens the browser itself and runs its own
callback server, so this module starts that command, streams what it prints,
and waits. The credential still appears on disk written by the vendor, and
Shambles still only ever finds it there.

What DD-2 also said was that the tool "never opens a browser". That line is
crossed deliberately -- see the design doc -- and the thing it was protecting,
the absence of network reach and OAuth handling, is untouched. There is still
no ``socket``, no ``urllib``, no ``requests``, and ``tests/test_login.py``
asserts that mechanically rather than by promise.
"""

import re
import shutil
import subprocess
import threading

from .errors import ShamblesError


#: Both vendors print a URL to visit when they cannot launch a browser, which
#: is the normal case under WSL and over SSH. Pulling it out lets the window
#: offer it as something to click or copy rather than as text to retype.
_URL = re.compile(r"https?://[^\s<>\"'`]+")

#: Trailing punctuation that belongs to the sentence, not the address.
_TRAILING = ".,;:!?)]}>'\""


def find_url(line: str) -> str | None:
    """The first http(s) URL in ``line``, or None.

    Restricted to http and https on purpose: this feeds a control that opens
    whatever it is given, and a vendor is never going to ask for file:// or
    ftp://.
    """
    match = _URL.search(line or "")
    if not match:
        return None
    return match.group(0).rstrip(_TRAILING)


class LoginUnavailableError(ShamblesError):
    """The vendor's login command could not be started."""


NOT_ON_PATH = (
    "{binary} is not installed, or not on your PATH.\n\n"
    "Shambles does not sign you in itself — it runs {binary}, which opens "
    "your browser. Install it first, then try again."
)


def binary(provider) -> str:
    return provider.login_binary()


def available(provider) -> bool:
    """Whether this provider's login command can be run at all.

    Probed rather than assumed: offering a provider whose CLI is absent means
    the user only finds out at the moment they expected a browser.
    """
    return shutil.which(provider.login_binary()) is not None


def command(provider, *, email: str | None = None) -> list[str]:
    """The vendor's login argv, optionally pre-filling a known address.

    A provider that declares no ``email_flag`` gets no address rather than a
    guessed flag name.
    """
    argv = provider.login_command()
    flag = provider.spec.get("login", {}).get("email_flag")
    if email and flag:
        argv = argv + [flag, email]
    return argv


class LoginProcess:
    """One run of a vendor login command.

    Output is streamed line by line rather than collected, because the line
    that matters most arrives early: both vendors print a URL to open by hand
    when they cannot launch a browser, which is the normal case under WSL and
    over SSH. A user staring at a spinner while that URL sits in an unread
    buffer would conclude the tool is broken.

    ``on_line`` and ``on_exit`` are invoked **on a worker thread**. Tk callers
    must marshal back with ``widget.after``; a blocking wait on the main
    thread freezes the window and stops the signal pump that makes Ctrl+C
    work.
    """

    def __init__(self, argv, *, popen=subprocess.Popen):
        self._argv = list(argv)
        self._popen = popen
        self._process = None
        self._thread = None
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, *, on_line, on_exit) -> None:
        if shutil.which(self._argv[0]) is None:
            raise LoginUnavailableError(NOT_ON_PATH.format(binary=self._argv[0]))
        try:
            self._process = self._popen(
                self._argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise LoginUnavailableError(
                f"Could not start {self._argv[0]}:\n{exc}") from exc

        self._thread = threading.Thread(
            target=self._pump, args=(on_line, on_exit), daemon=True)
        self._thread.start()

    def _pump(self, on_line, on_exit) -> None:
        try:
            if self._process.stdout is not None:
                for line in self._process.stdout:
                    on_line(line.rstrip("\n"))
        except (OSError, ValueError):
            # The pipe closed under us, which is what cancel() looks like from
            # here. The exit code below is the real answer either way.
            pass
        code = self._process.wait()
        on_exit(code)

    def cancel(self, *, grace: float = 5.0) -> None:
        """Stop the vendor process.

        SIGTERM first so it can release its callback port, SIGKILL only if it
        will not go. Leaving one running would hold that port and make the
        next attempt fail for a reason the user could not possibly guess.
        """
        self._cancelled = True
        if self._process is None or self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self._process.kill()
