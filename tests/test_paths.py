import os

import pytest

from conftest import posix_modes_only
from shambles.paths import Paths


def test_every_path_derives_from_the_injected_home(tmp_path):
    paths = Paths.for_home(tmp_path)
    assert paths.library_dir == tmp_path / ".shambles"
    assert paths.provider_dir("claude") == tmp_path / ".shambles" / "claude"
    assert paths.profile_dir("codex", "Work") == tmp_path / ".shambles" / "codex" / "Work"
    assert paths.credentials("codex", "Work") == \
        tmp_path / ".shambles" / "codex" / "Work" / "credentials.json"
    assert paths.account("claude", "Work") == \
        tmp_path / ".shambles" / "claude" / "Work" / "account.json"
    assert paths.active_marker("codex") == tmp_path / ".shambles" / "codex" / "active"
    assert paths.backup_dir == tmp_path / ".shambles" / ".backups"


def test_two_providers_never_collide(tmp_path):
    """The whole point of the provider hop: same profile name, different
    account, no shared bytes."""
    paths = Paths.for_home(tmp_path)
    assert paths.credentials("claude", "Work") != paths.credentials("codex", "Work")


def test_legacy_paths_point_at_the_old_layout(tmp_path):
    paths = Paths.for_home(tmp_path)
    assert paths.legacy_profiles_dir == tmp_path / ".claude-profiles"
    assert paths.legacy_active_marker == tmp_path / ".claude-profiles" / "active"
    assert paths.legacy_backup_dir == tmp_path / ".claude-profiles" / ".shambles-backups"


@posix_modes_only
def test_the_store_and_every_level_below_it_is_owner_only(tmp_path):
    """It holds OAuth refresh tokens. A plain mkdir under the usual 022 umask
    would leave these 755."""
    paths = Paths.for_home(tmp_path)
    paths.ensure_profile("codex", "Work")
    for directory in (paths.library_dir, paths.provider_dir("codex"),
                      paths.profile_dir("codex", "Work")):
        assert oct(os.stat(directory).st_mode)[-3:] == "700"


def test_ensure_profile_is_idempotent(tmp_path):
    paths = Paths.for_home(tmp_path)
    first = paths.ensure_profile("claude", "Work")
    second = paths.ensure_profile("claude", "Work")
    assert first == second and first.is_dir()
