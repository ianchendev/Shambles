"""Converting the pre-1.0 layout back to one shared ~/.claude.

The old design gave every account its own copy of ~/.claude, so each had its
own projects/ directory and switching accounts appeared to erase weeks of
session history. These tests pin down that the merge loses nothing.
"""

import json
import os

import pytest

from helpers import (NOW, make_claude_json, make_legacy_profile,
                     make_live_claude_login, make_profile, make_v1_profile)
from shambles import providers as _providers
from shambles import configjson, migrate, state, switcher
from shambles.errors import ShamblesError

#: The pre-1.0 layout predates every other provider; everything it holds is
#: a Claude login.
CLAUDE = _providers.load("claude")
from conftest import posix_modes_only


def _legacy_setup(paths, active="Admin"):
    make_legacy_profile(paths, "Admin", email="admin@example.com", sessions=5)
    make_legacy_profile(paths, "Work", email="work@example.com", sessions=2)
    make_claude_json(paths, email="admin@example.com")
    os.symlink(str((paths.legacy_profiles_dir / active)), str(paths.claude_dir),
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
        assert paths.credentials("claude", name).exists(), f"{name} lost its login"
        assert json.loads(paths.credentials("claude", name).read_text())["claudeAiOauth"]


@posix_modes_only
def test_credentials_stay_owner_only(paths):
    import stat
    _legacy_setup(paths)
    migrate.run(paths, now_ms=NOW)
    mode = stat.S_IMODE(os.stat(paths.credentials("claude", "Admin")).st_mode)
    assert mode == 0o600, oct(mode)


def test_the_active_profile_is_carried_over(paths):
    _legacy_setup(paths, active="Work")
    migrate.run(paths, now_ms=NOW)
    assert state.read_active(paths, "claude") == "Work"
    assert state.inspect(paths, CLAUDE, platform="linux").kind in (state.MANAGED, state.DRIFTED)


def test_identities_are_preserved(paths):
    _legacy_setup(paths)
    migrate.run(paths, now_ms=NOW)
    assert configjson.read_sidecar(paths.account("claude", "Work"))[
        "oauthAccount"]["emailAddress"] == "work@example.com"


def test_a_clash_keeps_the_base_copy(paths):
    """Same filename in both profiles: the base wins and nothing is lost,
    because the base is the profile with the most history."""
    make_legacy_profile(paths, "Admin", email="a@example.com")
    make_legacy_profile(paths, "Work", email="w@example.com")
    for name, body in (("Admin", "richer"), ("Work", "poorer")):
        d = (paths.legacy_profiles_dir / name) / "projects" / "-some-project"
        d.mkdir(parents=True, exist_ok=True)
        (d / "same.jsonl").write_text(body)
    ((paths.legacy_profiles_dir / "Admin") / "projects" / "-some-project" /
     "extra.jsonl").write_text("only in admin")
    make_claude_json(paths, email="a@example.com")
    os.symlink(str((paths.legacy_profiles_dir / "Admin")), str(paths.claude_dir),
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

    switcher.switch(paths, CLAUDE, "Work", platform="linux",
                    now_ms_fn=lambda: NOW, sleep=lambda _: None)

    after = sorted(p.name for p in
                   (paths.claude_dir / "projects").rglob("*.jsonl"))
    assert after == before
    assert state.inspect(paths, CLAUDE, platform="linux").profile == "Work"


def test_switch_refuses_while_the_legacy_layout_is_present(paths):
    _legacy_setup(paths)
    with pytest.raises(ShamblesError):
        switcher.switch(paths, CLAUDE, "Work", platform="linux",
                    now_ms_fn=lambda: NOW, sleep=lambda _: None)


# ---- a symlink is only ours when it points into the old store -----------

def test_a_symlink_of_the_users_own_is_not_the_legacy_layout(paths):
    """Dotfile managers symlink ~/.claude, and so do people who keep it on
    another drive. Treated as the pre-1.0 layout, the window would unlink
    their link at startup and rename a leftover profile directory into its
    place, so Claude Code would open on a directory with none of their
    settings or history in it."""
    real = paths.home / "dotfiles" / "claude"
    (real / "projects").mkdir(parents=True)
    (real / "settings.json").write_text("{}", encoding="utf-8")
    os.symlink(real, paths.claude_dir, target_is_directory=True)
    make_v1_profile(paths, "Work", email="w@example.test")

    assert migrate.needed(paths) is False
    # Asked anyway, the migration refuses rather than converting a home it
    # does not recognise, and neither the link nor what it points at moves.
    with pytest.raises(migrate.MigrationError):
        migrate.run(paths, now_ms=NOW)

    assert paths.claude_dir.is_symlink()
    assert os.readlink(paths.claude_dir) == str(real)
    assert sorted(p.name for p in real.iterdir()) == ["projects", "settings.json"]
    assert (real / "settings.json").read_text(encoding="utf-8") == "{}"
    assert (paths.legacy_profiles_dir / "Work").is_dir()


@pytest.mark.parametrize("target", [
    ".claude-profiles",                    # the old store itself
    ".claude-profiles/Work/projects",      # inside a profile, not a profile
    ".claude-profiles/.shambles-backups",  # in the store, but not a profile
    ".claude-profiles/Gone",               # points at nothing
])
def test_only_a_link_to_a_profile_directory_is_the_legacy_layout(paths, target):
    """The old layout was ~/.claude linked to one profile directory. A link
    that merely passes near the old store, or leads nowhere, is something
    the user made, and converting it would replace their link with a
    directory they did not choose."""
    make_legacy_profile(paths, "Work", email="w@example.test")
    (paths.legacy_profiles_dir / ".shambles-backups").mkdir()
    os.symlink(paths.home / target, paths.claude_dir, target_is_directory=True)

    assert migrate.needed(paths) is False


def test_a_relative_link_into_the_old_store_is_still_the_legacy_layout(paths):
    """How the link is spelled must not hide the old layout, or the split
    session history it causes would never be merged."""
    make_legacy_profile(paths, "Work", email="w@example.test")
    os.symlink(os.path.join(".claude-profiles", "Work"), paths.claude_dir,
               target_is_directory=True)

    assert migrate.needed(paths) is True


def test_switching_works_through_a_symlink_of_the_users_own(paths):
    """With ~/.claude symlinked by the user, every switch was refused with
    "still a symlink from an older version of Shambles", and no migration
    could ever clear it because there was nothing to migrate."""
    real = paths.home / "dotfiles" / "claude"
    real.mkdir(parents=True)
    os.symlink(real, paths.claude_dir, target_is_directory=True)
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    make_claude_json(paths, email="w@example.test")
    make_live_claude_login(paths, access_token="tok-Work")

    switcher.switch(paths, CLAUDE, "Personal", platform="linux",
                    sleep=lambda _: None)

    assert state.read_active(paths, "claude") == "Personal"


# ---- migration happens on sight, not on request -------------------------

def test_app_migrates_on_startup_without_asking(paths, make_app, monkeypatch):
    """The old layout hid session history. There is no version of that anyone
    wants, so opening the window fixes it rather than offering to."""
    from shambles import gui

    shown = []
    monkeypatch.setattr(gui.messagebox, "showinfo",
                        lambda *a, **k: shown.append(a))
    monkeypatch.setattr(gui.messagebox, "showerror",
                        lambda *a, **k: shown.append(a))

    _legacy_setup(paths)
    assert migrate.needed(paths)

    app = make_app(paths)
    app.update()

    assert not migrate.needed(paths), "startup left the broken layout in place"
    assert paths.claude_dir.is_dir() and not paths.claude_dir.is_symlink()
    sessions = sorted(p.name for p in
                      (paths.claude_dir / "projects").rglob("*.jsonl"))
    assert len(sessions) == 7, "history was not merged"
    assert state.inspect(paths, CLAUDE, platform="linux").kind == state.MANAGED


def test_startup_migration_reports_what_it_did(paths, make_app, monkeypatch):
    from shambles import gui

    shown = []
    monkeypatch.setattr(gui.messagebox, "showinfo",
                        lambda *a, **k: shown.append(" ".join(str(x) for x in a)))
    _legacy_setup(paths)
    app = make_app(paths)
    app.update()

    assert shown, "migration happened silently"
    assert "2" in shown[0], "did not say how many sessions it merged"


def test_startup_is_untouched_when_no_migration_is_needed(paths, make_app,
                                                          monkeypatch):
    from shambles import gui
    from helpers import make_claude_json, make_live_claude_login, make_profile

    shown = []
    monkeypatch.setattr(gui.messagebox, "showinfo",
                        lambda *a, **k: shown.append(a))
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    assert not shown, "showed a migration dialog with nothing to migrate"


# ---- everything machine-scoped comes across, not just projects/ ---------

def test_plugins_installed_under_another_profile_survive(paths):
    """Ian's second profile only ever held PID lock files, so nothing real was
    stranded. Someone who installed a plugin under their second account would
    lose it, which is the same class of bug as the split history."""
    _legacy_setup(paths)
    only_there = ((paths.legacy_profiles_dir / "Work") / "plugins" / "repos" / "acme")
    only_there.mkdir(parents=True)
    (only_there / "plugin.js").write_text("installed under Work")

    migrate.run(paths, now_ms=NOW)

    assert (paths.claude_dir / "plugins" / "repos" / "acme" /
            "plugin.js").read_text() == "installed under Work"


def test_prompt_history_from_both_profiles_is_merged(paths):
    _legacy_setup(paths)
    ((paths.legacy_profiles_dir / "Admin") / "history.jsonl").write_text(
        '{"display": "from admin", "timestamp": 100}\n')
    ((paths.legacy_profiles_dir / "Work") / "history.jsonl").write_text(
        '{"display": "from work", "timestamp": 200}\n')

    migrate.run(paths, now_ms=NOW)

    lines = [json.loads(l) for l in
             (paths.claude_dir / "history.jsonl").read_text().splitlines() if l]
    assert [e["display"] for e in lines] == ["from admin", "from work"]


def test_duplicate_prompt_history_is_not_doubled(paths):
    _legacy_setup(paths)
    entry = '{"display": "same command", "timestamp": 100}\n'
    ((paths.legacy_profiles_dir / "Admin") / "history.jsonl").write_text(entry)
    ((paths.legacy_profiles_dir / "Work") / "history.jsonl").write_text(entry)

    migrate.run(paths, now_ms=NOW)

    lines = [l for l in
             (paths.claude_dir / "history.jsonl").read_text().splitlines() if l]
    assert len(lines) == 1


def test_the_stale_shambles_sidecar_is_cleared_from_claude(paths):
    """The old layout left Shambles' own sidecar inside ~/.claude. Once the
    identity lives in the profile store it is redundant, and ~/.claude should
    look exactly like a stock install."""
    _legacy_setup(paths)
    assert ((paths.legacy_profiles_dir / "Admin") / ".shambles.json").exists()

    migrate.run(paths, now_ms=NOW)

    assert not (paths.claude_dir / ".shambles.json").exists()
    # but the identity it carried is not lost
    assert configjson.read_sidecar(paths.account("claude", "Admin")).get("oauthAccount")
