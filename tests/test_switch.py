"""Switching accounts moves the login and nothing else."""

import json

import pytest

from helpers import (DAY_MS, NOW, make_claude_json, make_live_login,
                     make_profile)
from shambles import configjson, state, switcher
from shambles.errors import (AlreadyManagedError, ConfigUnreadableError,
                             ProfileNotFoundError, ShamblesError)

from conftest import posix_modes_only


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


@posix_modes_only
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


# ---- transient locks, the Windows antivirus/indexer case ----------------

def _flaky_copyfile(monkeypatch, failures):
    """Make shutil.copyfile fail `failures` times, then work."""
    import shutil
    real = shutil.copyfile
    state_ = {"n": 0}

    def flaky(src, dst, *a, **k):
        state_["n"] += 1
        if state_["n"] <= failures:
            raise PermissionError(13, "The process cannot access the file")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(shutil, "copyfile", flaky)
    return state_


def _two_profiles(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)


def test_a_briefly_locked_credentials_file_is_retried(paths, monkeypatch):
    """A running Claude Code, an antivirus scan or the Windows indexer can hold
    the file for a moment. Giving up on the first refusal turns a hiccup into a
    failed switch."""
    _two_profiles(paths)
    calls = _flaky_copyfile(monkeypatch, failures=2)

    switcher.switch(paths, "Personal", now_ms_fn=_fixed(), sleep=lambda _s: None)

    assert calls["n"] > 2, "did not retry"
    assert state.inspect(paths).profile == "Personal"


def test_a_permanently_locked_file_reports_cleanly(paths, monkeypatch):
    """Never a raw OSError: the GUI only renders ShamblesError, so anything
    else reaches the user as a silent stderr traceback."""
    _two_profiles(paths)
    _flaky_copyfile(monkeypatch, failures=99)

    with pytest.raises(ShamblesError):
        switcher.switch(paths, "Personal", now_ms_fn=_fixed(),
                        sleep=lambda _s: None)


def test_a_lock_while_stashing_the_outgoing_login_is_caught(paths, monkeypatch):
    """The outgoing stash runs before the incoming copy and was outside the
    error handling, so a lock there escaped as a bare PermissionError."""
    _two_profiles(paths)
    _flaky_copyfile(monkeypatch, failures=99)

    with pytest.raises(ShamblesError):
        switcher.switch(paths, "Personal", now_ms_fn=_fixed(),
                        sleep=lambda _s: None)


def test_a_failed_switch_leaves_the_marker_alone(paths, monkeypatch):
    """If the login could not be installed, the app must not claim otherwise."""
    _two_profiles(paths)
    _flaky_copyfile(monkeypatch, failures=99)

    with pytest.raises(ShamblesError):
        switcher.switch(paths, "Personal", now_ms_fn=_fixed(),
                        sleep=lambda _s: None)

    assert state.read_active(paths) == "Work"


def test_save_current_account_survives_a_transient_lock(paths, monkeypatch):
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)
    _flaky_copyfile(monkeypatch, failures=2)

    switcher.save_current_account(paths, "Work", now_ms_fn=_fixed(),
                                  sleep=lambda _s: None)

    assert paths.credentials("Work").exists()


@posix_modes_only
def test_switching_keeps_the_store_owner_only(paths):
    import stat
    _two_profiles(paths)
    switcher.switch(paths, "Personal", now_ms_fn=_fixed())
    for d in (paths.profiles_dir, paths.profile_dir("Personal")):
        assert stat.S_IMODE(d.stat().st_mode) == 0o700, f"{d} is {oct(d.stat().st_mode)}"


# ---- removing a profile -------------------------------------------------

def test_remove_deletes_the_profile_directory(paths):
    _two_profiles(paths)
    assert paths.credentials("Personal").exists()

    switcher.remove_profile(paths, "Personal")

    assert not paths.profile_dir("Personal").exists()
    assert state.profile_names(paths) == ["Work"]


def test_remove_refuses_the_active_profile(paths):
    """The UI hides the button, but the guard belongs here too -- hiding a
    control is not a safety property."""
    _two_profiles(paths)
    with pytest.raises(ShamblesError):
        switcher.remove_profile(paths, "Work")
    assert paths.credentials("Work").exists()


def test_remove_refuses_an_unknown_profile(paths):
    _two_profiles(paths)
    with pytest.raises(ProfileNotFoundError):
        switcher.remove_profile(paths, "Nope")


def test_remove_refuses_a_name_that_escapes_the_store(paths):
    """Defence against a name that resolves outside ~/.claude-profiles."""
    _two_profiles(paths)
    for hostile in ("..", "../..", "Personal/../..", "/etc"):
        with pytest.raises(ShamblesError):
            switcher.remove_profile(paths, hostile)
    assert paths.claude_dir.exists()


def test_remove_leaves_everything_else_alone(paths):
    _two_profiles(paths)
    sessions = paths.claude_dir / "projects" / "-repo"
    sessions.mkdir(parents=True)
    (sessions / "a.jsonl").write_text("keep me")

    switcher.remove_profile(paths, "Personal")

    assert (sessions / "a.jsonl").read_text() == "keep me"
    assert paths.live_credentials.exists()
    assert state.inspect(paths).kind == state.MANAGED
    assert state.read_active(paths) == "Work"


def test_remove_does_not_disturb_the_config(paths):
    _two_profiles(paths)
    before = configjson.load(paths.claude_json)
    switcher.remove_profile(paths, "Personal")
    assert configjson.load(paths.claude_json) == before


def test_switching_still_works_after_a_removal(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_profile(paths, "Third", email="third@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    switcher.remove_profile(paths, "Personal")
    switcher.switch(paths, "Third", now_ms_fn=_fixed())

    assert state.inspect(paths).profile == "Third"
    assert state.live_email(paths) == "third@example.com"
