"""Discovering profiles and working out who each one belongs to.

Everything provider-specific -- what a token means, where identity lives, when
a window closes -- is delegated. This module decides ordering, naming rules,
and how a computed liveness is worded for the UI, all of which are the same
for every vendor.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from . import configjson, state, usage as usage_mod
from .errors import ProfileNameError
from .providers import ABSENT, CLOSED, CLOSING, NEEDS_LOGIN, Liveness

INVALID_NAME_CHARS = set('/\\:*?"<>|')

#: How loudly the UI draws the attention chip.
EXPIRY_OK = "ok"
EXPIRY_SOON = "soon"
EXPIRY_GONE = "gone"

SEVERITY = {CLOSING: EXPIRY_SOON, CLOSED: EXPIRY_GONE, ABSENT: EXPIRY_GONE}

#: Face copy for the chip. Healthy / unknown accounts show none (DD-1).
FACE_LABELS = {
    CLOSING: "soon",
    CLOSED: "needs login",
    ABSENT: "needs login",
}

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
    #: Session and weekly figures for the card. Live for the active profile,
    #: stashed-and-aged for the rest; empty when neither is available, which
    #: is every profile of a provider that publishes no usage at all.
    usage: "usage_mod.Usage" = usage_mod.EMPTY
    #: Whether this provider exposes usage figures at all. Distinguishes "none
    #: recorded yet", which is worth explaining, from "never will be", which is
    #: not -- Codex publishes nothing readable.
    publishes_usage: bool = False


def warning(profile: Profile) -> str | None:
    """The ⚠ tooltip for a profile that cannot be used as-is."""
    return WARNINGS.get(profile.liveness.state)


def expiry_label(profile: Profile) -> str | None:
    """Short face label for the attention chip, e.g. ``"soon"``.

    Healthy accounts return ``None`` — DD-1: no duration on the face.
    Countdown numbers stay out of this helper; tooltips format dates instead.
    """
    return FACE_LABELS.get(profile.liveness.state)


def expiry_severity(profile: Profile) -> str | None:
    return SEVERITY.get(profile.liveness.state)


def needs_login(profile: Profile) -> bool:
    return profile.liveness.state in NEEDS_LOGIN


def list_profile_names(paths, provider_id: str) -> list[str]:
    """Profile directories, case-insensitively sorted for display."""
    return sorted(state.profile_names(paths, provider_id), key=str.casefold)


def resolve_usage(paths, provider, name: str, active_name: str | None):
    """Usage figures for one profile.

    The active profile reads the vendor's own live cache, which it keeps
    current. Everyone else reads what was stashed when they were last active,
    which the UI renders with its age attached -- see :mod:`shambles.usage`
    for why a stashed figure is never trusted silently.

    Only Claude publishes anything readable; every other provider returns
    empty, which the card treats as a supported state rather than a gap.
    """
    companion = provider.spec.get("companion")
    if not companion:
        return usage_mod.EMPTY

    if active_name is not None and name == active_name:
        live = usage_mod.parse(
            configjson.load(paths.claude_json).get("cachedUsageUtilization"))
        if live:
            return live

    stashed = configjson.load(paths.account(provider.id, name))
    # stash_live_login writes whatever companion_read returned, so the key is
    # the vendor's own rather than a name of ours.
    return usage_mod.parse(stashed.get("cachedUsageUtilization")
                           or stashed.get("usage"))


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
            usage=resolve_usage(paths, provider, name, active_name),
            publishes_usage=bool(provider.spec.get("companion")),
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
