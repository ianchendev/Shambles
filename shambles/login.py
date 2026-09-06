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

import os
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


#: URL openers, most reliable first.
#:
#: WSL is the case that matters: ``webbrowser`` there picks ``gio``, which has
#: no handler and fails with "Operation not supported" -- and reports success
#: anyway, so a caller trusting its return value never falls back. The Windows
#: side has to be reached instead. ``wslview`` ships in wslu and is often
#: absent; ``explorer.exe`` is on every install.
#: Each entry is (argv prefix, return codes that mean it worked).
#:
#: ``explorer.exe`` returns **1 on success** -- a long-standing quirk, not an
#: error -- so treating a non-zero exit as failure rejects the one opener that
#: actually works here.
#:
#: ``cmd.exe /c start`` is deliberately absent. cmd splits its argument at
#: ``&`` whatever the quoting, and every OAuth URL is full of them: the real
#: sign-in link failed with "'b' is not recognized as an internal or external
#: command".
WSL_OPENERS = (
    (["wslview"], (0,)),
    (["explorer.exe"], (0, 1)),
)

DESKTOP_OPENERS = (
    (["xdg-open"], (0,)),
    (["gio", "open"], (0,)),
    (["sensible-browser"], (0,)),
)

#: Long enough for a handler to spawn, short enough not to hang the window.
OPEN_TIMEOUT = 10


def is_wsl(*, proc_version="/proc/version", env=None) -> bool:
    env = os.environ if env is None else env
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    try:
        with open(proc_version, encoding="utf-8", errors="replace") as fh:
            return "microsoft" in fh.read().lower()
    except OSError:
        return False


def browser_commands(*, wsl=None, which=shutil.which) -> list:
    """Openers to try, in order, filtered to what is installed."""
    if wsl is None:
        wsl = is_wsl()
    candidates = WSL_OPENERS + DESKTOP_OPENERS if wsl else DESKTOP_OPENERS
    return [(list(argv), codes) for argv, codes in candidates if which(argv[0])]


def open_url(url, *, wsl=None, which=shutil.which, runner=None) -> bool:
    """Hand ``url`` to the first opener that accepts it.

    Returns whether one reported success. The URL is passed as a single argv
    element and never through a shell -- it arrives from another process's
    stdout, so it is not ours to trust.

    Covers Linux and WSL. On native Windows none of these binaries exists, so
    this finds nothing and returns False; the caller falls back to
    ``webbrowser``, which uses ``os.startfile`` there and is the right answer.
    ``tests/test_browser.py`` pins that fallback, because losing it would take
    Windows with it silently.
    """
    if not url or not str(url).lower().startswith(("http://", "https://")):
        return False
    if runner is None:
        runner = subprocess.run

    for argv, accepted in browser_commands(wsl=wsl, which=which):
        try:
            result = runner(argv + [url], timeout=OPEN_TIMEOUT,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)
        except Exception:
            continue
        if getattr(result, "returncode", None) in accepted:
            return True
    return False


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
