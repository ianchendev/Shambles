import json
import os
import shutil
import stat

import pytest

from conftest import posix_modes_only
from helpers import credentials, make_profile, make_v1_profile, write_json
from shambles import migrate, settings, state


def test_not_needed_when_there_is_no_old_store(paths):
    assert migrate.store_migration_needed(paths) is False


def test_not_needed_once_the_new_store_exists(paths):
    """Having migrated already is not a reason to migrate again, even though
    the source is deliberately left on disk."""
    make_v1_profile(paths, "Work")
    migrate.migrate_store(paths)
    assert migrate.store_migration_needed(paths) is False


def test_needed_when_only_the_old_store_exists(paths):
    make_v1_profile(paths, "Work")
    assert migrate.store_migration_needed(paths) is True


def test_a_setting_saved_first_does_not_strand_the_old_profiles(paths):
    """Turning update checks on before the window first opened created
    ~/.shambles, which read as "already migrated". The window then opened
    empty, with every saved account still sitting in the old store."""
    make_v1_profile(paths, "Work", email="w@example.test", active=True)
    settings.set_update_check(paths, True)

    assert migrate.store_migration_needed(paths) is True


def test_a_codex_account_saved_first_does_not_strand_the_old_profiles(paths):
    """Every v1.0 profile is a Claude login. A Codex account in the new
    store says nothing about whether those were ever brought across."""
    make_v1_profile(paths, "Work", email="w@example.test", active=True)
    make_profile(paths, "codex", "Side", email="s@example.test")

    assert migrate.store_migration_needed(paths) is True


def test_profiles_land_under_the_claude_provider(paths):
    make_v1_profile(paths, "Work", email="w@example.com", active=True)
    make_v1_profile(paths, "Personal", email="p@example.com")

    plan = migrate.migrate_store(paths)

    assert sorted(plan.profiles) == ["Personal", "Work"]
    assert plan.active == "Work"
    assert paths.credentials("claude", "Work").is_file()
    assert paths.account("claude", "Personal").is_file()
    assert paths.active_marker("claude").read_text(encoding="utf-8").strip() == "Work"


def test_the_credential_is_copied_byte_for_byte(paths):
    """The whole product promise. A migration that alters a refresh token
    costs the user a verification email."""
    make_v1_profile(paths, "Work")
    before = (paths.legacy_profiles_dir / "Work" / "credentials.json").read_bytes()

    migrate.migrate_store(paths)

    assert paths.credentials("claude", "Work").read_bytes() == before


def test_the_old_store_is_left_untouched(paths):
    make_v1_profile(paths, "Work", email="w@example.com", active=True)

    migrate.migrate_store(paths)

    assert (paths.legacy_profiles_dir / "Work" / "credentials.json").is_file()
    assert paths.legacy_active_marker.is_file()


def test_backups_come_across(paths):
    make_v1_profile(paths, "Work")
    paths.legacy_backup_dir.mkdir(parents=True, exist_ok=True)
    (paths.legacy_backup_dir / "claude.json.1785000000000").write_text("{}", encoding="utf-8")

    plan = migrate.migrate_store(paths)

    assert plan.backups == 1
    assert (paths.backup_dir / "claude.json.1785000000000").is_file()


def test_running_twice_changes_nothing(paths):
    make_v1_profile(paths, "Work", email="w@example.com", active=True)
    migrate.migrate_store(paths)
    paths.credentials("claude", "Work").write_text('{"edited": true}', encoding="utf-8")

    migrate.migrate_store(paths)

    assert json.loads(paths.credentials("claude", "Work").read_text()) == {"edited": True}


# ---- a copy that was cut short is started again -------------------------

class Killed(BaseException):
    """The process ending mid-copy. Not an Exception, so nothing in the code
    under test can catch it and tidy up, exactly as nothing could."""


def _alpha_and_beta(paths):
    """Two v1.0 profiles, each with its own token so a copy that swapped
    them could not pass, and Alpha marked active."""
    for name in ("Alpha", "Beta"):
        make_v1_profile(paths, name, email=f"{name.lower()}@example.test",
                        active=(name == "Alpha"))
        write_json(paths.legacy_profiles_dir / name / "credentials.json",
                   credentials(access_token=f"old-{name}"))
    return {name: (paths.legacy_profiles_dir / name
                   / "credentials.json").read_bytes()
            for name in ("Alpha", "Beta")}


def _dies_on_call(number, error):
    real = shutil.copy2
    calls = {"n": 0}

    def copy(src, dst, **kwargs):
        calls["n"] += 1
        if calls["n"] == number:
            raise error
        return real(src, dst, **kwargs)
    return copy


def _staging_left(paths):
    return sorted(p.name for p in paths.library_dir.iterdir()
                  if "migrating" in p.name)


