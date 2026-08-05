"""Discovering profiles and working out who each one belongs to."""

import math
from dataclasses import dataclass
from pathlib import Path

from . import configjson
from .errors import ProfileNameError

CREDENTIALS_NAME = ".credentials.json"
BACKUPS_DIRNAME = "backups"
BACKUP_GLOB = ".claude.json.backup.*"

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
    """Non-dot directories directly under ~/.claude-profiles/.

    The leading dot on .shambles-backups/ is what excludes it.
    """
    if not paths.profiles_dir.is_dir():
        return []
    names = [
        entry.name
        for entry in paths.profiles_dir.iterdir()
        if entry.is_dir() and not entry.name.startswith(".")
    ]
    return sorted(names, key=str.casefold)


def token_state(profile_dir, now_ms: int) -> str:
    oauth = configjson.load(Path(profile_dir) / CREDENTIALS_NAME).get("claudeAiOauth")
    if not isinstance(oauth, dict) or not oauth.get("accessToken"):
        return TOKEN_MISSING
    expires = oauth.get("refreshTokenExpiresAt")
    if isinstance(expires, (int, float)) and expires <= now_ms:
        return TOKEN_EXPIRED
    return TOKEN_OK


def resolve_account(paths, name: str, active_name: str | None) -> dict:
    """Best-known ``oauthAccount`` blob for a profile; ``{}`` if unknown.

    Four sources, first hit wins: the live ~/.claude.json when this profile is
    active, then its sidecar, then the newest .claude.json backup Claude Code
    left inside the profile, then nothing.
    """
    if active_name is not None and name == active_name:
        live = configjson.load(paths.claude_json).get("oauthAccount")
        if _usable(live):
            return live

    stashed = configjson.read_sidecar(paths.sidecar(name)).get("oauthAccount")
    if _usable(stashed):
        return stashed

    return _account_from_backups(paths.profile_dir(name) / BACKUPS_DIRNAME)


def _usable(account) -> bool:
    return isinstance(account, dict) and bool(account.get("emailAddress"))


def _account_from_backups(backups_dir: Path) -> dict:
    if not backups_dir.is_dir():
        return {}
    snaps = sorted(backups_dir.glob(BACKUP_GLOB), key=_stamp, reverse=True)
    for snap in snaps:
        account = configjson.load(snap).get("oauthAccount")
        if _usable(account):
            return account
    return {}


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
    bad = sorted(set(cleaned) & INVALID_NAME_CHARS)
    if bad:
        raise ProfileNameError("Profile name cannot contain:  " + "  ".join(bad))
    lowered = cleaned.casefold()
    if any(str(other).casefold() == lowered for other in existing):
        raise ProfileNameError(f"A profile named '{cleaned}' already exists.")
    return cleaned
