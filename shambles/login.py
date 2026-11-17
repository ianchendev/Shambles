"""Handing a lapsed profile to the vendor's own login flow.

The only module in Shambles that spawns a process.

DD-2 concluded that login must not be implemented inside this tool, and that
conclusion still holds completely: **no OAuth code lives here**. Both vendors
ship a one-shot command that opens the browser itself and runs its own
callback server, so this module starts that command, streams what it prints,
and waits. The one thing it ever passes back is the code a sign-in page shows
when the browser cannot reach this machine, typed into the vendor's own
prompt exactly as a person at a terminal would. The credential still appears
on disk written by the vendor, and Shambles still only ever finds it there.

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
from pathlib import Path

from .errors import ShamblesError
from .providers import spec as specmod


#: Both vendors print a URL to visit when they cannot launch a browser, which
#: is the normal case under WSL and over SSH. Pulling it out lets the window
#: offer it as something to click or copy rather than as text to retype.
_URL = re.compile(r"https?://[^\s<>\"'`\x00-\x1f\x7f]+")

#: Terminal escapes a vendor may wrap the URL in. Claude Code prints its link
#: as an OSC 8 hyperlink (target, then the same URL as the visible text)
#: whenever it decides the terminal can show one, which it judges from the
#: environment too: Windows Terminal's WT_SESSION, inherited by WSL shells,
#: is enough even when its output is a pipe. Removing the escapes, the
#: hyperlink's target included, leaves the text a person would have seen.
_ESCAPE = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"   # OSC ... BEL/ST
                     r"|\x1b\[[0-?]*[ -/]*[@-~]")             # CSI (colour)

#: Trailing punctuation that belongs to the sentence, not the address.
_TRAILING = ".,;:!?)]}>'\""


def find_url(line: str) -> str | None:
    """The first http(s) URL in ``line``, or None.

    Restricted to http and https on purpose: this feeds a control that opens
    whatever it is given, and a vendor is never going to ask for file:// or
    ftp://.
    """
    match = _URL.search(_ESCAPE.sub("", line or ""))
    if not match:
        return None
    return match.group(0).rstrip(_TRAILING)


#: Where each vendor sends a sign-in, as its current client builds the link:
#: Claude Code 2.1.270 to 2.1.300 (read from the binary) uses claude.com for
#: a Claude account and platform.claude.com for the Console; the claude.ai
#: and console.anthropic.com forms are older clients'. Codex uses
#: auth.openai.com (codex-rs/login, ``build_authorize_url``).
_AUTH_ENDPOINTS = frozenset({
    "https://auth.openai.com/authorize",
    "https://auth.openai.com/oauth/authorize",
    "https://claude.com/cai/oauth/authorize",
    "https://platform.claude.com/oauth/authorize",
    "https://claude.ai/oauth/authorize",
    "https://console.anthropic.com/oauth/authorize",
})
_AUTH_PARAMETERS = frozenset({
    "response_type", "client_id", "redirect_uri", "scope", "state",
    "code_challenge", "code_challenge_method", "login_hint", "prompt",
    # Claude Code: ``code=true`` on every link, the others when set.
    "code", "orgUUID", "login_method",
    # Codex.
    "id_token_add_organizations", "codex_cli_simplified_flow", "originator",
    "allowed_workspace_id", "current_workspace_id", "connection",
})
#: Parameters held to a narrower value than the general rule below.
_AUTH_VALUES = {
    # In every other OAuth message ``code`` carries an authorization code.
    # In a Claude Code sign-in link it is only ever the literal ``true``.
    "code": re.compile(r"true"),
    "orgUUID": re.compile(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}"
                          r"-[0-9a-fA-F]{12}"),
    "redirect_uri": re.compile(
        r"http://(?:localhost|127\.0\.0\.1)(?::[0-9]{1,5})?/"
        r"(?:auth/callback|callback)|"
        r"https://(?:console\.anthropic\.com|platform\.claude\.com)"
        r"/oauth/code(?:/callback)?"),
}


def authorization_url(line: str) -> str | None:
    """Expose supported sign-in requests, never arbitrary URLs from stdout.

    This is a narrow output filter, not an OAuth implementation. Unknown
    endpoints/parameters, fragments, userinfo and nested query strings fail
    closed. State and PKCE challenges must survive for the vendor's own flow.
    No networking or URL-opening module is needed to check this small grammar.
    """
    url = find_url(line)
    if not url:
        return None
    endpoint, _, query = url.partition("?")
    if endpoint not in _AUTH_ENDPOINTS:
        return None
    seen = set()
    for field in query.split("&") if query else ():
        key, separator, value = field.partition("=")
        if key not in _AUTH_PARAMETERS or key in seen or not separator:
            return None
        seen.add(key)
        # Decode once and reject remaining escapes as well as URL delimiters;
        # double encoding must not smuggle a second URL or credential field.
        value = re.sub(r"%([0-9a-fA-F]{2})",
                       lambda match: chr(int(match.group(1), 16)), value)
        if not re.fullmatch(r"[A-Za-z0-9._~+ :/@,-]*", value):
            return None
        narrower = _AUTH_VALUES.get(key)
        if narrower is not None and not narrower.fullmatch(value):
            return None
    return url


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


class CodeRejectedError(ShamblesError):
    """A pasted sign-in code that Shambles will not pass to the vendor.

    The message is always one of the fixed sentences below. It never holds
    what was pasted: until it is used, the code from the sign-in page is as
    good as a password.
    """


#: Far longer than any real code. Claude's is an authorization code and its
#: state, around a hundred characters together. The cap also keeps a write
#: well inside a pipe's buffer, so sending can never block the window.
MAX_CODE_LENGTH = 1024

CODE_EMPTY = "Paste the code from the browser page first."
CODE_HIDDEN_CHARACTERS = ("That code has a line break or a hidden character "
                          "in it. Copy it again from the browser page.")
CODE_INCOMPLETE = ("That is only part of the code. Copy all of it from the "
                   "browser page.")
CODE_TOO_LONG = ("That is longer than a sign-in code. Copy only the code "
                 "from the browser page.")
CODE_NOT_TAKEN = ("{binary} does not take a pasted code. Finish signing in "
                  "in the browser.")

#: What an OAuth code or state may contain: visible ASCII and the space
#: (RFC 6749, appendix A, VSCHAR). Nothing that ends a line, moves a cursor
#: or hides itself on a web page gets through to the vendor's input.
_ONE_LINE = re.compile(r"[\x20-\x7e]+")


def _paste_rules(provider) -> dict | None:
    rules = provider.spec.get("login", {}).get("paste_code")
    return rules if isinstance(rules, dict) else None


def accepts_code(provider) -> bool:
    """Whether this provider's sign-in reads a code pasted from the browser.

    From the spec rather than assumed: ``claude auth login`` does, and
    ``codex login`` finishes through its own callback server and never asks.
    """
    return _paste_rules(provider) is not None


def clean_code(provider, pasted) -> str:
    """The code to send, or :class:`CodeRejectedError` saying why not.

    Surrounding whitespace goes, since a copy from a web page often brings a
    line break with it. Anything else that is not one line of visible
    characters is refused rather than repaired: a code with a character
    missing is a code that fails at the vendor with a message Shambles
    cannot show.
    """
    rules = _paste_rules(provider)
    if rules is None:
        raise CodeRejectedError(CODE_NOT_TAKEN.format(binary=binary(provider)))
    text = (pasted or "").strip()
    if not text:
        raise CodeRejectedError(CODE_EMPTY)
    if len(text) > MAX_CODE_LENGTH:
        raise CodeRejectedError(CODE_TOO_LONG)
    if not _ONE_LINE.fullmatch(text):
        raise CodeRejectedError(CODE_HIDDEN_CHARACTERS)
    separator = rules.get("separator")
    if separator:
        # The vendor's own rule: both halves present, or it prints "Invalid
        # code" where only it can see it and goes on waiting.
        head, found, tail = text.partition(separator)
        if not (head and found and tail):
            raise CodeRejectedError(CODE_INCOMPLETE)
    return text


def environment(provider, *, home, platform) -> dict[str, str]:
    """Give the child the same home and configuration as its provider store.

    Preserve PATH and the desktop session. Provider-owned configuration and
    secure-store selectors come from the injected provider environment, not
    unrelated values in the parent. In particular, do not introduce a Claude
    config override when none existed: that would change its Keychain name.
    """
    child = dict(os.environ)
    provider_env = provider.env
    child.update(provider_env)
    # Every variable that decides *where* the vendor keeps its login comes
    # from the provider's environment or not at all. The config directory is
    # passed through exactly as it was written: Claude Code hashes that raw
    # string into its Keychain item name, so a tidied copy -- a trailing
    # slash dropped, separators flipped -- would sign in to a different item
    # from the one the user's own shell reads.
    for key in _store_selectors(provider.spec):
        child.pop(key, None)
        if key in provider_env:
            child[key] = provider_env[key]
    resolved_home = str(Path(home).resolve())
    child["HOME"] = resolved_home
    child["USERPROFILE"] = resolved_home
    if platform == "win32":
        drive, tail = os.path.splitdrive(resolved_home)
        child["HOMEDRIVE"] = drive
        child["HOMEPATH"] = tail
    return child


def _store_selectors(spec: dict) -> set[str]:
    """Names of the environment variables a spec says relocate the login.

    Collected from the spec rather than listed here, so a variable the
    research turns up later is honoured the moment it is written down: the
    config directory, and anything under ``store`` or ``secure_dir`` whose
    key is ``env`` or ends in ``_env``.
    """
    found = set()

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if isinstance(value, str) and (key == "env"
                                               or key.endswith("_env")):
                    found.add(value)
                else:
                    walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for section in ("config_dir", "secure_dir", "store"):
        walk(spec.get(section))
    found.discard("")
    return found


class LoginProcess:
    """One run of a vendor login command.

    Output is streamed line by line rather than collected, because the line
    that matters most arrives early: both vendors print a URL to open by hand
    when they cannot launch a browser, which is the normal case under WSL and
    over SSH. A user staring at a spinner while that URL sits in an unread
    buffer would conclude the tool is broken.

    ``on_line`` and ``on_exit`` are invoked **on a worker thread**. They must
    not call Tk at all, ``widget.after`` included: hand the value to the Tk
    thread (``LoginDialog`` puts it on a ``queue.Queue`` that the window
    polls). A blocking wait on the main thread instead freezes the window and
    stops the signal pump that makes Ctrl+C work.

    ``takes_input`` gives the vendor a pipe on its standard input instead of
    an empty one, for :meth:`send_line`. Only a provider that reads a pasted
    code asks for it (:func:`accepts_code`). For every other vendor nothing
    changes: its input is at end of file from the start, as it always was.
    """

    def __init__(self, argv, *, env=None, popen=subprocess.Popen,
                 takes_input=False):
        self._argv = list(argv)
        self._env = dict(env) if env is not None else None
        self._popen = popen
        self._process = None
        self._thread = None
        self._cancelled = False
        self._takes_input = bool(takes_input)
        #: Held while writing to or closing the vendor's input, so a send
        #: racing the vendor's exit either lands whole or reports False.
        self._input_lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, *, on_line, on_exit) -> None:
        resolved = shutil.which(
            self._argv[0], path=(self._env.get("PATH", os.defpath)
                                 if self._env is not None else None))
        if resolved is None:
            raise LoginUnavailableError(NOT_ON_PATH.format(binary=self._argv[0]))
        # Started by the path that was found, not by the bare name. On
        # Windows the two are different questions: ``which`` honours PATHEXT
        # and finds ``claude.cmd``, the shim npm installs, while the system
        # call that starts a process looks for ``claude.exe`` and nothing
        # else. Started by name, a vendor CLI installed through npm was
        # reported as on PATH and then could not be started.
        argv = [resolved, *self._argv[1:]]
        try:
            self._process = self._popen(
                argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                # A pipe, not a pseudo-terminal. Claude Code reads a pasted
                # code from a pipe as readily as from a terminal, and a
                # terminal would change what it prints: the sign-in link
                # comes wrapped in hyperlink escapes and colour, and it
                # starts reading keystrokes in raw mode.
                stdin=(subprocess.PIPE if self._takes_input
                       else subprocess.DEVNULL),
                text=True,
                bufsize=1,
                env=self._env,
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
        self._close_input()
        on_exit(code)

    def send_line(self, text) -> bool:
        """Write ``text`` and a line break to the vendor's standard input.

        Returns whether it was written. False, never an exception, when this
        process takes no input, has not started, has exited, or its vendor
        closed its end. ``text`` is a sign-in code, so it is never logged and
        never part of an error; the caller reports a fixed sentence.

        Only one line of visible characters is written: a line break inside
        would be a second answer nobody typed. :func:`clean_code` refuses
        such text with a reason first; this is the backstop.
        """
        if not self._takes_input or not _ONE_LINE.fullmatch(text or ""):
            return False
        with self._input_lock:
            process = self._process
            if process is None or process.poll() is not None:
                return False
            stream = process.stdin
            if stream is None or stream.closed:
                return False
            try:
                stream.write(text + "\n")
                stream.flush()
            except (OSError, ValueError):
                # Its reader is gone. What the exception says is not passed
                # on: it is about the pipe, and the caller has a sentence.
                return False
        return True

    def _close_input(self) -> None:
        """Close the vendor's input once it has exited. Never raises."""
        with self._input_lock:
            stream = getattr(self._process, "stdin", None)
            if stream is None or stream.closed:
                return
            try:
                stream.close()
            except OSError:
                # A flush into a pipe whose reader has exited. The stream is
                # closed all the same.
                pass

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
