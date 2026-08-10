"""Where quota figures come from, and why this layer is allowed to fail.

Both sources here are **by-products**, not interfaces. Claude Code writes
``cachedUsageUtilization`` into ``~/.claude.json`` for its own display; Codex
logs raw HTTP response headers into a debug database. Neither vendor promises
either will keep existing, and the Codex one is an internal log that could be
dropped in any release.

That volatility is the whole design constraint. **A usage source must never
raise.** Missing file, corrupt file, renamed field, changed schema — every one
of those returns ``None``, and ``None`` means the UI simply omits the figures.
Quota is a bonus; nothing about switching accounts may depend on it.

Neither source touches the network. Shambles reads what the vendor already
wrote to disk, so the "no network" property survives intact.
"""

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable

MS_PER_MINUTE = 60_000


@dataclass(frozen=True)
class UsageWindow:
    """One quota window, e.g. five hours or seven days.

    ``used_percent`` is ``None`` when the figure is known to be worthless --
    specifically when ``resets_at_ms`` has already passed, which proves the
    window rolled over since the number was recorded. Showing a stale
    percentage would be worse than showing nothing, because a user decides
    whether to switch accounts on the strength of it.
    """

    label: str
    used_percent: int | None
    resets_at_ms: int | None = None
    #: Recorded a while ago but still inside its window: display, de-emphasized.
    stale: bool = False


@dataclass(frozen=True)
class Usage:
    windows: list[UsageWindow]
    measured_at_ms: int | None = None
    #: Which by-product this came from, for diagnosis when it goes missing.
    source: str = ""


@runtime_checkable
class UsageSource(Protocol):
    def read(self, *, home, profile_dir, active: bool) -> Usage | None:
        """Quota for one profile, or ``None`` when unavailable for any reason."""


def _window(label, percent, resets_at_ms, now_ms, stale_after_ms=None,
            measured_at_ms=None) -> UsageWindow:
    """Build a window, blanking the percentage once its reset time has passed."""
    if resets_at_ms is not None and resets_at_ms <= now_ms:
        return UsageWindow(label, None, resets_at_ms)
    stale = bool(stale_after_ms and measured_at_ms
                 and now_ms - measured_at_ms > stale_after_ms)
    return UsageWindow(label, percent, resets_at_ms, stale)


def _load_json(path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _iso_to_ms(text) -> int | None:
    if not isinstance(text, str) or not text:
        return None
    from datetime import datetime, timezone
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp() * 1000)


class ClaudeUsageSource:
    """Claude Code's own cache, which carries both windows the UI wants.

    The cache is account-scoped and already travels with a switch, so a parked
    profile keeps whatever was current when it was last active. That makes the
    five-hour window near-useless for parked accounts -- five hours passes
    quickly, so its reset time will almost always have gone by and the figure
    blanks. The seven-day window survives a switch far more often.
    """

    STALE_AFTER_MS = 6 * 3_600_000

    def read(self, *, home, profile_dir, active: bool) -> Usage | None:
        try:
            source = (Path(home) / ".claude.json" if active
                      else Path(profile_dir) / "account.json")
            cached = _load_json(source).get("cachedUsageUtilization")
            if not isinstance(cached, dict):
                return None
            windows = cached.get("utilization")
            if not isinstance(windows, dict):
                return None

            measured = cached.get("fetchedAtMs")
            measured = measured if isinstance(measured, (int, float)) else None
            now_ms = _now_ms()

            found = []
            for key, label in (("five_hour", "5h"), ("seven_day", "7d")):
                block = windows.get(key)
                if not isinstance(block, dict):
                    continue
                percent = block.get("utilization")
                if not isinstance(percent, (int, float)):
                    continue
                found.append(_window(
                    label, int(percent), _iso_to_ms(block.get("resets_at")),
                    now_ms, self.STALE_AFTER_MS,
                    int(measured) if measured else None))

            if not found:
                return None
            return Usage(found, int(measured) if measured else None,
                         "claude.json")
        except Exception:
            # Deliberately broad. This is decoration; nothing it can raise is
            # worth failing a panel render over.
            return None


class CodexUsageSource:
    """Rate-limit response headers, recovered from Codex's own debug log.

    Codex never persists usage as data -- it reads ``x-codex-*`` headers off
    each API response, shows them live, and discards them. What it does do is
    log entire responses into ``logs_2.sqlite``, so the headers are recoverable
    without a network call.

    Two consequences the UI has to respect. There is **no five-hour window**;
    every observed ``window-minutes`` value was 10080, which is seven days. And
    the figures are only as recent as the last time the user actually ran
    Codex, which can be many days.

    This is the most fragile thing in the codebase. It reads an internal debug
    log by string-matching header names. Treat any change as expected.
    """

    LOG_NAME = "logs_2.sqlite"
    HEADER_USED = "x-codex-primary-used-percent"
    HEADER_WINDOW = "x-codex-primary-window-minutes"
    HEADER_RESET = "x-codex-primary-reset-at"

    def __init__(self, config_dir=None):
        self.config_dir = config_dir

    def read(self, *, home, profile_dir, active: bool) -> Usage | None:
        # The log is global to the Codex install, not per profile, so it only
        # ever describes whoever is signed in right now.
        if not active:
            return None
        try:
            root = Path(self.config_dir or (Path(home) / ".codex"))
            db = root / self.LOG_NAME
            if not db.is_file():
                return None
            body = self._latest_body(db)
            if not body:
                return None

            used = _header(body, self.HEADER_USED)
            window = _header(body, self.HEADER_WINDOW)
            reset = _header(body, self.HEADER_RESET)
            if used is None:
                return None

            label = _window_label(window)
            resets_ms = int(reset) * 1000 if reset and reset.isdigit() else None
            return Usage([_window(label, int(used), resets_ms, _now_ms(),
                                  stale=False if resets_ms else False)],
                         source="codex logs")
        except Exception:
            return None

    def _latest_body(self, db: Path) -> str | None:
        # Read-only, and ordered by the ts index so a 787 MB log costs a seek
        # rather than a scan.
        uri = f"file:{db}?mode=ro&immutable=0"
        with sqlite3.connect(uri, uri=True, timeout=0.5) as conn:
            row = conn.execute(
                "select feedback_log_body from logs "
                "where feedback_log_body like ? "
                "order by ts desc, id desc limit 1",
                (f"%{self.HEADER_USED}%",)).fetchone()
        return row[0] if row else None


def _header(body: str, name: str) -> str | None:
    """Pull one quoted header value out of a logged response dump."""
    import re
    found = re.search(rf'"{re.escape(name)}":\s*"([^"]*)"', body)
    return found.group(1) if found and found.group(1) else None


def _window_label(minutes) -> str:
    """Name a window from its length. Codex only ever reports 10080 (7 days)."""
    try:
        count = int(minutes)
    except (TypeError, ValueError):
        return "quota"
    if count % 1440 == 0:
        return f"{count // 1440}d"
    if count % 60 == 0:
        return f"{count // 60}h"
    return f"{count}m"


def _now_ms() -> int:
    import time
    return int(time.time() * 1000)


#: Which source belongs to which provider. A provider with no entry simply
#: renders without quota, which is a supported state rather than a gap.
SOURCES = {
    "claude": ClaudeUsageSource,
    "codex": CodexUsageSource,
}


def source_for(provider_id: str) -> UsageSource | None:
    factory = SOURCES.get(provider_id)
    return factory() if factory else None
