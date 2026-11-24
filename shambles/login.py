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
import sys
import threading
from dataclasses import dataclass
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
#: The short sign-in link Claude Code 2.1.330 prints by default (``tZe``):
#: claude.ai's authorize address, then one bare field, the known scopes as a
#: base64url bitmask (one or two characters) followed by the 43-character
#: PKCE challenge, then named fields as usual. Nothing in it is a secret; it
#: stands for the full link above, which the server rebuilds.
_SHORT_LINK_ENDPOINT = "https://claude.ai/oauth/authorize"
_SHORT_LINK_FIELD = re.compile(r"[A-Za-z0-9_-]{44,45}")

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
    fields = query.split("&") if query else []
    if (endpoint == _SHORT_LINK_ENDPOINT and fields
            and "=" not in fields[0]):
        if not _SHORT_LINK_FIELD.fullmatch(fields[0]):
            return None
        fields = fields[1:]
    seen = set()
    for field in fields:
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


# -- programs already running (M1) ---------------------------------------------

#: How long ``ps`` may take before the answer is "unknown".
PS_TIMEOUT_S = 5


def running_programs(name, *, platform=sys.platform, proc=Path("/proc"),
                     run=None):
    """The argv of every running process whose program is ``name``.

    Matched on the program itself, never its arguments, so ``vim codex`` is
    not Codex and a ``node .../codex.js`` launcher is not counted twice
    beside the binary it starts. Linux and WSL read ``/proc`` and start
    nothing. macOS asks ``ps``, which is why this lives here: this module is
    the only one that starts a process. Returns None where the answer is
    unknown -- native Windows, or ``ps`` failing -- and a caller then says
    nothing rather than guess.

    Only ever looks. Nothing is signalled, stopped or restarted.
    """
    if platform.startswith("linux"):
        return _from_proc(name, proc)
    if platform == "darwin":
        return _from_ps(name, run or subprocess.run)
    return None


def _from_proc(name, proc):
    found = []
    try:
        entries = list(Path(proc).iterdir())
    except OSError:
        return None
    me = str(os.getpid())
    for entry in entries:
        if not entry.name.isdigit() or entry.name == me:
            continue
        try:
            raw = (entry / "cmdline").read_bytes()
        except OSError:
            continue  # gone since the listing, or not ours to read
        argv = [part.decode("utf-8", "replace")
                for part in raw.split(b"\0") if part]
        if argv and _is_program(argv[0], name):
            found.append(argv)
    return found


def _from_ps(name, run):
    """Two listings joined by pid: ``comm`` is the program's path, which may
    hold spaces (``Visual Studio Code.app``); ``args`` is the whole line."""
    try:
        programs = _ps_column(run, "pid=,comm=")
        lines = _ps_column(run, "pid=,args=")
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    found = []
    for pid, program in programs.items():
        if pid == os.getpid() or not _is_program(program, name):
            continue
        line = lines.get(pid, program)
        rest = line[len(program):] if line.startswith(program) else ""
        found.append([program, *rest.split()])
    return found


def _ps_column(run, columns):
    done = run(["ps", "-axww", "-o", columns], capture_output=True, text=True,
               timeout=PS_TIMEOUT_S)
    if done.returncode != 0:
        raise ValueError("ps failed")
    table = {}
    for line in done.stdout.splitlines():
        pid, _, value = line.strip().partition(" ")
        if pid.isdigit():
            table[int(pid)] = value.strip()
    return table


def _is_program(path, name) -> bool:
    base = path.replace("\\", "/").rsplit("/", 1)[-1]
    if base.lower().endswith(".exe"):
        base = base[:-4]
    return base == name


def binary(provider) -> str:
    return provider.login_binary()


def available(provider) -> bool:
    """Whether this provider's login command can be run at all.

    Probed rather than assumed: offering a provider whose CLI is absent means
    the user only finds out at the moment they expected a browser.
    """
    return shutil.which(provider.login_binary()) is not None


def command(provider, *, email: str | None = None,
            device: bool = False) -> list[str]:
    """The vendor's login argv, optionally pre-filling a known address.

    A provider that declares no ``email_flag`` gets no address rather than a
    guessed flag name. ``device`` asks for the sign-in with a one-time code
    entered on another device, and only a provider whose spec describes one
    (:func:`accepts_device_auth`) can give it.
    """
    argv = provider.login_command()
    if device:
        argv = argv + [_device_rules(provider)["flag"]]
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
CODE_IS_ADDRESS = ("That's the page address, not the code. Copy the code "
                   "shown on the page.")
