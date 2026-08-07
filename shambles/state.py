"""Which account is currently logged in, and whether Shambles knows about it.

There is no symlink to inspect any more. The active profile is recorded in
``~/.claude-profiles/active`` and then *verified* against the identity actually
present in ``~/.claude.json``, so a ``/login`` performed outside Shambles is
detected rather than silently mistrusted.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from . import configjson

#: The marker names a profile, and the live identity matches it.
MANAGED = "managed"
#: No profiles exist yet.
UNMANAGED = "unmanaged"
#: A profile is marked active but is no longer on disk.
MISSING_PROFILE = "missing-profile"
#: The live login belongs to some account other than the marked profile,
#: which is what a manual /login looks like from here.
DRIFTED = "drifted"
#: Profiles exist but none is marked active.
UNKNOWN = "unknown"

#: ~/.claude is expected to be a real directory now. A leftover symlink means
#: the 1.x layout is still in place and migration has not run.
LEGACY_LAYOUT = "legacy-layout"


@dataclass(frozen=True)
class State:
    kind: str
    profile: str | None = None
    #: Email of whoever is actually logged in, regardless of the marker.
    live_email: str | None = None
    #: Email the marked profile expects, when that differs from live_email.
    expected_email: str | None = None


#: Claude Code honours this, and it moves the *entire* config tree -- config,
#: credentials and projects/ alike. Shambles swaps the login inside ~/.claude,
#: so anything reading a different tree never sees the switch.
CONFIG_DIR_ENV = "CLAUDE_CONFIG_DIR"


def config_dir_override(paths) -> str | None:
    """The foreign config directory the environment points at, if any.

    Returns ``None`` when unset, empty, or pointing at the very directory
    Shambles manages -- setting it explicitly to ``~/.claude`` changes nothing
    and must not raise a false alarm.

    Only the CLI is affected: the VS Code extension host does not inherit
    shell environment variables, which is why this tool exists at all.
    """
    raw = os.environ.get(CONFIG_DIR_ENV, "").strip()
    if not raw:
        return None
    try:
        target = Path(raw).expanduser().resolve()
        managed = paths.claude_dir.resolve()
    except OSError:
        return raw
    return None if target == managed else str(target)


def read_active(paths) -> str | None:
    try:
        name = paths.active_marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name or None


def write_active(paths, name: str | None) -> None:
    paths.ensure_store()
    if name is None:
        paths.active_marker.unlink(missing_ok=True)
        return
    paths.active_marker.write_text(name + "\n", encoding="utf-8")


def live_email(paths) -> str | None:
    account = configjson.load(paths.claude_json).get("oauthAccount") or {}
    if not isinstance(account, dict):
        return None
    return account.get("emailAddress")


def profile_email(paths, name: str) -> str | None:
    account = configjson.load(paths.account(name)).get("oauthAccount") or {}
    if not isinstance(account, dict):
        return None
    return account.get("emailAddress")


def profile_names(paths) -> list[str]:
    """Directories under the profile store that hold a profile.

    A directory counts even with no credentials file: that is exactly the
    state of a profile added but not yet logged in.
    """
    try:
        entries = sorted(p for p in paths.profiles_dir.iterdir() if p.is_dir())
    except OSError:
        return []
    return [p.name for p in entries if not p.name.startswith(".")]


def inspect(paths) -> State:
    """Classify the current login without touching anything."""
    if paths.claude_dir.is_symlink():
        return State(LEGACY_LAYOUT, profile=None)

    names = profile_names(paths)
    marked = read_active(paths)
    live = live_email(paths)

    # A marker naming a profile that is gone matters more than the store
    # being empty -- otherwise deleting the last profile reads as a clean
    # unmanaged machine and the stale marker is never surfaced.
    if marked is not None and marked not in names:
        return State(MISSING_PROFILE, profile=marked, live_email=live)
    if not names:
        return State(UNMANAGED, live_email=live)
    if marked is None:
        return State(UNKNOWN, live_email=live)

    expected = profile_email(paths, marked)
    # Only call it drift when both sides actually name someone. A profile that
    # has never been logged into has no expectation to violate.
    if expected and live and expected != live:
        return State(DRIFTED, profile=marked, live_email=live,
                     expected_email=expected)

    return State(MANAGED, profile=marked, live_email=live or expected)
