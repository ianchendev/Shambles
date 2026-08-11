"""Which account is logged in for one provider, and whether Shambles knows it.

The active profile is recorded in ``~/.shambles/<provider>/active`` and then
*verified* against the identity actually present in the provider's own store,
so a login performed outside Shambles is detected rather than silently
mistrusted.

One provider at a time. Two providers have two independent active profiles and
no operation on one can affect the other, which is why every function here
takes a provider rather than looping over them.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .providers import spec as specmod

#: The marker names a profile, and the live identity matches it.
MANAGED = "managed"
#: No profiles exist yet for this provider.
UNMANAGED = "unmanaged"
#: A profile is marked active but is no longer on disk.
MISSING_PROFILE = "missing-profile"
#: The live login belongs to some account other than the marked profile,
#: which is what a manual login looks like from here.
DRIFTED = "drifted"
#: Profiles exist but none is marked active.
UNKNOWN = "unknown"


@dataclass(frozen=True)
class State:
    kind: str
    provider: str | None = None
    profile: str | None = None
    #: Email of whoever is actually logged in, regardless of the marker.
    live_email: str | None = None
    #: Email the marked profile expects, when that differs from live_email.
    expected_email: str | None = None


def config_dir_override(provider, *, home, env=None) -> str | None:
    """The foreign config directory this provider's environment points at.

    Returns ``None`` when unset, empty, or pointing at the very directory the
    provider uses by default -- setting it explicitly to its own default
    changes nothing and must not raise a false alarm.

    Only a terminal is affected: neither VS Code extension host inherits shell
    environment variables, which is why this tool exists at all.
    """
    env = os.environ if env is None else env
    block = provider.spec.get("config_dir") or {}
    name = block.get("env")
    raw = env.get(name, "").strip() if name else ""
    if not raw:
        return None
    default = specmod.expand(block.get("default", ""), home=home)
    try:
        if Path(raw).expanduser().resolve() == Path(default).resolve():
            return None
    except OSError:
        return raw
    return raw


def read_active(paths, provider_id: str) -> str | None:
    try:
        name = paths.active_marker(provider_id).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name or None


def write_active(paths, provider_id: str, name: str | None) -> None:
    paths.ensure_provider(provider_id)
    if name is None:
        paths.active_marker(provider_id).unlink(missing_ok=True)
        return
    paths.active_marker(provider_id).write_text(name + "\n", encoding="utf-8")


def profile_names(paths, provider_id: str) -> list[str]:
    """Directories under one provider's store that hold a profile.

    A directory counts even with no credential file: that is exactly the state
    of a profile added but not yet logged in.
    """
    try:
        entries = sorted(p for p in paths.provider_dir(provider_id).iterdir()
                         if p.is_dir())
    except OSError:
        return []
    return [p.name for p in entries if not p.name.startswith(".")]


def live_email(paths, provider, *, platform: str) -> str | None:
    """Who the provider's live store says is signed in."""
    try:
        blob = provider.store(home=paths.home, platform=platform).read()
    except OSError:
        return None
    return provider.identity(blob, home=paths.home, active=True).email


def profile_email(paths, provider, name: str) -> str | None:
    """Who a stashed profile belongs to."""
    directory = paths.profile_dir(provider.id, name)
    try:
        blob = paths.credentials(provider.id, name).read_bytes()
    except OSError:
        blob = None
    return provider.identity(blob, home=paths.home, profile_dir=directory,
                             active=False).email


def inspect(paths, provider, *, platform: str = sys.platform) -> State:
    """Classify one provider's login without touching anything."""
    names = profile_names(paths, provider.id)
    marked = read_active(paths, provider.id)
    live = live_email(paths, provider, platform=platform)

    # A marker naming a profile that is gone matters more than the store being
    # empty -- otherwise deleting the last profile reads as a clean unmanaged
    # machine and the stale marker is never surfaced.
    if marked is not None and marked not in names:
        return State(MISSING_PROFILE, provider.id, profile=marked, live_email=live)
    if not names:
        return State(UNMANAGED, provider.id, live_email=live)
    if marked is None:
        return State(UNKNOWN, provider.id, live_email=live)

    expected = profile_email(paths, provider, marked)
    # Only call it drift when both sides actually name someone. A profile that
    # has never been logged into has no expectation to violate.
    if expected and live and expected != live:
        return State(DRIFTED, provider.id, profile=marked, live_email=live,
                     expected_email=expected)

    return State(MANAGED, provider.id, profile=marked, live_email=live or expected)