CODE_IS_LOCAL_ADDRESS = ("That address only works in a browser on this "
                         "machine. Open the link above instead, and paste the "
                         "code its last page shows.")
CODE_IS_VERIFICATION = ("That's a verification code. Paste the code shown on "
                        "the page after you sign in.")

#: Claude Code 2.1.330's own tests (``GRe``), anywhere in the paste: a web
#: address, a ``/magic-link#``, and an address on this machine.
_WEB = re.compile(r"https?://|/magic-link#", re.IGNORECASE)
_LOCAL = re.compile(r"https?://(?:localhost|127\.0\.0\.1|\[::1\])[:/]",
                    re.IGNORECASE)

#: An address without its scheme, which 2.1.330 would take for a code and
#: fail on: localhost, or a dotted host followed by a port, a path or a
#: query. Matched from the start of the part before any '#'. A real code has
#: no '/' or ':' there, so a dot alone (``abc.def``) is never taken for one.
_BARE_LOCAL = re.compile(r"(?:localhost|127\.0\.0\.1|\[::1\])(?![A-Za-z0-9_-])",
                         re.IGNORECASE)
_BARE_HOST = re.compile(
    r"[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::[0-9]+)?[/?]"
    r"|[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+:[0-9]+")

#: The short number an email or text message gives, pasted on its own; as
#: 2.1.330 does, spaces and dashes inside it ("123-456") do not count.
_VERIFICATION = re.compile(r"[0-9]{4,10}")


def _address_reason(text: str) -> str | None:
    """Which address reason fits ``text``, if it is an address at all."""
    head = text.partition("#")[0]
    if _LOCAL.search(text) or _BARE_LOCAL.match(head):
        return CODE_IS_LOCAL_ADDRESS
    if _WEB.search(text) or _BARE_HOST.match(head):
        return CODE_IS_ADDRESS
    return None

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
    # What the vendor itself refuses, refused here first with the reason:
    # its own would reach the window only as hidden output.
    refuses = set(rules.get("refuses") or ())
    if "address" in refuses:
        reason = _address_reason(text)
        if reason:
            raise CodeRejectedError(reason)
    if "verification_code" in refuses and _VERIFICATION.fullmatch(
            re.sub(r"[\s-]", "", text)):
        raise CodeRejectedError(CODE_IS_VERIFICATION)
    separator = rules.get("separator")
    if separator:
        # The vendor's own rule: both halves present, or it prints "Invalid
        # code" where only it can see it and goes on waiting.
        head, found, tail = text.partition(separator)
        if not (head and found and tail):
            raise CodeRejectedError(CODE_INCOMPLETE)
    return text


# -- signing in with a code on another device -------------------------------

DEVICE_NOT_OFFERED = ("{binary} cannot sign in with a code from another "
                      "device. Sign in with the browser instead.")


def plain(line: str) -> str:
    """``line`` without terminal escape sequences.

    Codex colours its device prompt whether or not it is writing to a
    terminal, so the link and the code each arrive wrapped in escapes.
    """
    return _ESCAPE.sub("", line or "")


def _device_rules(provider) -> dict:
    rules = provider.spec.get("login", {}).get("device_auth")
    if not isinstance(rules, dict):
        raise LoginUnavailableError(
            DEVICE_NOT_OFFERED.format(binary=binary(provider)))
    return rules


def accepts_device_auth(provider) -> bool:
    """Whether this provider can sign in with a code entered elsewhere."""
    try:
        _device_rules(provider)
    except LoginUnavailableError:
        return False
    return True


@dataclass(frozen=True)
class DeviceCode:
    """What to show for a sign-in finished on another device."""

    user_code: str
    verification_url: str
    #: How long the vendor waits for the code to be entered.
    expires_in_s: int


