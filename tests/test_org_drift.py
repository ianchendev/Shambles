"""One address, two organisations, two logins (owner decision D3).

Identity used to be the address alone. Somebody with a personal subscription
and a Team or Console seat under the same address has two logins that read
as one: the drift check never fired between them, and a switch or a
re-stash filed one's token over the other's saved one. The organisation (for
Claude) and the ChatGPT account (for Codex) are already in what Shambles
reads; a known mismatch in either is now drift. Unknown on either side is
not evidence of anything, as with the address.
"""

import base64
import json

import pytest

from helpers import (NOW, credentials, healthy_ms, make_live_claude_login,
                     make_profile, write_json)
from shambles import providers, state, switcher
from shambles.errors import DriftedLoginError

ADDRESS = "me@example.test"


def claude():
    return providers.load("claude", env={})


def codex():
    return providers.load("codex", env={})


def oauth_account(org_uuid, org_name):
    data = {"emailAddress": ADDRESS, "accountUuid": "uuid-me",
            "displayName": "Me", "organizationName": org_name,
            "organizationRateLimitTier": "max_5x"}
    if org_uuid is not None:
        data["organizationUuid"] = org_uuid
    return data


def claude_profile(paths, name, org_uuid, org_name, *, active=False):
    make_profile(paths, "claude", name, active=active)
    write_json(paths.account("claude", name),
               {"oauthAccount": oauth_account(org_uuid, org_name),
                "stashed_at": NOW})


def claude_live(paths, org_uuid, org_name, token):
    write_json(paths.claude_json, {"oauthAccount": oauth_account(
        org_uuid, org_name), "projects": {}})
    return make_live_claude_login(paths, access_token=token)


