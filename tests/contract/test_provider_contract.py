"""One suite every provider must pass, whatever vendor it wraps.

Adding a provider means writing a spec, a thin adapter, and passing this file.
That is what makes the design swappable rather than merely layered -- a diagram
does not stop a new provider quietly skipping the awkward cases, and this does.

Provider-specific behaviour is asserted at the bottom, after the shared suite.
"""

import json

import pytest

from shambles import providers
from shambles.providers import ABSENT, CLOSED, CLOSING, LIVE, UNKNOWN, Identity
from shambles.providers import spec as specmod
from shambles.providers.claude import account_name, service_name
from shambles.providers.codex import jwt_claims
from shambles.stores import CredentialStore, FileStore, KeychainStore

NOW = 1_785_000_000_000
DAY_MS = 86_400_000


@pytest.fixture(params=providers.ids())
def provider(request):
    return providers.load(request.param, env={})


# -- the shared contract ------------------------------------------------------


def test_provider_satisfies_the_protocol(provider):
    assert isinstance(provider, providers.Provider)


def test_provider_declares_its_identity(provider):
    assert provider.id
    assert provider.display_name
    assert isinstance(provider.rotates, bool)
    assert provider.warn_days >= 0


def test_login_hint_names_a_command(provider):
    """A closed window is a handoff, so the hint has to be actionable."""
    hint = provider.login_hint()
    assert hint.strip()
    assert provider.id in hint or "login" in hint.lower()


def test_spec_declares_a_store_for_every_platform(provider):
    for platform in ("darwin", "linux", "win32"):
        block = specmod.store_block(provider.spec, platform)
        assert block["kind"] in {"file", "keychain", "credman"}


def test_store_is_a_credential_store_on_every_platform(provider, tmp_path):
    for platform in ("darwin", "linux", "win32"):
        assert isinstance(
            provider.store(home=tmp_path, platform=platform), CredentialStore)


def test_no_credential_reads_as_absent(provider):
    assert provider.liveness(None, now_ms=NOW).state == ABSENT
    assert provider.liveness(b"", now_ms=NOW).state == ABSENT


def test_absent_means_needs_login(provider):
    assert provider.liveness(None, now_ms=NOW).needs_login


@pytest.mark.parametrize("blob", [
    b"not json at all",
    b"{",
    b"[]",
    b"null",
    b'{"unexpected":"shape"}',
    "\udcff".encode("utf-8", "surrogateescape"),
])
def test_a_corrupt_credential_never_raises(provider, blob, tmp_path):
    """A corrupt profile must still list, just without an expiry.

    Raising here would take down the whole window over one bad file.
    """
    assert provider.liveness(blob, now_ms=NOW).state in {ABSENT, UNKNOWN, CLOSED}
    assert isinstance(provider.identity(blob, home=tmp_path), Identity)


def test_identity_of_nothing_is_unknown_not_an_error(provider, tmp_path):
    assert provider.identity(None, home=tmp_path).known is False


def test_companion_read_returns_a_mapping(provider, tmp_path):
    assert isinstance(provider.companion_read(home=tmp_path), dict)


def test_companion_round_trips_through_write(provider, tmp_path):
    """Whatever a provider stashes, it must be able to put back."""
    before = provider.companion_read(home=tmp_path)
    provider.companion_write(before, home=tmp_path)
    assert provider.companion_read(home=tmp_path) == before


def test_a_credential_survives_the_providers_own_store(provider, tmp_path):
    """The load-bearing property, exercised end to end per provider.

    Uses whichever platform gives this provider a plain file, so the test runs
    everywhere without touching a real Keychain.
    """
    store = provider.store(home=tmp_path, platform="linux")
    if not isinstance(store, FileStore):
        pytest.skip(f"{provider.id} does not use a file store on linux")
    payload = json.dumps({"nested": {"token": "x" * 108}}).encode()
    store.write(payload)
    assert store.read() == payload


# -- Claude ------------------------------------------------------------------


def test_claude_service_name_is_bare_when_config_dir_is_unset():
    provider = providers.load("claude", env={})
    block = provider.spec["store"]["darwin"]
    assert service_name(block, config_dir="/home/example/.claude",
                        env={}) == "Claude Code-credentials"


def test_claude_service_name_gains_a_hash_when_config_dir_is_set():
    """The finding that makes hardcoding the service name a bug.

    Setting ``CLAUDE_CONFIG_DIR`` -- even to the default path -- appends eight
    hex characters of SHA-256, so a hardcoded lookup finds nothing. The golden
    vector below was produced by the same algorithm that was confirmed against
    a live CLI run.
    """
    provider = providers.load("claude", env={})
    block = provider.spec["store"]["darwin"]
    name = service_name(block, config_dir="/home/example/.claude",
                        env={"CLAUDE_CONFIG_DIR": "/home/example/.claude"})
    assert name == "Claude Code-credentials-3783d4ca"


