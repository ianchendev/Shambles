from pathlib import Path

from shambles.errors import ShamblesError, SymlinkPermissionError
from shambles.paths import Paths


def test_paths_derive_from_home(tmp_path):
    p = Paths.for_home(tmp_path)
    assert p.claude_dir == tmp_path / ".claude"
    assert p.claude_json == tmp_path / ".claude.json"
    assert p.profiles_dir == tmp_path / ".claude-profiles"
    assert p.backup_dir == tmp_path / ".claude-profiles" / ".shambles-backups"
    assert p.tmp_link == tmp_path / ".claude.shambles-tmp"


def test_profile_and_sidecar_paths(tmp_path):
    p = Paths.for_home(tmp_path)
    assert p.profile_dir("Work") == tmp_path / ".claude-profiles" / "Work"
    assert p.sidecar("Work") == tmp_path / ".claude-profiles" / "Work" / ".shambles.json"


def test_paths_are_absolute(tmp_path):
    p = Paths.for_home(tmp_path)
    assert p.claude_dir.is_absolute()
    assert p.profile_dir("Work").is_absolute()


def test_real_uses_home(monkeypatch, tmp_path):
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    assert Paths.real().home == tmp_path


def test_every_error_is_a_shambles_error():
    assert issubclass(SymlinkPermissionError, ShamblesError)
