import os

import pytest

from helpers import make_profile
from shambles import links
from shambles.errors import SwitchFailedError


def test_missing_when_nothing_there(paths):
    assert links.inspect(paths).kind == links.MISSING


def test_unmanaged_for_a_real_directory(paths):
    paths.claude_dir.mkdir(parents=True)
    state = links.inspect(paths)
    assert state.kind == links.UNMANAGED
    assert state.profile is None


def test_managed_reports_the_profile_name(paths):
    target = make_profile(paths, "Work")
    os.symlink(str(target), str(paths.claude_dir), target_is_directory=True)
    state = links.inspect(paths)
    assert state.kind == links.MANAGED
    assert state.profile == "Work"


def test_dangling_when_target_removed(paths):
    target = make_profile(paths, "Gone")
    os.symlink(str(target), str(paths.claude_dir), target_is_directory=True)
    for child in target.iterdir():
        child.unlink()
    target.rmdir()
    state = links.inspect(paths)
    assert state.kind == links.DANGLING
    assert state.profile == "Gone"


def test_foreign_when_pointing_outside_profiles_dir(paths, tmp_path):
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    os.symlink(str(elsewhere), str(paths.claude_dir), target_is_directory=True)
    assert links.inspect(paths).kind == links.FOREIGN


def test_point_to_creates_an_absolute_link(paths):
    target = make_profile(paths, "Work")
    links.point_to(paths, target, sleep=_no_sleep)
    stored = os.readlink(paths.claude_dir)
    assert os.path.isabs(stored)
    assert links.inspect(paths).profile == "Work"


def test_point_to_replaces_an_existing_link(paths):
    a = make_profile(paths, "A")
    b = make_profile(paths, "B")
    links.point_to(paths, a, sleep=_no_sleep)
    links.point_to(paths, b, sleep=_no_sleep)
    assert links.inspect(paths).profile == "B"


def test_point_to_leaves_no_temp_link(paths):
    target = make_profile(paths, "Work")
    links.point_to(paths, target, sleep=_no_sleep)
    assert not paths.tmp_link.exists()
    assert not paths.tmp_link.is_symlink()


def test_point_to_clears_a_stale_temp_link(paths):
    target = make_profile(paths, "Work")
    os.symlink(str(target), str(paths.tmp_link), target_is_directory=True)
    links.point_to(paths, target, sleep=_no_sleep)
    assert links.inspect(paths).profile == "Work"


def test_point_to_surfaces_a_persistent_failure(paths, monkeypatch):
    target = make_profile(paths, "Work")

    def blocked(*_args, **_kwargs):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", blocked)
    with pytest.raises(SwitchFailedError):
        links.point_to(paths, target, sleep=_no_sleep)


def _no_sleep(_seconds):
    pass
