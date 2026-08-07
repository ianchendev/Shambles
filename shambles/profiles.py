"""Discovering profiles and working out who each one belongs to.

Everything provider-specific -- what a token means, where identity lives, when
a window closes -- is delegated. This module decides ordering, naming rules,
and how a computed liveness is worded for the UI, all of which are the same
for every vendor.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from . import state
from .errors import ProfileNameError
from .providers import ABSENT, CLOSED, CLOSING, NEEDS_LOGIN, Liveness

INVALID_NAME_CHARS = set('/\\:*?"<>|')

#: How loudly the UI draws the countdown chip.
EXPIRY_OK = "ok"
EXPIRY_SOON = "soon"
EXPIRY_GONE = "gone"

SEVERITY = {CLOSING: EXPIRY_SOON, CLOSED: EXPIRY_GONE}

WARNINGS = {
    ABSENT: "No token here yet. Switch to this profile and log in.",
    CLOSED: "Refresh window closed — switch to this profile and log in again.",
}


@dataclass(frozen=True)
class Profile:
    name: str
    provider: str
    path: Path
    active: bool
    email: str | None
    org: str | None
    plan: str | None
    liveness: Liveness


def warning(profile: Profile) -> str | None:
    """The ⚠ tooltip for a profile that cannot be used as-is."""
    return WARNINGS.get(profile.liveness.state)


def expiry_label(profile: Profile) -> str | None:
    """Short countdown for the UI, e.g. ``"29d"`` or ``"expired 3d ago"``.

    ``None`` for a profile with no token and for one whose expiry could not be
    determined -- the VS Code bundle writes Claude credentials without the
    field, and inventing a number there would be worse than showing none.
    """
    days = profile.liveness.days_left
    if days is None:
        return None
    if days < 0:
        return f"expired {abs(days)}d ago"
    if days == 0:
        return "today"
    return f"{days}d"


def expiry_severity(profile: Profile) -> str | None:
    if profile.liveness.days_left is None:
        return None
    return SEVERITY.get(profile.liveness.state, EXPIRY_OK)


def needs_login(profile: Profile) -> bool:
    return profile.liveness.state in NEEDS_LOGIN


def list_profile_names(paths, provider_id: str) -> list[str]:
    """Profile directories, case-insensitively sorted for display."""
    return sorted(state.profile_names(paths, provider_id), key=str.casefold)


def discover(paths, provider, active_name: str | None, now_ms: int, *,
             platform: str = sys.platform) -> list[Profile]:
    found = []
    for name in list_profile_names(paths, provider.id):
        directory = paths.profile_dir(provider.id, name)
        try:
            blob = paths.credentials(provider.id, name).read_bytes()
        except OSError:
            blob = None

        is_active = (name == active_name)
        identity = provider.identity(blob, home=paths.home,
                                     profile_dir=directory, active=is_active)
        found.append(Profile(
            name=name,
            provider=provider.id,
            path=directory,
            active=is_active,
            email=identity.email,
            org=identity.org,
            plan=identity.plan,
            liveness=provider.liveness(blob, now_ms=now_ms),
        ))
    return found


def validate_profile_name(name, existing) -> str:
    """Return the trimmed name, or raise :class:`ProfileNameError`."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ProfileNameError("Profile name cannot be empty.")
    if cleaned in (".", ".."):
        raise ProfileNameError("Profile name cannot be '.' or '..'.")
    if cleaned.startswith("."):
        raise ProfileNameError("Profile name cannot start with a dot.")
    bad = sorted(set(cleaned) & INVALID_NAME_CHARS)
    if bad:
        raise ProfileNameError("Profile name cannot contain:  " + "  ".join(bad))
    lowered = cleaned.casefold()
    if any(str(other).casefold() == lowered for other in existing):
        raise ProfileNameError(f"A profile named '{cleaned}' already exists.")
    return cleaned
