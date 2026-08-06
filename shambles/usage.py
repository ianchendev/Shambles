"""Reading the usage figures Claude Code caches in ``~/.claude.json``.

Two numbers matter to someone deciding which account to switch to: how much of
the current session window is gone, and how much of the week. Claude Code
already computes both, along with a severity it derives itself, so this module
reads rather than judges.

**Display only.** These figures are never written back into ``~/.claude.json``
-- see :data:`shambles.configjson.STALE_ON_SWITCH` for why restoring a cached
copy misleads the extension. A profile's stashed usage is kept solely so the
window can show what an idle account looked like when you left it, always
labelled with its age.
"""

import datetime
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Bar:
    """One usage bucket, ready to render."""
    label: str
    percent: int
    severity: str
    resets_at: str | None = None

    def resets_label(self) -> str | None:
        """``resets_at`` as something a person can read, or None."""
        if not self.resets_at:
            return None
        try:
            when = datetime.datetime.fromisoformat(self.resets_at)
        except ValueError:
            return None
        return when.astimezone().strftime("%a %d %b, %H:%M")


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
        age = self.age_ms(now_ms)
        if age is None:
            return None
        minutes = age // 60_000
        if minutes < 60:
            return "just now" if minutes < 5 else f"{minutes}m ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours}h ago"
        return f"{hours // 24}d ago"


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
    fetched = fetched if isinstance(fetched, (int, float)) else None
    util = blob.get("utilization")
    if not isinstance(util, dict):
        return Usage(bars=(), fetched_at_ms=int(fetched) if fetched else None)

    found = {}
    for entry in util.get("limits") or []:
        if not isinstance(entry, dict):
            continue
        label = KINDS.get(entry.get("kind"))
        percent = entry.get("percent")
        if label is None or not isinstance(percent, (int, float)):
            continue
        found[label] = Bar(
            label=label,
            percent=int(percent),
            severity=SEVERITY.get(entry.get("severity"), SEVERITY_FALLBACK),
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
        if not isinstance(percent, (int, float)):
            continue
        found[label] = Bar(label=label, percent=int(percent),
                           severity=SEVERITY_FALLBACK,
                           resets_at=bucket.get("resets_at"))

    order = [lbl for lbl in ("session", "week") if lbl in found]
    return Usage(bars=tuple(found[lbl] for lbl in order),
                 fetched_at_ms=int(fetched) if fetched else None)
