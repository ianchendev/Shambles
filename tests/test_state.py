"""Working out which account is live, without a symlink to inspect."""

import os

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
