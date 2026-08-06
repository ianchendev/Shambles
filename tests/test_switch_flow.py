"""The switch flow: what it refuses, what it captures, and in what order."""

import json

import pytest

from shambles import providers
from shambles.app import actions, snapshot as snap
from tests.test_snapshot import claude_blob, claude_identity, make_profile

NOW = 1_785_000_000_000
DAY_MS = 86_400_000


@pytest.fixture
def claude():
    return providers.load("claude", env={})


@pytest.fixture
def codex():
    return providers.load("codex", env={})


def live_path(home):
    return home / ".claude" / ".credentials.json"


def do_switch(provider, name, home):
    return actions.switch(provider, name, home=home, platform="linux")


# -- refusing before anything moves -------------------------------------------


def test_an_unknown_account_is_refused_by_name(claude, tmp_path):
    with pytest.raises(actions.SwitchRefused, match="Nowhere|no Claude Code account"):
        do_switch(claude, "Nowhere", tmp_path)


def test_an_unreadable_companion_aborts_before_the_credential_moves(claude, tmp_path):
    """Splicing onto a config that failed to parse would replace every project
    and MCP server in it with two keys."""
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    make_profile(tmp_path, "claude", "Personal", blob=claude_blob())
    (tmp_path / ".claude.json").write_text("{ truncated", encoding="utf-8")
    live_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    live_path(tmp_path).write_bytes(b"original")

    with pytest.raises(actions.SwitchRefused, match="could not be read"):
        do_switch(claude, "Personal", tmp_path)

    assert live_path(tmp_path).read_bytes() == b"original"
    assert snap.active_name(tmp_path, "claude") == "Work"


def test_an_absent_companion_is_fine(claude, tmp_path):
    """A machine that has never run Claude Code has no config yet."""
    make_profile(tmp_path, "claude", "Work", blob=claude_blob())
    do_switch(claude, "Work", tmp_path)
    assert snap.active_name(tmp_path, "claude") == "Work"


# -- what a switch actually does ----------------------------------------------


def test_the_incoming_credential_reaches_the_live_store(claude, tmp_path):
    blob = claude_blob(NOW + 10 * DAY_MS)
    make_profile(tmp_path, "claude", "Personal", blob=blob)
    do_switch(claude, "Personal", tmp_path)
    assert live_path(tmp_path).read_bytes() == blob


def test_a_credential_survives_a_round_trip_unmodified(claude, tmp_path):
    """The load-bearing property, at flow level: Work -> Personal -> Work must
    leave Work's credential byte-identical, refresh token included."""
    work = claude_blob(NOW + 11 * DAY_MS)
    personal = claude_blob(NOW + 22 * DAY_MS)
    make_profile(tmp_path, "claude", "Work", blob=work, active=True)
    make_profile(tmp_path, "claude", "Personal", blob=personal)
    live_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    live_path(tmp_path).write_bytes(work)

    do_switch(claude, "Personal", tmp_path)
    assert live_path(tmp_path).read_bytes() == personal
    do_switch(claude, "Work", tmp_path)
    assert live_path(tmp_path).read_bytes() == work


def test_switching_to_a_profile_with_no_login_clears_rather_than_reuses(claude, tmp_path):
    """Leaving the old credential in place would silently keep using the
    previous account instead of prompting."""
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    make_profile(tmp_path, "claude", "Fresh")
    live_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    live_path(tmp_path).write_bytes(claude_blob())

    result = do_switch(claude, "Fresh", tmp_path)
    assert result.needs_login is True
    assert not live_path(tmp_path).exists()


def test_the_identity_follows_the_credential(claude, tmp_path):
    claude_identity(tmp_path, email="work@example.com")
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    parked = make_profile(tmp_path, "claude", "Personal", blob=claude_blob())
    (parked / "account.json").write_text(json.dumps({
        "oauthAccount": {"emailAddress": "personal@example.com"}}), encoding="utf-8")

    do_switch(claude, "Personal", tmp_path)
    config = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
    assert config["oauthAccount"]["emailAddress"] == "personal@example.com"


