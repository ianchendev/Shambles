import os

import pytest

from helpers import NOW, credentials, make_claude_json, write_json
from shambles import configjson, links, switcher
from shambles.errors import (AlreadyManagedError, ForeignLinkError,
                             ProfileNameError, ShamblesError,
                             SymlinkPermissionError)


def _clock():
    return NOW


def _no_sleep(_seconds):
    pass


def _live_claude_dir(paths):
    """A real ~/.claude, as it exists before Shambles has ever run."""
    d = paths.claude_dir
    d.mkdir(parents=True)
    write_json(d / ".credentials.json", credentials())
    write_json(d / "settings.json", {"model": "opus"})
    (d / "projects").mkdir()
    make_claude_json(paths, email="live@example.com")
    return d


def _save(paths, name):
    return switcher.save_current_account(paths, name,
                                         now_ms_fn=_clock, sleep=_no_sleep)


def test_moves_the_directory_and_leaves_a_symlink(paths):
    _live_claude_dir(paths)
    assert _save(paths, "Default") == "Default"

    state = links.inspect(paths)
    assert state.kind == links.MANAGED
    assert state.profile == "Default"
    assert os.path.isabs(os.readlink(paths.claude_dir))


def test_contents_arrive_intact(paths):
    _live_claude_dir(paths)
    _save(paths, "Default")

    moved = paths.profile_dir("Default")
    assert (moved / ".credentials.json").exists()
    assert (moved / "settings.json").exists()
    assert (moved / "projects").is_dir()
    # and it is reachable through the link
    assert (paths.claude_dir / "settings.json").exists()


def test_stashes_the_current_identity_into_the_sidecar(paths):
    _live_claude_dir(paths)
    _save(paths, "Default")
    stashed = configjson.read_sidecar(paths.sidecar("Default"))
    assert stashed["oauthAccount"]["emailAddress"] == "live@example.com"


def test_trims_the_name(paths):
    _live_claude_dir(paths)
    assert _save(paths, "  Work  ") == "Work"
    assert paths.profile_dir("Work").is_dir()


def test_rejects_a_bad_name_before_moving_anything(paths):
    _live_claude_dir(paths)
    with pytest.raises(ProfileNameError):
        _save(paths, "bad/name")
    assert paths.claude_dir.is_dir()
    assert not paths.claude_dir.is_symlink()


# ---- the rollback -------------------------------------------------------

def test_rolls_back_when_symlink_creation_fails(paths, monkeypatch):
    """If os.symlink fails after the move, an un-rolled-back failure would
    leave the user with no ~/.claude at all."""
    _live_claude_dir(paths)

    def blocked(*_args, **_kwargs):
        err = OSError("privilege not held")
        err.winerror = 1314
        raise err

    monkeypatch.setattr(switcher.os, "symlink", blocked)

    with pytest.raises(SymlinkPermissionError) as exc:
        _save(paths, "Default")

    assert "Developer Mode" in str(exc.value)
    assert paths.claude_dir.is_dir()
    assert not paths.claude_dir.is_symlink()
    assert (paths.claude_dir / ".credentials.json").exists()
    assert (paths.claude_dir / "settings.json").exists()
    assert not paths.profile_dir("Default").exists()


# ---- guards -------------------------------------------------------------

def test_refuses_when_already_managed(paths):
    _live_claude_dir(paths)
    _save(paths, "Default")
    with pytest.raises(AlreadyManagedError):
        _save(paths, "Again")


def test_refuses_a_foreign_link(paths, tmp_path):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(str(elsewhere), str(paths.claude_dir), target_is_directory=True)
    with pytest.raises(ForeignLinkError):
        _save(paths, "Default")


def test_refuses_when_there_is_nothing_to_save(paths):
    with pytest.raises(ShamblesError):
        _save(paths, "Default")


def test_crosses_filesystem_is_false_within_one_home(paths):
    _live_claude_dir(paths)
    assert switcher.crosses_filesystem(paths) is False


def test_crosses_filesystem_is_false_when_claude_dir_absent(paths):
    assert switcher.crosses_filesystem(paths) is False
