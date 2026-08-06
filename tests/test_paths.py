from pathlib import Path

from shambles.errors import ShamblesError, SymlinkPermissionError
from shambles.paths import Paths


def test_paths_derive_from_home(tmp_path):
    p = Paths.for_home(tmp_path)
    assert p.claude_dir == tmp_path / ".claude"
    assert p.claude_json == tmp_path / ".claude.json"
    assert p.profiles_dir == tmp_path / ".claude-profiles"
    assert p.backup_dir == tmp_path / ".claude-profiles" / ".shambles-backups"
    assert p.live_credentials == tmp_path / ".claude" / ".credentials.json"
    assert p.active_marker == tmp_path / ".claude-profiles" / "active"


def test_profile_store_paths(tmp_path):
    p = Paths.for_home(tmp_path)
    store = tmp_path / ".claude-profiles" / "Work"
    assert p.profile_dir("Work") == store
    assert p.credentials("Work") == store / "credentials.json"
    assert p.account("Work") == store / "account.json"


def test_paths_are_absolute(tmp_path):
    p = Paths.for_home(tmp_path)
    assert p.claude_dir.is_absolute()
    assert p.profile_dir("Work").is_absolute()


def test_real_uses_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert Paths.real().home == tmp_path


def test_every_error_is_a_shambles_error():
    assert issubclass(SymlinkPermissionError, ShamblesError)


def test_the_profile_store_is_owner_only(tmp_path):
    """It holds OAuth refresh tokens. The files are 600, but the directory
    should not be traversable either -- defence in depth, and the old layout
    guaranteed it."""
    import stat
    p = Paths.for_home(tmp_path)
    p.ensure_store()
    mode = stat.S_IMODE((tmp_path / ".claude-profiles").stat().st_mode)
    assert mode == 0o700, oct(mode)


def test_ensure_store_is_idempotent_and_repairs_loose_modes(tmp_path):
    import os
    import stat
    p = Paths.for_home(tmp_path)
    p.ensure_store()
    os.chmod(p.profiles_dir, 0o755)          # as a stray mkdir would leave it
    p.ensure_store()
    assert stat.S_IMODE(p.profiles_dir.stat().st_mode) == 0o700
