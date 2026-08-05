"""Builders for synthetic ~/.claude trees."""

import json

NOW = 1_785_000_000_000  # fixed reference clock for every test
DAY_MS = 86_400_000


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def account(email="a@example.com", org="Acme", uuid="uuid-a"):
    return {
        "emailAddress": email,
        "organizationName": org,
        "accountUuid": uuid,
        "displayName": org,
    }


def credentials(refresh_expires_ms=NOW + 30 * DAY_MS, access_token="tok"):
    return {
        "claudeAiOauth": {
            "accessToken": access_token,
            "refreshToken": "refresh",
            "expiresAt": NOW + 8 * 3_600_000,
            "refreshTokenExpiresAt": refresh_expires_ms,
            "scopes": ["user:inference"],
            "subscriptionType": "team",
            "rateLimitTier": "default_raven",
        }
    }


def make_profile(paths, name, *, email=None, token=True,
                 refresh_expires_ms=NOW + 30 * DAY_MS, settings=None):
    """Create a profile directory, optionally with a sidecar and credentials."""
    d = paths.profile_dir(name)
    d.mkdir(parents=True, exist_ok=True)
    if token:
        write_json(d / ".credentials.json", credentials(refresh_expires_ms))
    if email:
        write_json(paths.sidecar(name),
                   {"oauthAccount": account(email), "stashed_at": NOW})
    if settings is not None:
        write_json(d / "settings.json", settings)
    return d


def make_claude_json(paths, email="a@example.com", extra=None):
    """Write a ~/.claude.json with account keys plus unrelated shared state."""
    data = {
        "numStartups": 42,
        "projects": {"/some/dir": {"allowedTools": []}},
        "oauthAccount": account(email),
        "cachedUsageUtilization": {
            "accountUuid": "uuid-a",
            "utilization": {"five_hour": {"utilization": 55}},
        },
        "machineID": "machine",
    }
    if extra:
        data.update(extra)
    write_json(paths.claude_json, data)
    return data
