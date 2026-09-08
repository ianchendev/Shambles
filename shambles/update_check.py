"""The one place Shambles may talk to the internet, and only when told to.

Everything else in this package moves files around on one machine. That is the
security claim the README makes and
``tests/test_login.py::test_the_package_imports_no_networking_module`` enforces
with an AST scan over every module. This file is the single exemption: when
``update.check`` is on it asks the public GitHub Releases API for one tag,
compares it with the running version, and hands back a sentence to print. It
never downloads anything and never replaces the binary -- saying that a newer
release exists is the whole of the feature.

Three rules shape everything below:

* **Off by default.** With the setting unset, :func:`check_for_update` returns
  before ``fetch`` is so much as looked at, so an unconfigured install makes no
  request at all. Nothing else in here runs either.
* **One lookup a day**, remembered in ``~/.shambles/update-cache.json`` as a
  tag and a timestamp. Nothing account-shaped goes near that file, and a failed
  attempt counts as the day's attempt so an offline machine is not made to sit
  through a connection timeout on every invocation.
* **Silence on failure.** A rate limit, a captive portal, a DNS hiccup, a
  half-written cache or a tag nobody can order all come back as "no notice".
  A version check is not worth interrupting anybody over, and it is certainly
  not worth a traceback.

``urllib`` is imported inside :func:`fetch_latest_tag`'s body rather than at
module scope, so ``import shambles`` -- which the GUI, the TUI and the CLI all
do -- never pulls a networking stack into the process, whatever the setting
says.
"""

import json
from dataclasses import dataclass

from . import configjson, settings

#: The public Releases endpoint. Unauthenticated, so it carries no identity of
#: any kind: no token, no account, no machine ID, no query string.
RELEASES_URL = "https://api.github.com/repos/ianchendev/Shambles/releases/latest"

CACHE_NAME = "update-cache.json"

#: One lookup per day, per the design's privacy budget.
TTL_S = 86_400

#: Per socket operation, not per lookup: ``urlopen`` applies it separately to
#: the name resolution, the connect and each read, so the wall-clock worst
#: case is a small multiple of this. Nothing waits on a lookup any more --
#: ``--version`` reads the cache and the TUI checks in a worker -- but a
#: background thread still has to end, and an endpoint that cannot answer a
#: two-second read has already spent the day's attempt as far as anybody
#: looking at the screen is concerned.
TIMEOUT_S = 2.0

#: A release description is a few kilobytes. Reading a bounded amount means a
#: misdirected or hostile endpoint cannot answer with a stream.
MAX_BYTES = 1 << 20

#: CPython will not parse an int from more than 4300 digits, and a release
#: segment is never more than a handful. Anything longer is not a version.
MAX_SEGMENT_DIGITS = 9

#: The notice, in full. It names the install script and nothing else: that is
#: the route the README leads with, and it is the only one that works today.
#: An npm package is designed but unpublished, so telling somebody to run
#: ``npm i -g shambles`` would be handing them a command that fails -- and a
#: version notice that lies about how to act on it is worse than none.
NOTICE = ("Shambles {latest} is available (you have {current}). "
          "Re-run the install script to update.")


@dataclass(frozen=True)
class UpdateStatus:
    """What one check found, in a shape a caller can render without thinking.

    ``enabled`` is separate from ``newer`` on purpose: "checks are off" and
    "checks are on and there is nothing to report" look identical from the
    ``message`` alone, and the CLI's ``config get`` needs to tell them apart.
    ``latest`` is the tag with its release ``v`` removed, so one spelling
    reaches the cache, the status and the notice.
    """

    enabled: bool
    current: str
    latest: str | None
    newer: bool
    message: str | None


def fetch_latest_tag(url: str) -> dict:
    """GET one release description from GitHub.

    Deliberately dumb: no auth, no added headers, one short timeout, a bounded
    read. Every failure is handled identically one level up, so there is
    nothing worth catching here.

    ``urllib`` is imported in this body rather than at module scope -- see the
    module docstring. It is the only networking import the package's AST gate
    allows anywhere.
    """
    import urllib.request

    with urllib.request.urlopen(url, timeout=TIMEOUT_S) as response:
        return json.loads(response.read(MAX_BYTES).decode("utf-8"))


def check_for_update(paths, *, current_version: str, now_s: float,
                     fetch=fetch_latest_tag) -> UpdateStatus:
    """Whether a newer release exists, and the one line to say about it.

    The clock and the fetch are arguments rather than ambient facts so the
    24-hour budget and the failure paths can be tested without a network or a
    wait.
    """
    if not settings.update_check_enabled(paths):
        return UpdateStatus(enabled=False, current=current_version,
                            latest=None, newer=False, message=None)

    checked_at, latest = _read_cache(paths)
    if not _fresh(checked_at, now_s):
        found = _lookup(fetch)
        # A failed lookup still spends the day's attempt, but it does not
        # forget the tag the last successful one found: the notice should not
        # blink out because the network went away.
        latest = latest if found is None else found
        _write_cache(paths, now_s, latest)

    newer = bool(latest) and _is_newer(latest, current_version)
    message = (NOTICE.format(latest=latest, current=current_version)
               if newer else None)
    return UpdateStatus(enabled=True, current=current_version, latest=latest,
                        newer=newer, message=message)


