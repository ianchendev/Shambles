"""Reading usage figures cached by Claude Code and Codex.

Claude Code stores both windows in ``~/.claude.json``. Codex writes the
same 5h / week pair onto ``token_count`` events in ``~/.codex/sessions``.

**Display only.** These figures are never written back into ``~/.claude.json``
-- see ``stale_on_switch`` in ``providers/claude.json`` for why restoring a
cached copy misleads the extension. A profile's stashed usage is kept solely so the
window can show what an idle account looked like when you left it, always
labelled with its age.
"""

import datetime
import json
from dataclasses import dataclass
from pathlib import Path

from . import configjson
from .providers.spec import finite

#: ``kind`` values in the cache's ``limits`` array, mapped to a short label.
#: ``weekly_all`` is the whole-week bucket; the per-model ones are ignored
#: because a row has space for two numbers, not six.
KINDS = {"session": "session", "weekly_all": "week"}

#: Claude Code's own severity strings, mapped onto the chip palette already
#: used for token expiry. Anything unrecognised is treated as the worst case,
#: since a new severity is far more likely to mean trouble than not.
SEVERITY = {"normal": "ok", "warning": "soon"}
SEVERITY_FALLBACK = "gone"

#: Beyond this a stashed figure is too old to show without qualification.
STALE_AFTER_MS = 60 * 60 * 1000

#: A bar goes red at or above this percentage, matching the VS Code
#: extension's own meter so the two never disagree on screen. This is a floor,
#: not a replacement for Claude Code's severity: a bucket it flags below the
#: threshold still renders amber rather than being painted normal.
RED_AT = 80


def bar_severity(percent, claude_severity) -> str:
    """Colour key for a bar, from its value and Claude Code's own verdict.

    ``claude_severity`` is the raw string out of the cache -- "normal",
    "warning" -- not an already-mapped colour key.
    """
    try:
        if float(percent) >= RED_AT:
            return "gone"
    except (TypeError, ValueError):
        return SEVERITY_FALLBACK
    return SEVERITY.get(claude_severity, SEVERITY_FALLBACK)


def fill_fraction(percent) -> float:
    """How much of the track to fill, clamped to 0..1.

    Usage can exceed 100 once an account is over quota; the bar saturates
    rather than drawing past its own width.
    """
    try:
        return max(0.0, min(1.0, float(percent) / 100.0))
    except (TypeError, ValueError):
        return 0.0


@dataclass(frozen=True)
class Bar:
    """One usage bucket, ready to render.

    ``severity`` is Claude Code's own raw verdict. The colour actually drawn
    comes from :attr:`display_severity`, which applies the 80% floor on top.
    """
    label: str
    percent: int
    severity: str | None = None
    resets_at: str | None = None

    @property
    def display_severity(self) -> str:
        return bar_severity(self.percent, self.severity)

    @property
    def fill(self) -> float:
        return fill_fraction(self.percent)

    def resets_label(self) -> str | None:
        """``resets_at`` as something a person can read, or None."""
        if not self.resets_at:
            return None
        try:
            when = datetime.datetime.fromisoformat(self.resets_at)
            # The move to local time can fail on its own: an instant on the
            # calendar's last day is a real one in UTC and off the end east
            # of it.
            return when.astimezone().strftime("%a %d %b, %H:%M")
        except (TypeError, ValueError, OverflowError, OSError):
            return None


@dataclass(frozen=True)
class Usage:
    bars: tuple
    fetched_at_ms: int | None = None

    def __bool__(self) -> bool:
        return bool(self.bars)

    def age_ms(self, now_ms: int) -> int | None:
        if self.fetched_at_ms is None:
            return None
        return max(0, now_ms - self.fetched_at_ms)

    def is_stale(self, now_ms: int) -> bool:
        age = self.age_ms(now_ms)
        return age is not None and age > STALE_AFTER_MS

    def age_label(self, now_ms: int) -> str | None:
        """Short human age, e.g. ``"17h ago"``. None when freshly fetched."""
        return age_words(self.age_ms(now_ms))


def age_words(age_ms) -> str | None:
    """An age in milliseconds as ``"just now"``, ``"40m ago"``, ``"17h ago"``."""
    if age_ms is None:
        return None
    minutes = max(0, age_ms) // 60_000
    if minutes < 60:
        return "just now" if minutes < 5 else f"{minutes}m ago"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h ago"
    return f"{hours // 24}d ago"


#: Under this, a reset time reads as a countdown ("in 1h 52m"), which is what
#: someone choosing an account needs. Further off, the date says more.
COUNTDOWN_UNDER_MS = 24 * 60 * 60 * 1000

