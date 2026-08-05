"""Converting the pre-1.0 layout back to one shared ~/.claude.

The old design gave every account its own copy of ~/.claude, so each had its
own projects/ directory and switching accounts appeared to erase weeks of
session history. These tests pin down that the merge loses nothing.
"""

import json
import os

import pytest

from helpers import NOW, make_claude_json, make_legacy_profile
from shambles import configjson, migrate, state, switcher
from shambles.errors import ShamblesError


def _legacy_setup(paths, active="Admin"):
    make_legacy_profile(paths, "Admin", email="admin@example.com", sessions=5)
    make_legacy_profile(paths, "Work", email="work@example.com", sessions=2)
    make_claude_json(paths, email="admin@example.com")
    os.symlink(str(paths.profile_dir(active)), str(paths.claude_dir),
               target_is_directory=True)


def test_detects_when_migration_is_needed(paths):
    _legacy_setup(paths)
    assert migrate.needed(paths) is True


def test_not_needed_once_claude_is_a_real_directory(paths):
    paths.claude_dir.mkdir(parents=True)
    assert migrate.needed(paths) is False


def test_survey_picks_the_richest_profile_as_the_base(paths):
    _legacy_setup(paths)
    plan = migrate.survey(paths)
    assert plan.base == "Admin"          # 5 sessions beats 2
    assert plan.others == ["Work"]
    assert plan.merged_files == 2


def test_survey_changes_nothing(paths):
    _legacy_setup(paths)
    before = sorted(str(p) for p in paths.home.rglob("*"))
    migrate.survey(paths)
    assert sorted(str(p) for p in paths.home.rglob("*")) == before


def test_every_session_survives_the_merge(paths):
    """The whole point. Sessions from both profiles must end up in one place."""
    _legacy_setup(paths)
    migrate.run(paths, now_ms=NOW)

    sessions = sorted(p.name for p in
                      (paths.claude_dir / "projects").rglob("*.jsonl"))
    assert sessions == sorted(
        [f"Admin-{i}.jsonl" for i in range(5)] +
        [f"Work-{i}.jsonl" for i in range(2)])


def test_claude_dir_becomes_a_real_directory(paths):
    _legacy_setup(paths)
    migrate.run(paths, now_ms=NOW)
    assert paths.claude_dir.is_dir()
    assert not paths.claude_dir.is_symlink()


def test_credentials_move_into_the_slim_store(paths):
    _legacy_setup(paths)
    migrate.run(paths, now_ms=NOW)
    for name in ("Admin", "Work"):
        assert paths.credentials(name).exists(), f"{name} lost its login"
        assert json.loads(paths.credentials(name).read_text())["claudeAiOauth"]


def test_credentials_stay_owner_only(paths):
    import stat
    _legacy_setup(paths)
    migrate.run(paths, now_ms=NOW)
    mode = stat.S_IMODE(os.stat(paths.credentials("Admin")).st_mode)
    assert mode == 0o600, oct(mode)


def test_the_active_profile_is_carried_over(paths):
    _legacy_setup(paths, active="Work")
    migrate.run(paths, now_ms=NOW)
    assert state.read_active(paths) == "Work"
    assert state.inspect(paths).kind in (state.MANAGED, state.DRIFTED)


def test_identities_are_preserved(paths):
    _legacy_setup(paths)
    migrate.run(paths, now_ms=NOW)
    assert configjson.read_sidecar(paths.account("Work"))[
        "oauthAccount"]["emailAddress"] == "work@example.com"


def test_a_clash_keeps_the_base_copy(paths):
    """Same filename in both profiles: the base wins and nothing is lost,
    because the base is the profile with the most history."""
    make_legacy_profile(paths, "Admin", email="a@example.com")
    make_legacy_profile(paths, "Work", email="w@example.com")
    for name, body in (("Admin", "richer"), ("Work", "poorer")):
        d = paths.profile_dir(name) / "projects" / "-some-project"
        d.mkdir(parents=True, exist_ok=True)
        (d / "same.jsonl").write_text(body)
    (paths.profile_dir("Admin") / "projects" / "-some-project" /
     "extra.jsonl").write_text("only in admin")
    make_claude_json(paths, email="a@example.com")
    os.symlink(str(paths.profile_dir("Admin")), str(paths.claude_dir),
               target_is_directory=True)

    plan = migrate.run(paths, now_ms=NOW)

    kept = (paths.claude_dir / "projects" / "-some-project" / "same.jsonl")
    assert kept.read_text() == "richer"
    assert plan.skipped_files == 1


def test_running_twice_is_refused(paths):
    _legacy_setup(paths)
    migrate.run(paths, now_ms=NOW)
    with pytest.raises(ShamblesError):
        migrate.run(paths, now_ms=NOW)


def test_switching_after_migration_preserves_history(paths):
    """End to end: migrate, then switch, and confirm the merged history is
    still there afterwards."""
    _legacy_setup(paths)
    migrate.run(paths, now_ms=NOW)
    before = sorted(p.name for p in
                    (paths.claude_dir / "projects").rglob("*.jsonl"))

    switcher.switch(paths, "Work", now_ms_fn=lambda: NOW)

    after = sorted(p.name for p in
                   (paths.claude_dir / "projects").rglob("*.jsonl"))
    assert after == before
    assert state.inspect(paths).profile == "Work"


def test_switch_refuses_while_the_legacy_layout_is_present(paths):
    _legacy_setup(paths)
    with pytest.raises(ShamblesError):
        switcher.switch(paths, "Work", now_ms_fn=lambda: NOW)
