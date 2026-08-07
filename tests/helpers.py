"""Builders for synthetic homes. Never touches a real one."""

import base64
import json

NOW = 1_785_000_000_000  # fixed reference clock for every test
DAY_MS = 86_400_000


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -- claude -------------------------------------------------------------

def account(email="a@example.com", org="Acme", uuid="uuid-a"):
    return {
        "emailAddress": email,
        "organizationName": org,
        "accountUuid": uuid,
        "displayName": org,
        "organizationRateLimitTier": "max_5x",
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


def make_claude_json(paths, email="a@example.com", extra=None):
    """A ~/.claude.json with account keys plus unrelated shared state."""
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


def make_live_claude_login(paths, refresh_expires_ms=NOW + 30 * DAY_MS):
    """Put a credentials file inside the shared ~/.claude."""
    path = paths.claude_dir / ".credentials.json"
    write_json(path, credentials(refresh_expires_ms))
    return path


# -- codex --------------------------------------------------------------

def jwt(claims: dict) -> str:
    """An unsigned JWT. Signatures are never verified -- see CodexProvider."""
    def segment(payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f'{segment({"alg": "none", "typ": "JWT"})}.{segment(claims)}.sig'


def codex_auth(email="a@example.com", name="A User", plan="plus",
               org="Acme", exp_ms=NOW + 10 * DAY_MS):
    """An ~/.codex/auth.json under OAuth, shaped as Codex writes it.

    Note ``id_token`` is a bare JWT string on disk even though it is a struct
    in the Rust source -- the parser trap the spec records.
    """
    return {
        "OPENAI_API_KEY": None,
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": jwt({"exp": exp_ms // 1000}),
            "id_token": jwt({
                "https://api.openai.com/profile": {"email": email, "name": name},
                "https://api.openai.com/auth": {
                    "chatgpt_plan_type": plan,
                    "organizations": [{"title": org}],
                },
            }),
            "refresh_token": "refresh-1",
            "account_id": "acct-1",
        },
        "last_refresh": "2026-08-01T00:00:00Z",
    }


def make_live_codex_login(paths, **kwargs):
    path = paths.home / ".codex" / "auth.json"
    write_json(path, codex_auth(**kwargs))
    return path


# -- provider-agnostic --------------------------------------------------

def make_profile(paths, provider_id, name, *, email=None, token=True,
                 refresh_expires_ms=NOW + 30 * DAY_MS, active=False):
    """Create a slim profile: a credential and, for Claude, a stashed identity."""
    directory = paths.ensure_profile(provider_id, name)
    if token:
        blob = (credentials(refresh_expires_ms) if provider_id == "claude"
                else codex_auth(email=email or "a@example.com",
                                exp_ms=refresh_expires_ms))
        write_json(paths.credentials(provider_id, name), blob)
    if email and provider_id == "claude":
        write_json(paths.account(provider_id, name),
                   {"oauthAccount": account(email), "stashed_at": NOW})
    if active:
        paths.ensure_provider(provider_id)
        paths.active_marker(provider_id).write_text(name + "\n", encoding="utf-8")
    return directory


def make_legacy_profile(paths, name, *, email=None, sessions=0):
    """A pre-1.0 profile: a full ~/.claude copy with its own history."""
    directory = paths.legacy_profiles_dir / name
    (directory / "projects" / "-some-project").mkdir(parents=True, exist_ok=True)
    write_json(directory / ".credentials.json", credentials())
    if email:
        write_json(directory / ".shambles.json",
                   {"oauthAccount": account(email), "stashed_at": NOW})
    for index in range(sessions):
        (directory / "projects" / "-some-project" /
         f"{name}-{index}.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    return directory


def make_v1_profile(paths, name, *, email=None, token=True, active=False):
    """A v1.0 slim profile in ~/.claude-profiles/, the migration's input."""
    directory = paths.legacy_profiles_dir / name
    directory.mkdir(parents=True, exist_ok=True)
    if token:
        write_json(directory / "credentials.json", credentials())
    if email:
        write_json(directory / "account.json",
                   {"oauthAccount": account(email), "stashed_at": NOW})
    if active:
        paths.legacy_active_marker.write_text(name + "\n", encoding="utf-8")
    return directory