def test_unrelated_config_keys_are_preserved(claude, tmp_path):
    (tmp_path / ".claude.json").write_text(json.dumps({
        "projects": {"/work": {}}, "machineID": "m1",
        "oauthAccount": {"emailAddress": "work@example.com"}}), encoding="utf-8")
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    make_profile(tmp_path, "claude", "Personal", blob=claude_blob())

    do_switch(claude, "Personal", tmp_path)
    config = json.loads((tmp_path / ".claude.json").read_text(encoding="utf-8"))
    assert config["projects"] == {"/work": {}}
    assert config["machineID"] == "m1"


def test_the_outgoing_login_is_captured_before_the_incoming_lands(claude, tmp_path):
    """Switching away must never strand an account."""
    make_profile(tmp_path, "claude", "Work", active=True)   # no stash yet
    make_profile(tmp_path, "claude", "Personal", blob=claude_blob())
    live = claude_blob(NOW + 5 * DAY_MS)
    live_path(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    live_path(tmp_path).write_bytes(live)

    do_switch(claude, "Personal", tmp_path)
    stashed = tmp_path / ".shambles/claude/Work/credential"
    assert stashed.read_bytes() == live


def test_the_companion_is_backed_up_before_being_spliced(claude, tmp_path):
    claude_identity(tmp_path, email="work@example.com")
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    make_profile(tmp_path, "claude", "Personal", blob=claude_blob())

    do_switch(claude, "Personal", tmp_path)
    backups = list((tmp_path / ".shambles/claude/.backups").iterdir())
    assert backups
    assert "work@example.com" in backups[0].read_text(encoding="utf-8")


# -- rotation -----------------------------------------------------------------


def test_sync_captures_a_rotated_credential(codex, tmp_path):
    """Codex mints a replacement refresh token on every use. A snapshot taken
    at the last switch is dead once that happens, so the live copy has to be
    re-captured before it can be switched away from."""
    make_profile(tmp_path, "codex", "Personal", blob=b'{"tokens":{}}', active=True)
    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_bytes(b'{"tokens":{"refresh_token":"rotated"}}')

    assert actions.sync_active(codex, home=tmp_path, platform="linux") is True
    stashed = tmp_path / ".shambles/codex/Personal/credential"
    assert b"rotated" in stashed.read_bytes()


def test_sync_writes_nothing_when_the_credential_is_unchanged(codex, tmp_path):
    blob = b'{"tokens":{"refresh_token":"same"}}'
    make_profile(tmp_path, "codex", "Personal", blob=blob, active=True)
    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_bytes(blob)
    assert actions.sync_active(codex, home=tmp_path, platform="linux") is False


def test_sync_only_ever_writes_inside_the_profile_library(codex, tmp_path):
    """It runs whenever the panel opens, so it must not be able to race a
    running session over a vendor file."""
    make_profile(tmp_path, "codex", "Personal", blob=b"old", active=True)
    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_bytes(b"new")
    before = auth.stat().st_mtime_ns

    actions.sync_active(codex, home=tmp_path, platform="linux")
    assert auth.read_bytes() == b"new"
    assert auth.stat().st_mtime_ns == before


def test_a_rotated_codex_credential_survives_a_round_trip(codex, tmp_path):
    work = b'{"tokens":{"refresh_token":"work-1"}}'
    personal = b'{"tokens":{"refresh_token":"personal-1"}}'
    make_profile(tmp_path, "codex", "Work", blob=work, active=True)
    make_profile(tmp_path, "codex", "Personal", blob=personal)
    auth = tmp_path / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, exist_ok=True)
    auth.write_bytes(work)

    # Codex runs and rotates the token before the user switches away.
    rotated = b'{"tokens":{"refresh_token":"work-2"}}'
    auth.write_bytes(rotated)

    actions.switch(codex, "Personal", home=tmp_path, platform="linux")
    assert auth.read_bytes() == personal
    actions.switch(codex, "Work", home=tmp_path, platform="linux")
    assert auth.read_bytes() == rotated, "the rotated token must come back, not the stale one"