def notice_from_cache(paths, *, current_version: str) -> str | None:
    """The notice an earlier lookup already earned, without doing another.

    ``--version`` is what a script runs to ask whether the install worked, and
    :data:`TIMEOUT_S` bounds one socket operation rather than the whole
    lookup, so putting :func:`check_for_update` in front of it would let a
    captive portal hold up an install check for as long as DNS, connect and
    read take to each give up in turn. This path therefore only reads: no
    fetch, no restamping, not even a ``mkdir``. There is no ``fetch``
    parameter because there is nothing here that could use one.

    Staleness is deliberately not consulted. Age decides when it is time to
    look again, which this never does; a tag from last week is still the
    newest release anybody here knows about, and going quiet on it would make
    the notice blink in and out depending on which command ran last.
    """
    if not settings.update_check_enabled(paths):
        return None
    _, latest = _read_cache(paths)
    if not latest or not _is_newer(latest, current_version):
        return None
    return NOTICE.format(latest=latest, current=current_version)


def _lookup(fetch) -> str | None:
    """The tag GitHub reports, or ``None`` if anything at all went wrong.

    Broad on purpose. ``fetch`` reaches a network: it can raise ``URLError``,
    ``HTTPError``, a timeout, a decoding error, or whatever a future opener
    adds, and an answer shaped like a rate-limit message rather than a release
    is just as likely. None of that is a reason to take the program down.
    ``BaseException`` still propagates, so Ctrl-C is still Ctrl-C.
    """
    try:
        payload = fetch(RELEASES_URL)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    tag = payload.get("tag_name")
    return _tag_text(tag) if isinstance(tag, str) else None


def _read_cache(paths) -> tuple[float | None, str | None]:
    """When the last lookup happened and what it saw.

    Each field is validated on its own, so a cache that is missing, truncated,
    hand-edited or written by some later version still yields whatever part of
    it makes sense instead of raising. ``True`` is not a timestamp, however
    much of an ``int`` Python considers it.
    """
    cached = configjson.load(paths.library_dir / CACHE_NAME)
    checked_at = cached.get("checked_at")
    latest = cached.get("latest")
    stamped = (isinstance(checked_at, (int, float))
               and not isinstance(checked_at, bool))
    return (checked_at if stamped else None,
            latest if isinstance(latest, str) else None)


def _write_cache(paths, now_s: float, latest: str | None) -> None:
    """Record the attempt: a timestamp and a tag, and nothing else, ever."""
    try:
        paths.ensure_store()
        configjson.write_atomic(paths.library_dir / CACHE_NAME,
                                {"checked_at": now_s, "latest": latest})
    except OSError:
        pass  # An unwritable cache costs a lookup, not a working program.


def _fresh(checked_at: float | None, now_s: float) -> bool:
    """Whether a lookup that recent counts as today's.

    A stamp in the future -- a clock correction, a home directory copied off
    another machine -- reads as stale rather than fresh, or the check would
    wedge until the machine caught up with its own cache.
    """
    if checked_at is None:
        return False
    return 0 <= now_s - checked_at < TTL_S


def _tag_text(tag: str) -> str | None:
    """A release tag as it should be shown: no whitespace, no leading ``v``."""
    text = tag.strip()
    text = text[1:] if text[:1] in ("v", "V") else text
    return text or None


def _is_newer(latest: str, current: str) -> bool:
    """Whether ``latest`` names a later release than ``current``.

    Both are padded to the same number of segments first: ``2.1`` and ``2.1.0``
    are the same release, but ``(2, 1)`` and ``(2, 1, 0)`` do not compare that
    way. Segment-wise comparison is also what makes ``2.10`` later than
    ``2.9``, which no amount of string comparison would.
    """
    left, right = _release_number(latest), _release_number(current)
    if left is None or right is None:
        return False
    width = max(len(left), len(right))
    return _padded(left, width) > _padded(right, width)


def _release_number(text: str) -> tuple[int, ...] | None:
    """A dotted release number as integers, or ``None`` if it is not one.

    Only digits and dots order reliably under the rule above, so a prerelease
    (``2.1.0-rc1``), a moving tag (``nightly``) or anything else hand-made is
    unorderable -- and unorderable means no notice, because the one
    unacceptable answer is announcing an update that may not exist. Comparing
    those properly needs a version parser, and a version notice is not worth a
    dependency.

    All-digits is not enough on its own: ``int()`` refuses strings past
    :data:`MAX_SEGMENT_DIGITS`, so a very long run of digits is checked for
    length here rather than raising out of a caller that has no reason to
    expect it.
    """
    stripped = _tag_text(text)
    if stripped is None:
        return None
    parts = stripped.split(".")
    if not all(part.isdecimal() and len(part) <= MAX_SEGMENT_DIGITS
               for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _padded(numbers: tuple[int, ...], width: int) -> tuple[int, ...]:
    return numbers + (0,) * (width - len(numbers))
