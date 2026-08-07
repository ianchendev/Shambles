"""Discovering profiles and working out who each one belongs to."""

import math
from dataclasses import dataclass
from pathlib import Path

from . import configjson, usage as usage_mod
from .errors import ProfileNameError

CREDENTIALS_NAME = "credentials.json"

TOKEN_OK = "ok"
TOKEN_MISSING = "missing"
TOKEN_EXPIRED = "expired"

TOKEN_WARNINGS = {
    TOKEN_MISSING: (
        "No token found. Switch to this profile and run 'claude' in terminal to login."
    ),
    TOKEN_EXPIRED: (
        "Token expired — switch to this profile and run /login."
    ),
}

INVALID_NAME_CHARS = set('/\\:*?"<>|')

#: The window is a fixed width and Tk labels do not truncate, so a long name
#: stretches the whole window rather than being clipped. 80 characters took a
#: 600px window to 1092px.
MAX_NAME_LENGTH = 40

#: Below this many days remaining, the countdown is worth drawing attention to.
EXPIRY_WARN_DAYS = 7

EXPIRY_OK = "ok"
EXPIRY_SOON = "soon"
EXPIRY_GONE = "gone"

MS_PER_DAY = 86_400_000


@dataclass(frozen=True)
class Profile:
    name: str
    path: Path
    active: bool
    email: str | None
    org: str | None
    token_state: str
    #: When this account's refresh token lapses. ``None`` if there is no
    #: readable credentials file at all.
    refresh_expires_ms: int | None = None
    #: Whole days until that moment, negative once past. Computed against the
    #: clock passed to :func:`discover`, never read from the system here.
    days_left: int | None = None
    #: Session and weekly figures for the card. Live for the active profile,
    #: stashed-and-aged for the rest; empty when neither is available.
    usage: "usage_mod.Usage" = usage_mod.EMPTY

    @property
    def warning(self) -> str | None:
        return TOKEN_WARNINGS.get(self.token_state)


def refresh_expiry_ms(profile_dir) -> int | None:
    """When this profile's refresh token lapses, or ``None`` if unreadable."""
    oauth = configjson.load(Path(profile_dir) / CREDENTIALS_NAME).get("claudeAiOauth")
    if not isinstance(oauth, dict):
        return None
    expires = oauth.get("refreshTokenExpiresAt")
    return expires if isinstance(expires, (int, float)) else None


def expiry_label(profile: Profile) -> str | None:
    """Short countdown for the UI, e.g. ``"29d"`` or ``"expired 3d ago"``."""
    days = profile.days_left
    if days is None:
        return None
    if days < 0:
        return f"expired {abs(days)}d ago"
    if days == 0:
        return "today"
    return f"{days}d"


def expiry_severity(profile: Profile) -> str | None:
    """How loudly the UI should render the countdown."""
    days = profile.days_left
    if days is None:
        return None
    if days < 0:
        return EXPIRY_GONE
    if days <= EXPIRY_WARN_DAYS:
        return EXPIRY_SOON
    return EXPIRY_OK


def list_profile_names(paths) -> list[str]:
    """Profile directories, case-insensitively sorted for display."""
    from . import state
    return sorted(state.profile_names(paths), key=str.casefold)


def token_state(profile_dir, now_ms: int) -> str:
    oauth = configjson.load(Path(profile_dir) / CREDENTIALS_NAME).get("claudeAiOauth")
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        return TOKEN_MISSING
    expires = oauth.get("refreshTokenExpiresAt")
    if isinstance(expires, (int, float)) and expires <= now_ms:
        return TOKEN_EXPIRED
    return TOKEN_OK


def resolve_usage(paths, name: str, active_name: str | None):
    """Usage for one profile.

    The active profile reads ``~/.claude.json``, which Claude Code keeps
    current. Everyone else reads what was stashed when they were last active,
    which the UI renders with its age attached -- see
    :mod:`shambles.usage` for why a stashed figure is never trusted silently.
    """
    if active_name is not None and name == active_name:
        live = usage_mod.parse(
            configjson.load(paths.claude_json).get("cachedUsageUtilization"))
        if live:
            return live
    return usage_mod.parse(configjson.load(paths.account(name)).get("usage"))


def resolve_account(paths, name: str, active_name: str | None) -> dict:
    """Best-known ``oauthAccount`` blob for a profile; ``{}`` if unknown.

    The live ~/.claude.json wins for the active profile, since it is the one
    Claude Code keeps current. Otherwise fall back to what was stashed when
    this profile was last active.
    """
    if active_name is not None and name == active_name:
        live = configjson.load(paths.claude_json).get("oauthAccount")
        if _usable(live):
            return live

    stashed = configjson.read_sidecar(paths.account(name)).get("oauthAccount")
    return stashed if _usable(stashed) else {}


def _usable(account) -> bool:
    return isinstance(account, dict) and bool(account.get("emailAddress"))


def _stamp(path: Path) -> int:
    try:
        return int(path.name.rsplit(".", 1)[1])
    except (IndexError, ValueError):
        return 0


def discover(paths, active_name: str | None, now_ms: int) -> list[Profile]:
    found = []
    for name in list_profile_names(paths):
        directory = paths.profile_dir(name)
        account = resolve_account(paths, name, active_name)
        expires = refresh_expiry_ms(directory)
        # Floor rather than truncate, so a token 12 hours past its window
        # reads as "expired 1d ago" instead of "today".
        days = math.floor((expires - now_ms) / MS_PER_DAY) if expires else None
        found.append(
            Profile(
                name=name,
                path=directory,
                active=(name == active_name),
                email=account.get("emailAddress"),
                org=account.get("organizationName"),
                token_state=token_state(directory, now_ms),
                refresh_expires_ms=expires,
                days_left=days,
                usage=resolve_usage(paths, name, active_name),
            )
        )
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
    if len(cleaned) > MAX_NAME_LENGTH:
        raise ProfileNameError(
            f"That name is {len(cleaned)} characters. Keep it to "
            f"{MAX_NAME_LENGTH} or fewer so the window stays a sensible size.")

    bad = sorted(set(cleaned) & INVALID_NAME_CHARS)
    if bad:
        raise ProfileNameError("Profile name cannot contain:  " + "  ".join(bad))
    lowered = cleaned.casefold()
    if any(str(other).casefold() == lowered for other in existing):
        raise ProfileNameError(f"A profile named '{cleaned}' already exists.")
    return cleaned