class DeviceCodeReader:
    """Picks the link and the one-time code out of the vendor's output.

    By position, not by the English around them: the link is a line that is
    exactly the one the spec names, and the code is the first line after it
    that is nothing but a code. So no other address is ever offered as the
    place to enter it, and no other line is shown as the code.
    """

    def __init__(self, provider):
        rules = _device_rules(provider)
        self._link = rules["verification_url"]
        self._code = re.compile(rules["code_pattern"])
        self._expires_in_s = int(rules.get("expires_in_s") or 0)
        self._after_link = False
        self._found = False

    def feed(self, line: str) -> DeviceCode | None:
        """The code, from the line that completes it; otherwise None."""
        if self._found:
            return None
        text = plain(line).strip()
        if not self._after_link:
            self._after_link = text == self._link
            return None
        if not self._code.fullmatch(text):
            return None
        self._found = True
        return DeviceCode(user_code=text, verification_url=self._link,
                          expires_in_s=self._expires_in_s)


def known_message(provider, line: str) -> str | None:
    """Which of the vendor's fixed device sign-in messages ``line`` holds.

    Returns the spec's name for it, never text from the line: what a
    frontend shows is the spec's own copy of the sentence.
    """
    rules = provider.spec.get("login", {}).get("device_auth") or {}
    text = plain(line)
    for key, sentence in (rules.get("messages") or {}).items():
        if sentence and sentence in text:
            return key
    return None


def device_message(provider, key: str) -> str | None:
    """The spec's copy of the vendor's fixed message ``key``."""
    rules = provider.spec.get("login", {}).get("device_auth") or {}
    return (rules.get("messages") or {}).get(key)


def device_setting(provider) -> str:
    """What has to be switched on for this provider's device sign-in."""
    rules = provider.spec.get("login", {}).get("device_auth") or {}
    return rules.get("setting") or ""


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


#: Whether a cancel ends the vendor's whole process tree. Windows only: on
#: POSIX the vendor is the process Shambles started (the native binary, or
#: node for an npm install, and Codex's npm launcher forwards SIGTERM to its
#: native binary), while a new process group to kill would also change how
#: Ctrl+C in a terminal reaches it.
KILL_TREE = sys.platform == "win32"

#: Keeps taskkill from flashing a console window over a windowed Shambles.
_NO_WINDOW = ({"creationflags": subprocess.CREATE_NO_WINDOW}
              if sys.platform == "win32" else {})


def _taskkill(which=shutil.which) -> str | None:
    """Windows' own taskkill, from PATH or else from the system folder."""
    found = which("taskkill")
    if found:
        return found
    root = os.environ.get("SystemRoot") or os.environ.get("windir")
    if root:
        candidate = os.path.join(root, "System32", "taskkill.exe")
        if os.path.isfile(candidate):
            return candidate
    return None


def kill_tree(pid, *, timeout: float, run=subprocess.run,
              which=shutil.which) -> bool:
    """End process ``pid`` and every process under it. Windows only.

    ``pid`` is always Shambles' own child, which it still holds a handle to,
    so Windows cannot have reused the number for anything else. ``/F`` is as
    forceful as the ``TerminateProcess`` that ``Popen.terminate()`` uses;
    Windows has nothing gentler to send a console program it did not start
    in a group of its own. Returns whether taskkill said it succeeded, and
    never raises: the caller falls back to ``terminate()``.
    """
    exe = _taskkill(which)
    if exe is None:
        return False
    try:
        result = run([exe, "/F", "/T", "/PID", str(int(pid))],
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, timeout=timeout, **_NO_WINDOW)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return getattr(result, "returncode", 1) == 0


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
                # terminal would change what it does: it would always wrap
                # the sign-in link in hyperlink escapes and colour (through
                # a pipe, only when the environment suggests a terminal that
                # shows them; find_url strips them either way), and it would
                # start reading keystrokes in raw mode.
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

        On Windows the process Shambles started is often not the vendor:
        npm installs a ``.cmd`` shim, so it is ``cmd.exe`` with the vendor
        as its child, and ``terminate()`` ends ``cmd.exe`` alone. There the
        whole tree under that one child ends instead (:func:`kill_tree`),
        with ``terminate()`` as the fallback.
        """
        self._cancelled = True
        if self._process is None or self._process.poll() is not None:
            return
        if KILL_TREE and kill_tree(self._process.pid, timeout=grace):
            try:
                self._process.wait(timeout=grace)
                return
            except subprocess.TimeoutExpired:
                pass
        self._process.terminate()
        try:
            self._process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self._process.kill()
