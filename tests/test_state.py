"""Working out which account is live, without a symlink to inspect."""

import os

from pathlib import Path

from helpers import make_claude_json, make_live_login, make_profile
from shambles import state


def test_no_profiles_is_unmanaged(paths):
    make_claude_json(paths, email="me@example.com")
    s = state.inspect(paths)
    assert s.kind == state.UNMANAGED
    assert s.live_email == "me@example.com"


def test_marked_profile_matching_the_live_login_is_managed(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    s = state.inspect(paths)
    assert s.kind == state.MANAGED
    assert s.profile == "Work"
    assert s.live_email == "work@example.com"


def test_profiles_with_no_marker_are_unknown(paths):
    make_profile(paths, "Work", email="work@example.com")
    make_claude_json(paths, email="work@example.com")
    assert state.inspect(paths).kind == state.UNKNOWN


def test_marker_pointing_at_a_deleted_profile(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    for child in paths.profile_dir("Work").iterdir():
        child.unlink()
    paths.profile_dir("Work").rmdir()
    s = state.inspect(paths)
    assert s.kind == state.MISSING_PROFILE
    assert s.profile == "Work"


def test_login_changed_outside_shambles_is_drift(paths):
    """Someone ran /login by hand. The marker still says Work, but the live
    identity is someone else -- say so rather than quietly mislabelling it."""
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="somebody-else@example.com")
    s = state.inspect(paths)
    assert s.kind == state.DRIFTED
    assert s.profile == "Work"
    assert s.live_email == "somebody-else@example.com"
    assert s.expected_email == "work@example.com"


def test_a_never_logged_in_profile_is_not_drift(paths):
    """A fresh profile has no stored identity, so there is nothing to violate."""
    make_profile(paths, "Fresh", token=False, active=True)
    make_claude_json(paths, email="whoever@example.com")
    assert state.inspect(paths).kind == state.MANAGED


def test_a_leftover_symlink_reports_the_legacy_layout(paths):
    make_profile(paths, "Work", email="work@example.com")
    os.symlink(str(paths.profile_dir("Work")), str(paths.claude_dir),
               target_is_directory=True)
    assert state.inspect(paths).kind == state.LEGACY_LAYOUT


def test_backups_dir_is_not_a_profile(paths):
    make_profile(paths, "Work", email="work@example.com", active=True)
    paths.backup_dir.mkdir(parents=True, exist_ok=True)
    assert state.profile_names(paths) == ["Work"]


def test_active_marker_round_trips(paths):
    state.write_active(paths, "Work")
    assert state.read_active(paths) == "Work"
    state.write_active(paths, None)
    assert state.read_active(paths) is None


# ---- CLAUDE_CONFIG_DIR silently redirects the CLI -----------------------

def test_no_warning_when_the_override_is_unset(paths, monkeypatch):
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    assert state.config_dir_override(paths) is None


def test_an_override_pointing_elsewhere_is_reported(paths, monkeypatch):
    """Shambles swaps the login inside ~/.claude. If the CLI is pointed at a
    different tree by the environment, it reads a config Shambles never
    touches -- so switches appear to do nothing there."""
    elsewhere = paths.home / "somewhere-else"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere))
    override = state.config_dir_override(paths)
    assert override is not None
    assert Path(override) == elsewhere.resolve()


def test_an_override_pointing_at_claude_dir_is_harmless(paths, monkeypatch):
    """Explicitly setting it to the directory Shambles already manages changes
    nothing, so it must not raise a false alarm."""
    paths.claude_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(paths.claude_dir))
    assert state.config_dir_override(paths) is None


def test_a_relative_or_untidy_override_still_resolves(paths, monkeypatch):
    """~ and trailing slashes must not turn a harmless setting into a warning."""
    paths.claude_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(paths.claude_dir) + "/")
    assert state.config_dir_override(paths) is None


def test_an_empty_override_is_ignored(paths, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "")
    assert state.config_dir_override(paths) is None