DATE_FORMAT = "%a %d %b, %H:%M"


def has_reset(resets_at_ms, now_ms: int) -> bool:
    """Whether a limit's window has rolled over since it was read.

    The figure was true until ``resets_at_ms``; after it the limit starts
    again from nothing, so an old 100% must not be shown as a full limit. An
    unknown reset time has not passed: there is nothing to say it has.
    """
    return (isinstance(resets_at_ms, int) and not isinstance(resets_at_ms, bool)
            and resets_at_ms <= now_ms)


def until_label(resets_at_ms, now_ms: int) -> str | None:
    """``"in 1h 52m"`` for a reset under a day away, else None.

    Rounded up: the last seconds before a reset read "in 1m", never "in 0m"
    beside a figure that has not reset yet.
    """
    if not isinstance(resets_at_ms, int) or isinstance(resets_at_ms, bool):
        return None
    left = resets_at_ms - now_ms
    if left <= 0 or left >= COUNTDOWN_UNDER_MS:
        return None
    minutes = -(-left // 60_000)
    hours, minutes = divmod(minutes, 60)
    if not hours:
        return f"in {minutes}m"
    return f"in {hours}h {minutes}m" if minutes else f"in {hours}h"


def date_label(ms) -> str:
    """``ms`` as a local date and time, or ``""`` if no calendar reaches it."""
    try:
        return datetime.datetime.fromtimestamp(ms / 1000).strftime(DATE_FORMAT)
    except (TypeError, ValueError, OverflowError, OSError):
        return ""


def moment_label(ms, now_ms: int) -> str:
    """A moment in local time: ``"14:00"`` if it is today, else with its day.

    ``""`` for a value no calendar reaches. Both numbers are whatever the
    vendor cached, never range-checked.
    """
    try:
        when = datetime.datetime.fromtimestamp(ms / 1000)
        today = datetime.datetime.fromtimestamp(now_ms / 1000).date()
    except (TypeError, ValueError, OverflowError, OSError):
        return ""
    if when.date() == today:
        return when.strftime("%H:%M")
    return when.strftime(DATE_FORMAT)


EMPTY = Usage(bars=())


def parse(blob) -> Usage:
    """Read a ``cachedUsageUtilization`` blob into renderable bars.

    Prefers the ``limits`` array, which carries Claude Code's own ``severity``.
    Falls back to the ``utilization`` buckets when it is missing, deriving no
    severity of its own -- an unknown severity renders as the worst case rather
    than inventing a threshold that could disagree with the extension.
    """
    if not isinstance(blob, dict):
        return EMPTY

    fetched = blob.get("fetchedAtMs")
    fetched = fetched if finite(fetched) else None
    util = blob.get("utilization")
    if not isinstance(util, dict):
        return Usage(bars=(), fetched_at_ms=int(fetched) if fetched else None)

    found = {}
    for entry in util.get("limits") or []:
        if not isinstance(entry, dict):
            continue
        label = KINDS.get(entry.get("kind"))
        percent = entry.get("percent")
        if label is None or not finite(percent):
            continue
        found[label] = Bar(
            label=label,
            percent=int(percent),
            severity=entry.get("severity"),
            resets_at=entry.get("resets_at"),
        )

    # Older caches, or any future shape without `limits`.
    for key, label in (("five_hour", "session"), ("seven_day", "week")):
        if label in found:
            continue
        bucket = util.get(key)
        if not isinstance(bucket, dict):
            continue
        percent = bucket.get("utilization")
        if not finite(percent):
            continue
        # No `limits` entry means no severity to trust, so the value alone
        # decides: red past the threshold, otherwise unremarkable.
        found[label] = Bar(label=label, percent=int(percent), severity="normal",
                           resets_at=bucket.get("resets_at"))

    order = [lbl for lbl in ("session", "week") if lbl in found]
    return Usage(bars=tuple(found[lbl] for lbl in order),
                 fetched_at_ms=int(fetched) if fetched else None)


#: Codex's 5-hour window is 300 minutes. Anything in this band is "session"
#: (shown as 5h); longer windows are the week.
_CODEX_SESSION_MAX_MINUTES = 12 * 60
_CODEX_TAIL_BYTES = 256 * 1024


def parse_codex_rate_limits(limits, *, fetched_at_ms: int | None = None) -> Usage:
    """Turn a Codex ``rate_limits`` object into the same bars Claude uses.

    Codex does not keep a companion usage cache. It does write the live 5h
    and weekly windows onto ``token_count`` events in the session jsonl
    under ``~/.codex/sessions``. Primary is the short window, secondary the
    week. Labels stay ``session`` / ``week`` so the snapshot contract is
    one shape for every provider.
    """
    if not isinstance(limits, dict):
        return EMPTY
    found = {}
    for key in ("primary", "secondary"):
        bucket = limits.get(key)
        if not isinstance(bucket, dict):
            continue
        percent = bucket.get("used_percent")
        minutes = bucket.get("window_minutes")
        if not finite(percent):
            continue
        label = "session" if (
            isinstance(minutes, (int, float)) and minutes <= _CODEX_SESSION_MAX_MINUTES
        ) else "week"
        found[label] = Bar(
            label=label,
            percent=int(percent),
            severity="normal",
            resets_at=_codex_resets_at(bucket.get("resets_at")),
        )
    order = [lbl for lbl in ("session", "week") if lbl in found]
    return Usage(bars=tuple(found[lbl] for lbl in order), fetched_at_ms=fetched_at_ms)


def read_codex_usage(config_dir: Path, *, log: Path | None = None) -> Usage:
    """Latest 5h / week figures from the newest Codex session log.

    Local files only — the same discipline as Claude's
    ``cachedUsageUtilization``. A session that never emitted ``rate_limits``
    returns empty, which the UI already treats as a supported state.
    ``log`` is that newest log, for a caller that has already walked for it.
    """
    path = log if log is not None else latest_codex_session(config_dir)
    if path is None:
        return EMPTY
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            if size > _CODEX_TAIL_BYTES:
                handle.seek(size - _CODEX_TAIL_BYTES)
            raw = handle.read()
    except OSError:
        return EMPTY
    text = raw.decode("utf-8", errors="replace")
    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line or "rate_limits" not in line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        payload = event.get("payload") if isinstance(event, dict) else None
        if not isinstance(payload, dict):
            continue
        limits = payload.get("rate_limits")
        if not isinstance(limits, dict):
            continue
        parsed = parse_codex_rate_limits(
            limits, fetched_at_ms=_ms_from_timestamp(event.get("timestamp")))
        if parsed:
            return parsed
    return EMPTY


def codex_reading_since(config_dir: Path, since_ms: int | None, *,
                        log: Path | None = None) -> Usage:
    """The newest Codex reading, if it was taken at or after ``since_ms``.

    Codex writes its windows onto session logs that every account shares, so
    the newest one says nothing about whose figures they are. Taken before
    the account in use became so, it is the previous account's, and EMPTY
    comes back instead. A reading with no time of its own cannot be placed
    and is treated the same way. ``since_ms`` of None asks for any reading.
    ``log`` is as for :func:`read_codex_usage`.
    """
    reading = read_codex_usage(config_dir, log=log)
    if since_ms is None:
        return reading
    if not reading or reading.fetched_at_ms is None \
            or reading.fetched_at_ms < since_ms:
        return EMPTY
    return reading


def keep_codex_reading(paths, provider, name, *, log=None) -> bool:
    """Keep ``name``'s newest Codex reading beside its login; True if written.

    Codex keeps no usage cache of its own, so this is the only record a
    parked Codex row has. Only a reading taken since the marker named
    ``name``, and only while it does: the session logs are shared, and an
    older reading was written by whoever was signed in before. A reading the
    same as the one kept is not written again, and an older one never
    replaces it: resuming an old session makes its log the newest while the
    last reading on it is older.

    Best effort, and never raises: losing a reading costs a blank bar.
    ``log`` is as for :func:`read_codex_usage`.
    """
    from . import state
    from .errors import ShamblesError
    from .providers import spec as specmod
    try:
        if (provider.id != "codex"
                or state.read_active(paths, provider.id) != name):
            return False
        since = state.marked_since_ms(paths, provider.id)
        if since is None:
            return False  # the marker went meanwhile: nothing to date it by
        reading = codex_reading_since(
            specmod.config_dir(provider.spec, home=paths.home,
                               env=getattr(provider, "env", None)),
            since, log=log)
        if not reading:
            return False
        where = paths.usage(provider.id, name)
        kept = configjson.load(where)
        before = kept.get("fetchedAtMs")
        if isinstance(before, int) and before > reading.fetched_at_ms:
            return False
        fresh = to_cache(reading)
        if kept == fresh:
            return False
        configjson.write_atomic(where, fresh)
        return True
    except (OSError, ShamblesError):
        return False


def capture_codex(paths, provider, *, platform, log=None) -> bool:
    """Keep the Codex account in use's newest reading, as :func:`capture_live`
    does for Claude. True if written.

    Without this a reading was kept only at a switch made in Shambles. An
    account left any other way, signed out of in the Codex extension or
    replaced by ``codex login``, kept nothing, and the account in use showed
    nothing while its newest session had no reading on it yet.

    Only while the live login provably is the marked account's, by its bytes
    or its lineage. Signed in as somebody else outside Shambles, the marker
    stays put, and their readings are taken after it moved. ``provider``'s
    store is read for that, so a caller running unprompted passes one that
    reads files only.
    """
    from . import state
    from .errors import ShamblesError
    if provider.id != "codex":
        return False
    try:
        name = state.read_active(paths, provider.id)
        if not name or state.owner_of_live(
                paths, provider, platform=platform) != name:
            return False
    except (OSError, ShamblesError):
        return False
    return keep_codex_reading(paths, provider, name, log=log)


#: Bar labels back to the cache's ``limits`` kinds. See :data:`KINDS`.
_CACHE_KINDS = {label: kind for kind, label in KINDS.items()}


def to_cache(usage: Usage) -> dict:
    """``usage`` in the shape :func:`parse` reads back: Claude's cache.

    One shape for every kept reading, so a parked Codex row is read exactly
    as a parked Claude one.
    """
    return {
        "fetchedAtMs": usage.fetched_at_ms,
        "utilization": {"limits": [
            {"kind": _CACHE_KINDS[bar.label], "percent": bar.percent,
             "severity": bar.severity, "resets_at": bar.resets_at}
            for bar in usage.bars if bar.label in _CACHE_KINDS]},
    }


def latest_codex_session(config_dir: Path) -> Path | None:
    """The newest session log under ``config_dir``, or None. Walks the tree,
    so a caller polling for changes should keep the answer, not ask again."""
    sessions = Path(config_dir) / "sessions"
    if not sessions.is_dir():
        return None
    newest = None
    newest_mtime = -1.0
    for path in sessions.rglob("*.jsonl"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        if mtime >= newest_mtime:
            newest_mtime = mtime
            newest = path
    return newest


def _codex_resets_at(value) -> str | None:
    if isinstance(value, (int, float)):
        if not finite(value):
            return None
        try:
            return datetime.datetime.fromtimestamp(
                value, tz=datetime.timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None  # a number, but not one any calendar reaches
    if isinstance(value, str):
        return value
    return None


def _ms_from_timestamp(value) -> int | None:
    if not isinstance(value, str):
        return None
    try:
        when = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return int(when.timestamp() * 1000)


def capture_live(paths, provider_id, active_name, *, now_ms,
                 provider=None) -> bool:
    """Record the active account's live figures into its own profile.

    Without this a profile only learns its usage at the moment you switch
    away, so the account you are actually using is the one guaranteed to show
    nothing -- exactly backwards. Called on every window refresh, so it writes
    only when the figure has actually moved.

    Refuses a blob whose ``accountUuid`` does not match the profile's stored
    identity: ``~/.claude.json`` can still hold the previous account's cache in
    the moments after a switch, and attributing that to this profile would be
    the same class of mistake as restoring it.
    """
    if not active_name:
        return False

    # The profile's own sidecar first. It is a few hundred bytes, and without
    # an account in it nothing below can match -- which is every profile of a
    # provider with no companion file. ~/.claude.json is the largest file
    # Shambles reads, and this runs for every provider on every refresh.
    sidecar = configjson.load(paths.account(provider_id, active_name))
    account = sidecar.get("oauthAccount")
    expected = account.get("accountUuid") if isinstance(account, dict) else None
    if not expected:
        return False

    if provider is None:
        from .providers import load
        provider = load(provider_id)
    source = provider.companion_path(home=paths.home)
    if source is None:
        return False
    config = configjson.load(source)
    live = config.get("cachedUsageUtilization")
    if not isinstance(live, dict) or live.get("accountUuid") != expected:
        return False
    # accountUuid is the person, not the organisation: one person in two
    # organisations has two logins and two sets of figures.
    mine = account.get("organizationUuid")
    theirs = (config.get("oauthAccount") or {}).get("organizationUuid")
    if mine and theirs and mine != theirs:
        return False

    if sidecar.get("usage") == live:
        return False

    sidecar["usage"] = live
    try:
        configjson.write_atomic(paths.account(provider_id, active_name), sidecar)
    except OSError:
        # Display only, and called while the window draws. A sidecar that
        # cannot be written this time is a figure recorded next time.
        return False
    return True