def jwt(claims):
    def segment(payload):
        raw = json.dumps(payload, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return f"{segment({'alg': 'none'})}.{segment(claims)}.sig"


def codex_blob(account_id, refresh):
    auth = {"chatgpt_plan_type": "plus", "organizations": [{"title": "Org"}]}
    if account_id is not None:
        auth["chatgpt_account_id"] = account_id
    return {"OPENAI_API_KEY": None, "auth_mode": "chatgpt", "tokens": {
        "access_token": jwt({"exp": healthy_ms(9) // 1000}),
        "id_token": jwt({"https://api.openai.com/profile": {"email": ADDRESS},
                         "https://api.openai.com/auth": auth}),
        "refresh_token": refresh, "account_id": account_id or "acct"}}


# -- Claude: the organisation --------------------------------------------------

def test_one_address_in_another_organisation_is_drift(paths):
    claude_profile(paths, "Personal", "org-personal", "Personal", active=True)
    claude_live(paths, "org-team", "Acme Team", "tok-team")

    current = state.inspect(paths, claude(), platform="linux")

    assert current.kind == state.DRIFTED
    # The address alone would read "signed in as me@, but Personal holds me@".
    assert "Acme Team" in current.live_email
    assert "Personal" in current.expected_email


def test_switching_away_does_not_file_the_other_organisations_token(paths):
    claude_profile(paths, "Personal", "org-personal", "Personal", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    claude_live(paths, "org-team", "Acme Team", "tok-team")
    saved = paths.credentials("claude", "Personal").read_bytes()

    with pytest.raises(DriftedLoginError):
        switcher.switch(paths, claude(), "Other", platform="linux",
                        sleep=lambda _: None)

    assert paths.credentials("claude", "Personal").read_bytes() == saved


def test_the_same_organisation_is_the_same_login(paths):
    claude_profile(paths, "Personal", "org-personal", "Personal", active=True)
    claude_live(paths, "org-personal", "Personal", "tok-other-bytes")

    assert state.inspect(paths, claude(), platform="linux").kind == state.MANAGED


def test_an_organisation_missing_on_one_side_is_not_evidence(paths):
    """A sidecar saved before Claude Code wrote organizationUuid."""
    claude_profile(paths, "Personal", None, "Personal", active=True)
    claude_live(paths, "org-team", "Acme Team", "tok-team")

    assert state.inspect(paths, claude(), platform="linux").kind == state.MANAGED


def test_the_address_does_not_suggest_a_profile_in_another_organisation(paths):
    claude_profile(paths, "Personal", "org-personal", "Personal")
    claude_profile(paths, "Team", "org-team", "Acme Team")
    claude_live(paths, "org-team", "Acme Team", "tok-new-sign-in")

    assert state.owner_by_address(paths, claude(), platform="linux") == "Team"


# -- Codex: the ChatGPT account ------------------------------------------------

def codex_live(paths, account_id, refresh):
    write_json(paths.home / ".codex" / "auth.json",
               codex_blob(account_id, refresh))


def codex_saved(paths, name, account_id, refresh, *, active=False):
    make_profile(paths, "codex", name, active=active)
    write_json(paths.credentials("codex", name),
               codex_blob(account_id, refresh))


def test_one_address_on_another_chatgpt_account_is_drift(paths):
    codex_saved(paths, "Personal", "acct-personal", "r-p", active=True)
    codex_live(paths, "acct-team", "r-t")

    assert state.inspect(paths, codex(), platform="linux").kind == state.DRIFTED


def test_restash_does_not_file_another_chatgpt_accounts_token(paths):
    """restash runs on every refresh, with no click."""
    codex_saved(paths, "Personal", "acct-personal", "r-p", active=True)
    codex_live(paths, "acct-team", "r-t")
    saved = paths.credentials("codex", "Personal").read_bytes()

    assert switcher.restash_active(paths, codex(), platform="linux") is False
    assert paths.credentials("codex", "Personal").read_bytes() == saved


def test_a_refresh_on_the_same_chatgpt_account_is_still_restashed(paths):
    codex_saved(paths, "Personal", "acct-personal", "r-1", active=True)
    codex_live(paths, "acct-personal", "r-2")

    assert switcher.restash_active(paths, codex(), platform="linux") is True


# -- found by an independent review of the first version ---------------------

def session_rewrote(paths, org_uuid, org_name):
    """A session still running in another organisation rewrote the config."""
    claude_live_config_only(paths, org_uuid, org_name)


def claude_live_config_only(paths, org_uuid, org_name):
    write_json(paths.claude_json, {"oauthAccount": oauth_account(
        org_uuid, org_name), "projects": {}})


def refreshed(paths, name):
    """The live login is ``name``'s, refreshed since it was saved."""
    saved = json.loads(paths.credentials("claude", name).read_text())
    saved["claudeAiOauth"]["accessToken"] = f"tok-{name}-refreshed"
    saved["claudeAiOauth"]["refreshToken"] = f"refresh-{name}-2"
    saved["claudeAiOauth"]["refreshTokenExpiresAt"] -= 1375
    write_json(paths.claude_dir / ".credentials.json", saved)
    return (paths.claude_dir / ".credentials.json").read_bytes()


def test_a_session_rewriting_the_organisation_is_not_drift(paths):
    """Personal is live, refreshed; a Team session rewrote the config. The
    lineage says the login is Personal's: managed, kept current, and a
    switch away files it under Personal."""
    claude_profile(paths, "Personal", "org-personal", "Personal", active=True)
    claude_profile(paths, "Team", "org-team", "Acme Team")
    session_rewrote(paths, "org-team", "Acme Team")
    live = refreshed(paths, "Personal")

    assert state.inspect(paths, claude(), platform="linux").kind == \
        state.MANAGED
    assert switcher.restash_active(paths, claude(), platform="linux") is True
    assert paths.credentials("claude", "Personal").read_bytes() == live
    team = paths.credentials("claude", "Team").read_bytes()

    switcher.switch(paths, claude(), "Team", platform="linux",
                    sleep=lambda _: None)

    assert paths.credentials("claude", "Personal").read_bytes() == live
    assert (paths.claude_dir / ".credentials.json").read_bytes() == team


def test_an_old_profile_is_not_given_a_sessions_organisation(paths):
    """A sidecar saved before organizationUuid existed has none. Filling it
    in from a config a session rewrote labels Personal as Team's, and then
    the mismatch is 'known' and real drift follows."""
    claude_profile(paths, "Personal", None, "Personal", active=True)
    claude_profile(paths, "Team", "org-team", "Acme Team")
    session_rewrote(paths, "org-team", "Acme Team")
    (paths.claude_dir).mkdir(exist_ok=True)
    (paths.claude_dir / ".credentials.json").write_bytes(
        paths.credentials("claude", "Personal").read_bytes())

    switcher.switch(paths, claude(), "Team", platform="linux",
                    sleep=lambda _: None)

    filed = json.loads(paths.account("claude", "Personal").read_text())
    assert filed["oauthAccount"].get("organizationUuid") != "org-team"


@pytest.mark.parametrize("names", [(None, None), ("Acme", "Acme")])
def test_drift_between_two_organisations_reads_as_two(paths, names):
    claude_profile(paths, "Personal", "org-a", names[0], active=True)
    claude_live(paths, "org-b", names[1], "tok-b")

    current = state.inspect(paths, claude(), platform="linux")

    assert current.kind == state.DRIFTED
    assert current.live_email != current.expected_email


def test_drift_found_by_bytes_names_the_organisation(paths):
    claude_profile(paths, "Personal", "org-personal", "Personal", active=True)
    claude_profile(paths, "Team", "org-team", "Acme Team")
    session_rewrote(paths, "org-team", "Acme Team")
    (paths.claude_dir).mkdir(exist_ok=True)
    (paths.claude_dir / ".credentials.json").write_bytes(
        paths.credentials("claude", "Team").read_bytes())

    current = state.inspect(paths, claude(), platform="linux")

    assert current.kind == state.DRIFTED
    assert current.live_email != current.expected_email


def test_the_address_suggests_the_exact_organisation_first(paths):
    claude_profile(paths, "Personal", None, "Personal")
    claude_profile(paths, "Team", "org-team", "Acme Team")
    claude_live(paths, "org-team", "Acme Team", "tok-new-sign-in")

    assert state.owner_by_address(paths, claude(), platform="linux") == "Team"


def test_another_organisations_usage_is_not_captured(paths):
    """The usage cache is keyed by accountUuid, which is the person, not the
    organisation: another organisation's figures were filed here."""
    from shambles import usage

    claude_profile(paths, "Personal", "org-personal", "Personal", active=True)
    write_json(paths.claude_json, {
        "oauthAccount": oauth_account("org-team", "Acme Team"),
        "cachedUsageUtilization": {
            "accountUuid": "uuid-me", "fetchedAtMs": NOW,
            "utilization": {"five_hour": {"utilization": 97}}}})

    assert usage.capture_live(paths, "claude", "Personal", now_ms=NOW) is False
