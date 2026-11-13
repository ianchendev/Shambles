"""Converting the pre-1.0 layout back to one shared ~/.claude.

The old design gave every account its own copy of ~/.claude, so each had its
own projects/ directory and switching accounts appeared to erase weeks of
session history. These tests pin down that the merge loses nothing.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from helpers import (NOW, account, credentials, make_claude_json,
                     make_legacy_profile, make_live_claude_login, make_profile,
                     make_v1_profile, write_json)
from shambles import providers as _providers
from shambles import configjson, migrate, state, switcher
from shambles.errors import ShamblesError
from shambles.stores import FileStore, StoreUnavailableError

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
    # Compared with itself afterwards, not with str(real): Windows reports a
    # link's target in its extended \\?\ form.
    link = os.readlink(paths.claude_dir)

    assert migrate.needed(paths) is False
    # Asked anyway, the migration refuses rather than converting a home it
    # does not recognise, and neither the link nor what it points at moves.
    with pytest.raises(migrate.MigrationError):
        migrate.run(paths, now_ms=NOW)

    assert paths.claude_dir.is_symlink()
    assert os.readlink(paths.claude_dir) == link
    assert sorted(p.name for p in real.iterdir()) == ["projects", "settings.json"]
    assert (real / "settings.json").read_text(encoding="utf-8") == "{}"
    assert (paths.legacy_profiles_dir / "Work").is_dir()


@pytest.mark.parametrize("target", [
    ".claude-profiles",                    # the old store itself
    ".claude-profiles/Work/projects",      # inside a profile, not a profile
    ".claude-profiles/.shambles-backups",  # in the store, but not a profile
])
def test_only_a_link_to_a_profile_directory_is_the_legacy_layout(paths, target):
    """The old layout was ~/.claude linked to one profile directory. A link
    that merely passes near the old store is something the user made, and
    converting it would replace their link with a directory they did not
    choose. (A link to a profile that has since been removed is a different
    matter: see test_dangling_link_does_not_strand_pre_1_0_logins.)"""
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


# ---- a migration that was cut short can be finished ---------------------

def _linked_to_work(paths):
    """Work and Personal in the old layout, ~/.claude linked to Work.

    Each holds its own token. The stock builder gives every legacy profile
    the same bytes, and a test comparing identical blobs could not tell a
    correct copy from two accounts' logins changing places.
    """
    make_legacy_profile(paths, "Work", email="w@example.test", sessions=3)
    make_legacy_profile(paths, "Personal", email="p@example.test", sessions=1)
    for name in ("Work", "Personal"):
        write_json(_old_login(paths, name),
                   credentials(access_token=f"old-{name}"))
    os.symlink(paths.legacy_profiles_dir / "Work", paths.claude_dir,
               target_is_directory=True)
    make_claude_json(paths, email="w@example.test")


def _old_login(paths, name):
    return paths.legacy_profiles_dir / name / ".credentials.json"


def _fails(error):
    def fail(*args, **kwargs):
        raise error
    return fail


def test_an_interrupted_legacy_migration_can_be_finished(paths, monkeypatch):
    """A full disk or a crash partway through used to leave ~/.claude
    converted but the other accounts' logins never copied across. Nothing
    retried it, so those accounts came back as empty profiles and each one
    needed a new verification email."""
    _linked_to_work(paths)
    work = _old_login(paths, "Work").read_bytes()
    personal = _old_login(paths, "Personal").read_bytes()

    real = configjson.write_sidecar
    calls = {"n": 0}

    def dies_once(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("disk full")
        return real(*args, **kwargs)

    monkeypatch.setattr(configjson, "write_sidecar", dies_once)
    with pytest.raises(migrate.MigrationError):
        migrate.run(paths, now_ms=NOW)

    # Next start-up: the window asks again, and must still be told yes.
    assert migrate.needed(paths), "the failed attempt disarmed its own retry"
    migrate.run(paths, now_ms=NOW)

    assert paths.credentials("claude", "Personal").read_bytes() == personal
    assert paths.credentials("claude", "Work").read_bytes() == work
    assert paths.claude_dir.is_dir() and not paths.claude_dir.is_symlink()
    for name, email in (("Work", "w@example.test"),
                        ("Personal", "p@example.test")):
        assert configjson.read_sidecar(paths.account("claude", name))[
            "oauthAccount"]["emailAddress"] == email
    assert state.read_active(paths, "claude") == "Work"


@pytest.mark.parametrize("owner, attribute, error", [
    (migrate, "_merge_tree", OSError("disk full")),         # merging history
    (FileStore, "write", StoreUnavailableError("disk full")),  # a login
    (configjson, "write_sidecar", OSError("disk full")),    # an identity
    (state, "write_active", OSError("disk full")),          # who is signed in
])
def test_a_failure_before_the_swap_is_a_message_and_is_retried(
        paths, monkeypatch, owner, attribute, error):
    """The window only knows how to show a ShamblesError. A bare OSError
    from a full disk was a traceback at startup, and it arrived after
    ~/.claude had already been converted, so nothing ever tried again."""
    _linked_to_work(paths)
    link = os.readlink(paths.claude_dir)
    logins = {name: _old_login(paths, name).read_bytes()
              for name in ("Work", "Personal")}

    with monkeypatch.context() as patch:
        patch.setattr(owner, attribute, _fails(error))
        with pytest.raises(migrate.MigrationError) as caught:
            migrate.run(paths, now_ms=NOW)

    assert "Nothing was deleted" in str(caught.value)
    assert os.readlink(paths.claude_dir) == link
    assert migrate.needed(paths)

    migrate.run(paths, now_ms=NOW)
    for name, login in logins.items():
        assert paths.credentials("claude", name).read_bytes() == login, name
    assert not paths.claude_dir.is_symlink()


def test_a_login_already_in_the_new_store_is_not_overwritten(paths):
    """A profile already saved under the same name in the new store holds
    the login that has been kept current. The copy in the old directory
    stopped being refreshed the day it was left behind, so writing it over
    the saved one swaps a working token for a dead one, and the account
    needs a new verification email."""
    _linked_to_work(paths)
    make_profile(paths, "claude", "Personal", email="current@example.test")
    kept = paths.credentials("claude", "Personal").read_bytes()
    assert kept != _old_login(paths, "Personal").read_bytes()

    migrate.run(paths, now_ms=NOW)

    assert paths.credentials("claude", "Personal").read_bytes() == kept
    # The label stays with the token it describes. The old directory's
    # address belongs to the login that was not kept.
    assert configjson.read_sidecar(paths.account("claude", "Personal"))[
        "oauthAccount"]["emailAddress"] == "current@example.test"


def test_an_identity_already_in_the_new_store_is_not_erased(paths):
    """An old profile with no sidecar has no identity to bring. Filing that
    nothing over an identity the new store already holds would list the
    account without its address, which is the only thing telling two
    accounts apart."""
    make_legacy_profile(paths, "Work", email="w@example.test", sessions=3)
    make_legacy_profile(paths, "Personal", sessions=1)   # no .shambles.json
    os.symlink(paths.legacy_profiles_dir / "Work", paths.claude_dir,
               target_is_directory=True)
    make_claude_json(paths, email="w@example.test")
    write_json(paths.account("claude", "Personal"),
               {"oauthAccount": account("p@example.test"), "stashed_at": NOW})

    migrate.run(paths, now_ms=NOW)

    assert configjson.read_sidecar(paths.account("claude", "Personal"))[
        "oauthAccount"]["emailAddress"] == "p@example.test"
    assert (paths.credentials("claude", "Personal").read_bytes()
            == _old_login(paths, "Personal").read_bytes())


def test_a_login_refreshed_between_attempts_is_the_one_filed(paths,
                                                             monkeypatch):
    """After a failed attempt Claude Code carries on through the old link
    and refreshes the linked account's token. A copy filed early by the
    failed attempt would be the superseded one, and it would win over the
    fresh one on the retry. The linked account is therefore filed last."""
    make_legacy_profile(paths, "Alpha", email="a@example.test", sessions=1)
    make_legacy_profile(paths, "Beta", email="b@example.test", sessions=3)
    os.symlink(paths.legacy_profiles_dir / "Alpha", paths.claude_dir,
               target_is_directory=True)
    make_claude_json(paths, email="a@example.test")

    with monkeypatch.context() as patch:
        patch.setattr(configjson, "write_sidecar", _fails(OSError("disk full")))
        with pytest.raises(migrate.MigrationError):
            migrate.run(paths, now_ms=NOW)

    write_json(_old_login(paths, "Alpha"),
               credentials(access_token="refreshed"))
    refreshed = _old_login(paths, "Alpha").read_bytes()
    migrate.run(paths, now_ms=NOW)

    assert paths.credentials("claude", "Alpha").read_bytes() == refreshed


def test_a_failed_swap_puts_the_link_back_and_is_retried(paths, monkeypatch):
    """If the merged directory cannot be moved into place, ~/.claude must
    not be left missing: Claude Code would start as a fresh install."""
    _linked_to_work(paths)
    link = os.readlink(paths.claude_dir)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", _fails(OSError("device busy")))
        with pytest.raises(migrate.MigrationError, match="was restored"):
            migrate.run(paths, now_ms=NOW)

    assert os.readlink(paths.claude_dir) == link
    assert migrate.needed(paths)

    migrate.run(paths, now_ms=NOW)
    assert paths.claude_dir.is_dir() and not paths.claude_dir.is_symlink()
    assert paths.credentials("claude", "Personal").exists()


def test_a_swap_that_cannot_be_undone_says_where_the_files_are(paths,
                                                               monkeypatch):
    """Windows can refuse to create a symlink. If the link cannot be put
    back either, the user has no ~/.claude at all, and the one useful thing
    left to tell them is where their files still are."""
    _linked_to_work(paths)
    link = os.readlink(paths.claude_dir)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "rename", _fails(OSError("device busy")))
        patch.setattr(os, "symlink", _fails(OSError("not permitted")))
        with pytest.raises(migrate.MigrationError) as caught:
            migrate.run(paths, now_ms=NOW)

    assert link in str(caught.value)
    assert (paths.legacy_profiles_dir / "Work" / "projects").is_dir()


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


def test_prompt_history_that_is_not_valid_text_does_not_stop_the_migration(
        paths):
    """history.jsonl is appended to by a program that can be killed mid-write,
    so its last line can end inside a multi-byte character. Reading it as
    text raised UnicodeDecodeError, which is not a ShamblesError: a traceback
    at every start, the layout never converted, and every Claude switch
    refused for good. The promise is that unparseable lines are carried
    across verbatim, and bytes are the only way to keep it."""
    make_legacy_profile(paths, "Work", email="w@example.test", sessions=2)
    make_legacy_profile(paths, "Personal", email="p@example.test", sessions=1)
    os.symlink(paths.legacy_profiles_dir / "Work", paths.claude_dir,
               target_is_directory=True)
    torn = b'{"display": "caf\xc3'
    (paths.legacy_profiles_dir / "Work" / "history.jsonl").write_bytes(
        b'{"display": "one"}\n')
    (paths.legacy_profiles_dir / "Personal" / "history.jsonl").write_bytes(
        b'{"display": "two"}\n' + torn + b"\n")

    migrate.run(paths, now_ms=NOW)

    merged = (paths.claude_dir / "history.jsonl").read_bytes().splitlines()
    assert merged == [b'{"display": "one"}', b'{"display": "two"}', torn]
    assert paths.credentials("claude", "Personal").exists()


def test_a_line_separator_inside_a_prompt_does_not_split_the_line(paths):
    """JSON allows U+2028 unescaped inside a string. str.splitlines treats it
    as a line break, so merging cut that entry in two and neither half was
    JSON any more."""
    make_legacy_profile(paths, "Work", email="w@example.test", sessions=2)
    make_legacy_profile(paths, "Personal", email="p@example.test", sessions=1)
    os.symlink(paths.legacy_profiles_dir / "Work", paths.claude_dir,
               target_is_directory=True)
    entry = '{"display": "first second"}'
    (paths.legacy_profiles_dir / "Work" / "history.jsonl").write_text(
        '{"display": "one"}\n', encoding="utf-8")
    (paths.legacy_profiles_dir / "Personal" / "history.jsonl").write_text(
        entry + "\n", encoding="utf-8")

    migrate.run(paths, now_ms=NOW)

    merged = (paths.claude_dir / "history.jsonl").read_text(encoding="utf-8")
    assert merged == '{"display": "one"}\n' + entry + "\n"


def test_a_profile_that_was_signed_out_stays_signed_out(paths):
    """The link pointed at a profile with no login; the richest profile has
    one. The merged directory is the richest profile's, login included, so
    without care the conversion signs the user in as an account they were
    not using. Its login is in the store; the live slot is left empty."""
    make_legacy_profile(paths, "Rich", email="rich@example.test", sessions=4)
    make_legacy_profile(paths, "Linked", email="linked@example.test",
                        sessions=1)
    rich = (paths.legacy_profiles_dir / "Rich" / ".credentials.json").read_bytes()
    (paths.legacy_profiles_dir / "Linked" / ".credentials.json").unlink()
    os.symlink(paths.legacy_profiles_dir / "Linked", paths.claude_dir,
               target_is_directory=True)
    make_claude_json(paths, email="linked@example.test")

    migrate.run(paths, now_ms=NOW)

    assert not (paths.claude_dir / ".credentials.json").exists()
    assert paths.credentials("claude", "Rich").read_bytes() == rich
    assert state.read_active(paths, "claude") == "Linked"


def test_the_marker_follows_the_login_when_the_linked_one_cannot_be_installed(
        paths, monkeypatch):
    """After the swap the live login is the richest profile's. If the linked
    profile's cannot be written over it, the marker must not go on naming
    the linked profile: marker and live login have to name one account, or
    the next switch files one account's token under the other's name."""
    make_legacy_profile(paths, "Rich", email="rich@example.test", sessions=4)
    make_legacy_profile(paths, "Linked", email="linked@example.test",
                        sessions=1)
    write_json(paths.legacy_profiles_dir / "Rich" / ".credentials.json",
               credentials(access_token="old-Rich"))
    write_json(paths.legacy_profiles_dir / "Linked" / ".credentials.json",
               credentials(access_token="old-Linked"))
    rich = (paths.legacy_profiles_dir / "Rich" / ".credentials.json").read_bytes()
    os.symlink(paths.legacy_profiles_dir / "Linked", paths.claude_dir,
               target_is_directory=True)
    make_claude_json(paths, email="linked@example.test")

    real = FileStore.write

    def refuses_the_live_slot(store, blob):
        if store.path == paths.claude_dir / ".credentials.json":
            raise StoreUnavailableError("the file is in use")
        return real(store, blob)

    monkeypatch.setattr(FileStore, "write", refuses_the_live_slot)
    migrate.run(paths, now_ms=NOW)

    assert (paths.claude_dir / ".credentials.json").read_bytes() == rich
    assert state.read_active(paths, "claude") == "Rich"
