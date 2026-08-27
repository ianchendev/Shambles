"""Builders for synthetic homes. Never touches a real one."""

import base64
import json
import time

NOW = 1_785_000_000_000  # fixed reference clock for every test
DAY_MS = 86_400_000


#: One reading of the real clock per test session. Stable, so two fixtures
#: built from it agree to the byte -- the round-trip test compares credential
#: bytes, and a value re-read from the clock on each call disagrees with
#: itself by however many milliseconds passed between the two calls.
_SESSION_NOW = int(time.time() * 1000)


def healthy_ms(days: int = 30) -> int:
    """An expiry that far out from the *real* clock.

    Liveness is computed against ``switcher.now_ms()``, so a fixture meaning
    "this account is fine" has to be relative to the real clock. Built off the
    frozen NOW instead, it stops meaning "fine" the day the calendar passes
    it -- which is exactly what happened: NOW + 30 days is 2026-08-25, and on
    2026-08-26 every GUI test seeded with a "healthy" login started reading it
    as expired. NOW stays for assertions that need a stable reference (stash
    timestamps, formatted dates); anything a liveness check will look at
    belongs here.
    """
    return _SESSION_NOW + days * DAY_MS


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


def credentials(refresh_expires_ms=None, access_token="tok"):
    refresh_expires_ms = (healthy_ms() if refresh_expires_ms is None
                          else refresh_expires_ms)
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


def make_live_claude_login(paths, refresh_expires_ms=None,
                           access_token="tok"):
    """Put a credentials file inside the shared ~/.claude.

    ``access_token`` matches :func:`make_profile`'s per-profile value so a
    caller can seed a live login that genuinely is the active profile's
    credential, which is what it always is in reality.
    """
    path = paths.claude_dir / ".credentials.json"
    write_json(path, credentials(refresh_expires_ms, access_token=access_token))
    return path


# -- codex --------------------------------------------------------------

def jwt(claims: dict) -> str:
    """An unsigned JWT. Signatures are never verified -- see CodexProvider."""
    def segment(payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f'{segment({"alg": "none", "typ": "JWT"})}.{segment(claims)}.sig'


def codex_auth(email="a@example.com", name="A User", plan="plus",
               org="Acme", exp_ms=None):
    """An ~/.codex/auth.json under OAuth, shaped as Codex writes it.

    Note ``id_token`` is a bare JWT string on disk even though it is a struct
    in the Rust source -- the parser trap the spec records.
    """
    exp_ms = healthy_ms(10) if exp_ms is None else exp_ms
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
                 refresh_expires_ms=None, active=False):
    """Create a slim profile: a credential and, for Claude, a stashed identity.

    The credential is made **distinguishable per profile**. Claude's tokens are
    opaque and carry no identity, so without this every Claude profile would
    hold byte-identical credentials and the round-trip test could not tell a
    correct switch from one that swapped two accounts' tokens -- it would
    compare a blob against an identical blob and pass either way.
    """
    refresh_expires_ms = (healthy_ms() if refresh_expires_ms is None
                          else refresh_expires_ms)
    directory = paths.ensure_profile(provider_id, name)
    if token:
        blob = (credentials(refresh_expires_ms, access_token=f"tok-{name}")
                if provider_id == "claude"
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