def test_an_interrupted_store_migration_is_resumed(paths, monkeypatch):
    """A full disk partway through the copy left the new store looking
    finished with some accounts missing. Nothing tried again, so those
    accounts were gone from the window, and the failure itself reached the
    user as a traceback instead of a message."""
    logins = _alpha_and_beta(paths)

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "copy2", _dies_on_call(2, OSError("disk full")))
        with pytest.raises(migrate.MigrationError) as caught:
            migrate.migrate_store(paths)

    message = str(caught.value)
    assert "Nothing was deleted" in message
    assert str(paths.legacy_profiles_dir) in message
    # The new store must not exist half-made: its existence is what says
    # "done", so until then the window has to keep asking.
    assert not paths.provider_dir("claude").exists()
    assert migrate.store_migration_needed(paths)

    migrate.migrate_store(paths)

    for name, login in logins.items():
        assert paths.credentials("claude", name).read_bytes() == login, name
    assert state.read_active(paths, "claude") == "Alpha"
    assert not migrate.store_migration_needed(paths)
    assert _staging_left(paths) == []


def test_a_copy_that_died_leaves_nothing_the_next_one_trusts(paths,
                                                             monkeypatch):
    """A crash cannot clean up after itself. Whatever it had copied so far
    must neither count as the finished store nor be folded into the next
    attempt, or an account from a half-made copy would be listed as saved."""
    logins = _alpha_and_beta(paths)

    with monkeypatch.context() as patch:
        patch.setattr(shutil, "copy2", _dies_on_call(3, Killed()))
        with pytest.raises(Killed):
            migrate.migrate_store(paths)

    assert not paths.provider_dir("claude").exists()
    assert migrate.store_migration_needed(paths)
    assert _staging_left(paths), "the crash was expected to leave its copy"
    # Something only the dead attempt knew about.
    ghost = paths.library_dir / _staging_left(paths)[0] / "Ghost"
    ghost.mkdir()

    migrate.migrate_store(paths)

    assert sorted(state.profile_names(paths, "claude")) == ["Alpha", "Beta"]
    for name, login in logins.items():
        assert paths.credentials("claude", name).read_bytes() == login, name
    assert _staging_left(paths) == []


def test_two_windows_migrating_at_once_cannot_leave_an_account_out(
        paths, monkeypatch):
    """Opening Shambles twice in quick succession runs this copy twice at
    the same moment. If the two shared one staging directory, the second
    clearing it as a leftover would empty what the first was about to move
    into place, and the store would appear, finished, with accounts
    missing."""
    logins = _alpha_and_beta(paths)
    real = shutil.copy2
    calls = {"n": 0}

    def copy(src, dst, **kwargs):
        calls["n"] += 1
        if calls["n"] == 3:
            # The other window, start to finish, while this one is mid-copy.
            migrate.migrate_store(paths)
        return real(src, dst, **kwargs)

    monkeypatch.setattr(shutil, "copy2", copy)
    # The slower window finds the store already in place and says so. It
    # does not promise a retry, because none is needed.
    with pytest.raises(migrate.MigrationError) as caught:
        migrate.migrate_store(paths)
    assert "try again" not in str(caught.value)

    assert sorted(state.profile_names(paths, "claude")) == ["Alpha", "Beta"]
    for name, login in logins.items():
        assert paths.credentials("claude", name).read_bytes() == login, name
    assert state.read_active(paths, "claude") == "Alpha"
    assert _staging_left(paths) == []


def test_a_failed_copy_into_an_existing_store_is_a_message_too(paths,
                                                               monkeypatch):
    """Whichever way the copy runs, a failure has to reach the user as
    something the window can show."""
    _alpha_and_beta(paths)
    paths.ensure_provider("claude")
    monkeypatch.setattr(shutil, "copy2", _dies_on_call(1, OSError("disk full")))

    with pytest.raises(migrate.MigrationError) as caught:
        migrate.migrate_store(paths)

    assert "Nothing was deleted" in str(caught.value)
    # No promise to try again: the store exists, so the window will not ask.
    assert "try again" not in str(caught.value)


@posix_modes_only
def test_the_migrated_store_is_owner_only(paths):
    """Every file in it is a refresh token or says whose token it is."""
    _alpha_and_beta(paths)

    migrate.migrate_store(paths)

    store = paths.provider_dir("claude")
    for path in [paths.library_dir, store, *store.rglob("*")]:
        mode = stat.S_IMODE(os.stat(path).st_mode)
        assert mode == (0o700 if path.is_dir() else 0o600), (path, oct(mode))


def test_a_marker_naming_a_missing_profile_is_not_carried_over(paths):
    """A stale marker in the old store must not become a stale marker in the
    new one -- MISSING_PROFILE would then be reported on a fresh layout."""
    make_v1_profile(paths, "Work")
    paths.legacy_active_marker.write_text("Ghost\n", encoding="utf-8")

    plan = migrate.migrate_store(paths)

    assert plan.active is None
    assert not paths.active_marker("claude").exists()


def test_an_old_marker_that_is_not_text_does_not_stop_the_migration(paths):
    """A torn write to the old `active` file. Reading it raised
    UnicodeDecodeError past every handler, at every start, with the new store
    never appearing. It names nobody, so no profile is carried over as
    active and everything else comes across."""
    make_v1_profile(paths, "Work", email="w@example.test")
    paths.legacy_active_marker.write_bytes(b"\xff\xfe\xfa")

    plan = migrate.migrate_store(paths)

    assert plan.profiles == ["Work"]
    assert plan.active is None
    assert paths.credentials("claude", "Work").exists()
    assert not migrate.store_migration_needed(paths)