def test_claude_securestorage_override_suppresses_the_hash():
    """The undocumented escape hatch, which is the only way to relocate the
    config while keeping the default Keychain item."""
    provider = providers.load("claude", env={})
    block = provider.spec["store"]["darwin"]
    name = service_name(
        block, config_dir="/somewhere/else",
        env={"CLAUDE_CONFIG_DIR": "/somewhere/else",
             "CLAUDE_SECURESTORAGE_CONFIG_DIR": ""})
    assert name == "Claude Code-credentials"


@pytest.mark.parametrize("username, expected", [
    ("liam", "liam"),
    ("ada.lovelace", "ada.lovelace"),
    ("with space", "claude-code-user"),
    ("wîth-unicode", "claude-code-user"),
    ("", "claude-code-user"),
])
def test_claude_account_falls_back_for_names_the_vendor_refuses(username, expected):
    provider = providers.load("claude", env={})
    block = provider.spec["store"]["darwin"]
    assert account_name(block, {"USER": username}) == expected


def test_claude_account_is_a_fixed_literal_on_windows():
    provider = providers.load("claude", env={})
    block = provider.spec["store"]["win32"]
    assert account_name(block, {"USER": "liam"}) == "claude-code-user"


def test_claude_uses_the_keychain_on_macos(tmp_path):
    provider = providers.load("claude", env={})
    assert isinstance(provider.store(home=tmp_path, platform="darwin"),
                      KeychainStore)


def test_claude_missing_expiry_is_unknown_not_closed():
    """The VS Code extension writes credentials without refreshTokenExpiresAt.

    Reporting CLOSED would strand a working account behind a login prompt it
    does not need.
    """
    provider = providers.load("claude", env={})
    blob = json.dumps({"claudeAiOauth": {"accessToken": "tok"}}).encode()
    assert provider.liveness(blob, now_ms=NOW).state == UNKNOWN


@pytest.mark.parametrize("offset_ms, expected", [
    (10 * DAY_MS, LIVE),
    (2 * DAY_MS, LIVE),
    (1 * DAY_MS, CLOSING),
    (DAY_MS // 2, CLOSING),          # closes today, but has not closed
    (1, CLOSING),                    # one millisecond left is still open
    (0, CLOSED),                     # closes exactly now
    (-1 * DAY_MS, CLOSED),
    (-30 * DAY_MS, CLOSED),
])
def test_claude_liveness_states(offset_ms, expected):
    """The boundary matters: a window closing *today* still works, and telling
    someone to log in while their token is valid is the same failure as letting
    them switch to a dead one."""
    provider = providers.load("claude", env={})
    blob = json.dumps({"claudeAiOauth": {
        "refreshTokenExpiresAt": NOW + offset_ms}}).encode()
    assert provider.liveness(blob, now_ms=NOW).state == expected


def test_claude_splice_preserves_unrelated_keys(tmp_path):
    """Switching must not touch projects, MCP servers or machine IDs."""
    provider = providers.load("claude", env={})
    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({
        "projects": {"/work": {}}, "machineID": "m1",
        "oauthAccount": {"emailAddress": "old@example.com"},
    }), encoding="utf-8")

    provider.companion_write(
        {"oauthAccount": {"emailAddress": "new@example.com"}}, home=tmp_path)

    after = json.loads(config.read_text(encoding="utf-8"))
    assert after["projects"] == {"/work": {}}
    assert after["machineID"] == "m1"
    assert after["oauthAccount"]["emailAddress"] == "new@example.com"


def test_claude_splice_deletes_keys_the_incoming_profile_lacks(tmp_path):
    """Otherwise a switch shows the previous account's identity."""
    provider = providers.load("claude", env={})
    config = tmp_path / ".claude.json"
    config.write_text(json.dumps({
        "oauthAccount": {"emailAddress": "old@example.com"},
        "cachedUsageUtilization": {"utilization": 55},
        "machineID": "m1",
    }), encoding="utf-8")

    provider.companion_write({}, home=tmp_path)

    after = json.loads(config.read_text(encoding="utf-8"))
    assert "oauthAccount" not in after
    assert "cachedUsageUtilization" not in after
    assert after["machineID"] == "m1"


def test_claude_reads_plan_from_the_accurate_field(tmp_path):
    """subscriptionType read 'team' for a Max 5x account, so the plan badge
    must come from organizationRateLimitTier instead."""
    provider = providers.load("claude", env={})
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {
        "emailAddress": "a@example.com",
        "organizationRateLimitTier": "default_claude_max_5x",
    }}), encoding="utf-8")
    credential = json.dumps({"claudeAiOauth": {
        "subscriptionType": "team"}}).encode()

    identity = provider.identity(credential, home=tmp_path)
    assert identity.plan == "default_claude_max_5x"


# -- Codex -------------------------------------------------------------------


def _jwt(claims: dict) -> str:
    import base64
    payload = base64.urlsafe_b64encode(
        json.dumps(claims).encode()).decode().rstrip("=")
    return f"header.{payload}.signature"


def test_codex_uses_the_same_file_on_every_platform(tmp_path):
    provider = providers.load("codex", env={})
    stores = {provider.store(home=tmp_path, platform=p).path
              for p in ("darwin", "linux", "win32")}
    assert len(stores) == 1


