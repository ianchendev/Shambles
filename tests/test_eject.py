"""Leaving cleanly: restoring a stock Claude Code installation.

Someone who tries Shambles and deletes ~/.claude-profiles by hand loses every
token stashed there. Eject exists so that is never the required move.
"""

import json
import os

import pytest

from helpers import (NOW, make_claude_json, make_live_login, make_profile)
from shambles import eject, state
from shambles.errors import ShamblesError

from conftest import posix_modes_only


def _managed(paths, active="Work"):
    make_profile(paths, "Work", email="work@example.com",
                 active=(active == "Work"))
    make_profile(paths, "Personal", email="me@example.com",
                 active=(active == "Personal"))
    if active != "Work":
        paths.active_marker.write_text(active + "\n", encoding="utf-8")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)


def test_survey_reports_what_would_be_left_behind(paths):
    _managed(paths)
    plan = eject.survey(paths)
    assert plan.active == "Work"
    assert sorted(plan.other_profiles) == ["Personal"]
    assert plan.credentials_kept is True


def test_survey_changes_nothing(paths):
    _managed(paths)
    before = sorted(str(p) for p in paths.home.rglob("*"))
    eject.survey(paths)
    assert sorted(str(p) for p in paths.home.rglob("*")) == before


def test_eject_leaves_the_active_login_in_place(paths):
    """The whole point: ~/.claude must still be signed in afterwards."""
    _managed(paths)
    live_before = paths.live_credentials.read_text()

    eject.run(paths)

    assert paths.live_credentials.exists()
    assert paths.live_credentials.read_text() == live_before
    assert state.live_email(paths) == "work@example.com"


def test_eject_restores_the_active_profile_credentials_if_missing(paths):
    """If ~/.claude has no login but the active profile does, put it back --
    otherwise ejecting would leave the user signed out."""
    _managed(paths)
    paths.live_credentials.unlink()

    eject.run(paths)

    assert paths.live_credentials.exists()
    stored = json.loads(paths.credentials("Work").read_text())
    assert json.loads(paths.live_credentials.read_text()) == stored


def test_eject_removes_only_shambles_bookkeeping(paths):
    _managed(paths)
    eject.run(paths)
    assert not paths.active_marker.exists()
    assert not (paths.claude_dir / ".shambles.json").exists()


def test_eject_never_deletes_profiles(paths):
    """Tokens for the accounts you are not using are irreplaceable without a
    verification email. Eject reports them; the user removes them."""
    _managed(paths)
    eject.run(paths)
    assert paths.credentials("Personal").exists()
    assert paths.credentials("Work").exists()


def test_eject_leaves_session_history_untouched(paths):
    _managed(paths)
    sessions = paths.claude_dir / "projects" / "-repo"
    sessions.mkdir(parents=True)
    (sessions / "a.jsonl").write_text("keep me")

    eject.run(paths)

    assert (sessions / "a.jsonl").read_text() == "keep me"


def test_eject_leaves_the_config_identity_alone(paths):
    _managed(paths)
    eject.run(paths)
    from shambles import configjson
    config = configjson.load(paths.claude_json)
    assert config["oauthAccount"]["emailAddress"] == "work@example.com"
    assert config["projects"] == {"/some/dir": {"allowedTools": []}}


@posix_modes_only
def test_restored_credentials_are_owner_only(paths):
    import stat
    _managed(paths)
    paths.live_credentials.unlink()
    eject.run(paths)
    mode = stat.S_IMODE(os.stat(paths.live_credentials).st_mode)
    assert mode == 0o600, oct(mode)


def test_eject_refuses_on_the_legacy_layout(paths):
    """Ejecting a symlinked ~/.claude would leave a dangling link. Migrate
    first."""
    make_profile(paths, "Work", email="work@example.com")
    os.symlink(str(paths.profile_dir("Work")), str(paths.claude_dir),
               target_is_directory=True)
    with pytest.raises(ShamblesError):
        eject.run(paths)


def test_eject_is_idempotent(paths):
    _managed(paths)
    eject.run(paths)
    eject.run(paths)          # must not raise on an already-stock install
    assert paths.live_credentials.exists()


def test_eject_with_no_active_profile_still_tidies_up(paths):
    make_profile(paths, "Work", email="work@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    plan = eject.run(paths)

    assert plan.active is None
    assert paths.live_credentials.exists()
    assert not paths.active_marker.exists()


def test_restoring_a_login_retries_a_transient_lock(paths, monkeypatch):
    """Eject re-installs the credentials file, so it needs the same retry the
    switch path has -- otherwise a momentary lock aborts an uninstall."""
    import shutil as _shutil
    _managed(paths)
    paths.live_credentials.unlink()

    real, calls = _shutil.copyfile, {"n": 0}

    def flaky(src, dst, *a, **k):
        calls["n"] += 1
        if calls["n"] <= 2:
            raise PermissionError(13, "The process cannot access the file")
        return real(src, dst, *a, **k)

    monkeypatch.setattr(_shutil, "copyfile", flaky)
    eject.run(paths, sleep=lambda _s: None)

    assert calls["n"] > 2, "gave up on the first refusal"
    assert paths.live_credentials.exists()
