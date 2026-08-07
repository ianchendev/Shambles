import json

import pytest

from helpers import make_v1_profile
from shambles import migrate


def test_not_needed_when_there_is_no_old_store(paths):
    assert migrate.store_migration_needed(paths) is False


def test_not_needed_once_the_new_store_exists(paths):
    """Having migrated already is not a reason to migrate again, even though
    the source is deliberately left on disk."""
    make_v1_profile(paths, "Work")
    paths.ensure_store()
    assert migrate.store_migration_needed(paths) is False


def test_needed_when_only_the_old_store_exists(paths):
    make_v1_profile(paths, "Work")
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


def test_a_marker_naming_a_missing_profile_is_not_carried_over(paths):
    """A stale marker in the old store must not become a stale marker in the
    new one -- MISSING_PROFILE would then be reported on a fresh layout."""
    make_v1_profile(paths, "Work")
    paths.legacy_active_marker.write_text("Ghost\n", encoding="utf-8")

    plan = migrate.migrate_store(paths)

    assert plan.active is None
    assert not paths.active_marker("claude").exists()