def test_codex_rotates_and_claude_does_not():
    """The difference that forbids restoring a stale Codex snapshot."""
    assert providers.load("codex", env={}).rotates is True
    assert providers.load("claude", env={}).rotates is False


def test_codex_reads_identity_out_of_the_id_token(tmp_path):
    provider = providers.load("codex", env={})
    blob = json.dumps({"tokens": {"id_token": _jwt({
        "https://api.openai.com/profile": {
            "email": "a@example.com", "name": "Ada"},
        "https://api.openai.com/auth": {
            "chatgpt_plan_type": "pro",
            "organizations": [{"title": "Personal", "is_default": True}]},
    })}}).encode()

    identity = provider.identity(blob, home=tmp_path)
    assert identity.email == "a@example.com"
    assert identity.display_name == "Ada"
    assert identity.plan == "pro"
    assert identity.org == "Personal"


@pytest.mark.parametrize("days_out, expected", [
    (30, LIVE),
    (2, CLOSING),
    (-1, CLOSED),
])
def test_codex_liveness_comes_from_the_jwt_exp_claim(days_out, expected):
    provider = providers.load("codex", env={})
    exp = (NOW + days_out * DAY_MS) // 1000
    blob = json.dumps({"tokens": {"access_token": _jwt({"exp": exp})}}).encode()
    assert provider.liveness(blob, now_ms=NOW).state == expected


def test_codex_falls_back_to_last_refresh_when_the_jwt_is_unreadable():
    """Codex's own eight-day backstop, for a token whose exp will not parse."""
    provider = providers.load("codex", env={})
    from datetime import datetime, timezone
    recent = datetime.fromtimestamp(NOW / 1000, timezone.utc).isoformat()
    blob = json.dumps({
        "tokens": {"access_token": "not-a-jwt"},
        "last_refresh": recent,
    }).encode()
    assert provider.liveness(blob, now_ms=NOW).state == LIVE


def test_codex_has_no_companion_file(tmp_path):
    assert providers.load("codex", env={}).companion_read(home=tmp_path) == {}


def test_jwt_claims_tolerates_rubbish():
    for bad in (None, "", "a", "a.b", "a.!!!.c", 42):
        assert jwt_claims(bad) == {}


# -- registry ----------------------------------------------------------------


def test_unknown_provider_names_the_known_ones():
    with pytest.raises(KeyError, match="claude"):
        providers.load("nope")


def test_every_registered_provider_ships_a_spec():
    assert set(providers.ids()) <= set(specmod.available())


# ---- a credential whose token has been emptied ---------------------------
#
# Reported from a real machine: an account lost access, and Claude Code
# rewrote its credential with accessToken and refreshToken set to "" while
# leaving refreshTokenExpiresAt, scopes and subscriptionType intact. Liveness
# reads only the expiry, so the profile listed as healthy with 24 days left
# and no warning of any kind -- switching to it drops you at a login prompt.

def healthy_blob(provider) -> bytes:
    """A complete, working credential -- token fields included.

    The minimal blobs elsewhere in this file omit the token entirely, which
    is deliberately *not* the same signal: a partial credential that never
    carried the field proves nothing, while a field present and emptied is
    exactly how a cleared login looks on disk.
    """
    if provider.id == "claude":
        return json.dumps({"claudeAiOauth": {
            "refreshTokenExpiresAt": NOW + 30 * DAY_MS,
            "accessToken": "access-token-value",
            "refreshToken": "refresh-token-value",
        }}).encode()
    return json.dumps({"tokens": {
        "access_token": _jwt({"exp": (NOW + 30 * DAY_MS) // 1000}),
        "refresh_token": "refresh-token-value",
    }}).encode()


def _blank_the_token(provider, blob: bytes) -> bytes:
    """Empty the refresh token in place, as the vendor does."""
    import json
    data = json.loads(blob)
    if provider.id == "claude":
        data["claudeAiOauth"]["refreshToken"] = ""
        data["claudeAiOauth"]["accessToken"] = ""
    else:
        data["tokens"]["refresh_token"] = ""
    return json.dumps(data).encode()


def test_a_credential_with_an_emptied_token_is_not_reported_healthy(provider):
    from shambles.providers import SIGNED_OUT

    blob = _blank_the_token(provider, healthy_blob(provider))
    liveness = provider.liveness(blob, now_ms=NOW)

    assert liveness.state == SIGNED_OUT, (
        f"an unusable credential reported {liveness.state!r}")
    assert liveness.needs_login


def test_an_emptied_token_carries_no_expiry_to_display(provider):
    """The window it names is meaningless once the token is gone, and
    showing a date implies there is something left to expire."""
    from shambles.providers import SIGNED_OUT

    blob = _blank_the_token(provider, healthy_blob(provider))
    liveness = provider.liveness(blob, now_ms=NOW)
    assert liveness.state == SIGNED_OUT
    assert liveness.expires_at_ms is None


def test_a_full_credential_is_still_live(provider):
    """The guard must not catch a working account."""
    assert provider.liveness(healthy_blob(provider), now_ms=NOW).state == LIVE
