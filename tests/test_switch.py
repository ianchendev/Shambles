"""Switching accounts moves the login and nothing else."""

import json

import pytest

from helpers import (DAY_MS, NOW, make_claude_json, make_live_login,
                     make_profile)
from shambles import configjson, state, switcher
from shambles.errors import (AlreadyManagedError, ConfigUnreadableError,
                             ProfileNotFoundError)


def _fixed(ms=NOW):
    return lambda: ms


# ---- the whole point: history is never touched --------------------------

def test_session_history_survives_a_switch(paths):
    """The regression this redesign exists for. History lives in
    ~/.claude/projects and is shared by every account; switching must leave
    every transcript exactly where it was."""
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    sessions = paths.claude_dir / "projects" / "-repo"
    sessions.mkdir(parents=True)
    (sessions / "a.jsonl").write_text("session one")
    (sessions / "b.jsonl").write_text("session two")

    switcher.switch(paths, "Personal", now_ms_fn=_fixed())

    assert (sessions / "a.jsonl").read_text() == "session one"
    assert (sessions / "b.jsonl").read_text() == "session two"
    assert state.inspect(paths).profile == "Personal"


def test_plugins_and_settings_are_shared_too(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)
    (paths.claude_dir / "settings.json").write_text('{"theme": "dark"}')
    (paths.claude_dir / "plugins").mkdir()
    (paths.claude_dir / "plugins" / "x.js").write_text("plugin")

    switcher.switch(paths, "Personal", now_ms_fn=_fixed())

    assert (paths.claude_dir / "settings.json").read_text() == '{"theme": "dark"}'
    assert (paths.claude_dir / "plugins" / "x.js").read_text() == "plugin"


# ---- the login itself ----------------------------------------------------

def test_switch_installs_the_target_credentials(paths):
    make_profile(paths, "Work", email="work@example.com", active=True,
                 refresh_expires_ms=NOW + 10 * DAY_MS)
    make_profile(paths, "Personal", email="me@example.com",
                 refresh_expires_ms=NOW + 20 * DAY_MS)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths, refresh_expires_ms=NOW + 10 * DAY_MS)

    switcher.switch(paths, "Personal", now_ms_fn=_fixed())

    live = json.loads(paths.live_credentials.read_text())
    assert live["claudeAiOauth"]["refreshTokenExpiresAt"] == NOW + 20 * DAY_MS


def test_switch_splices_the_incoming_identity(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    switcher.switch(paths, "Personal", now_ms_fn=_fixed())

    config = configjson.load(paths.claude_json)
    assert config["oauthAccount"]["emailAddress"] == "me@example.com"
    assert config["projects"] == {"/some/dir": {"allowedTools": []}}
    assert config["machineID"] == "machine"


def test_switch_stashes_the_outgoing_login(paths):
    """Switching away must not lose the account you are leaving."""
    make_profile(paths, "Work", email="work@example.com", active=True,
                 token=False)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths, refresh_expires_ms=NOW + 15 * DAY_MS)

    switcher.switch(paths, "Personal", now_ms_fn=_fixed())

    stashed = json.loads(paths.credentials("Work").read_text())
    assert stashed["claudeAiOauth"]["refreshTokenExpiresAt"] == NOW + 15 * DAY_MS
    assert configjson.read_sidecar(paths.account("Work"))[
        "oauthAccount"]["emailAddress"] == "work@example.com"


def test_switching_to_a_profile_with_no_login_clears_credentials(paths):
    """So Claude Code prompts for a login instead of reusing the last one."""
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Fresh", token=False)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    switcher.switch(paths, "Fresh", now_ms_fn=_fixed())

    assert not paths.live_credentials.exists()


def test_credentials_are_owner_only(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    switcher.switch(paths, "Personal", now_ms_fn=_fixed())

    import os
    import stat
    mode = stat.S_IMODE(os.stat(paths.live_credentials).st_mode)
    assert mode == 0o600, f"credentials world-readable: {oct(mode)}"


def test_switch_to_a_missing_profile_raises(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    with pytest.raises(ProfileNotFoundError):
        switcher.switch(paths, "Nope", now_ms_fn=_fixed())


def test_corrupt_config_aborts_before_anything_moves(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_live_login(paths)
    paths.claude_json.write_text('{"projects": {trunc')
    before = paths.claude_json.read_text()

    with pytest.raises(ConfigUnreadableError):
        switcher.switch(paths, "Personal", now_ms_fn=_fixed())

    assert state.read_active(paths) == "Work", "marker moved despite the abort"
    assert paths.claude_json.read_text() == before


def test_switch_backs_up_the_config_first(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    switcher.switch(paths, "Personal", now_ms_fn=_fixed())

    snaps = list(paths.backup_dir.glob("claude.json.*"))
    assert len(snaps) == 1
    assert configjson.load(snaps[0])["oauthAccount"]["emailAddress"] == \
        "work@example.com"


# ---- saving and adding ---------------------------------------------------

def test_save_current_account_captures_the_live_login(paths):
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths, refresh_expires_ms=NOW + 12 * DAY_MS)

    name = switcher.save_current_account(paths, "Work", now_ms_fn=_fixed())

    assert name == "Work"
    assert state.read_active(paths) == "Work"
    saved = json.loads(paths.credentials("Work").read_text())
    assert saved["claudeAiOauth"]["refreshTokenExpiresAt"] == NOW + 12 * DAY_MS
    assert configjson.read_sidecar(paths.account("Work"))[
        "oauthAccount"]["emailAddress"] == "work@example.com"


def test_save_leaves_history_alone(paths):
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)
    sessions = paths.claude_dir / "projects" / "-repo"
    sessions.mkdir(parents=True)
    (sessions / "a.jsonl").write_text("keep me")

    switcher.save_current_account(paths, "Work", now_ms_fn=_fixed())

    assert (sessions / "a.jsonl").read_text() == "keep me"


def test_save_refuses_when_already_managed(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)
    with pytest.raises(AlreadyManagedError):
        switcher.save_current_account(paths, "Again", now_ms_fn=_fixed())


def test_save_refuses_with_no_login_present(paths):
    make_claude_json(paths, email="work@example.com")
    paths.claude_dir.mkdir(parents=True, exist_ok=True)
    with pytest.raises(AlreadyManagedError):
        switcher.save_current_account(paths, "Work", now_ms_fn=_fixed())


def test_add_empty_account_activates_a_blank_login(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    switcher.add_empty_account(paths, "Personal", now_ms_fn=_fixed())

    assert state.read_active(paths) == "Personal"
    assert not paths.live_credentials.exists()
    # and the account we left is still recoverable
    assert paths.credentials("Work").exists()


def test_add_refuses_to_discard_an_unsaved_login(paths):
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)
    with pytest.raises(AlreadyManagedError):
        switcher.add_empty_account(paths, "Personal", now_ms_fn=_fixed())


def test_rename_moves_the_marker_too(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")

    switcher.rename_profile(paths, "Work", "Day Job")

    assert state.read_active(paths) == "Day Job"
    assert paths.credentials("Day Job").exists()
    assert not paths.profile_dir("Work").exists()
