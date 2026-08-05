import os

import pytest

from helpers import NOW, make_claude_json, make_profile
from shambles import configjson, links, profiles, switcher
from shambles.errors import (ProfileNameError, ProfileNotFoundError,
                             ShamblesError)


def _clock():
    return NOW


def _no_sleep(_seconds):
    pass


def _managed(paths, active="Work", **kwargs):
    make_profile(paths, active, email="work@example.com", **kwargs)
    make_claude_json(paths, email="work@example.com")
    os.symlink(str(paths.profile_dir(active)), str(paths.claude_dir),
               target_is_directory=True)


def _add(paths, name, seed_settings=True):
    return switcher.add_empty_account(paths, name, seed_settings=seed_settings,
                                      now_ms_fn=_clock, sleep=_no_sleep)


# ---- add ----------------------------------------------------------------

def test_add_creates_and_activates(paths):
    _managed(paths)
    assert _add(paths, "Personal") == "Personal"
    state = links.inspect(paths)
    assert state.profile == "Personal"
    assert paths.profile_dir("Personal").is_dir()


def test_add_clears_the_previous_identity(paths):
    _managed(paths)
    _add(paths, "Personal")
    live = configjson.load(paths.claude_json)
    assert "oauthAccount" not in live


def test_add_never_copies_credentials(paths):
    _managed(paths)
    _add(paths, "Personal")
    assert not (paths.profile_dir("Personal") / ".credentials.json").exists()
    assert profiles.token_state(paths.profile_dir("Personal"), NOW) == \
        profiles.TOKEN_MISSING


def test_add_seeds_settings_by_default(paths):
    _managed(paths, settings={"model": "opus", "effortLevel": "xhigh"})
    _add(paths, "Personal")
    seeded = configjson.load(paths.profile_dir("Personal") / "settings.json")
    assert seeded == {"model": "opus", "effortLevel": "xhigh"}


def test_add_skips_seeding_when_unchecked(paths):
    _managed(paths, settings={"model": "opus"})
    _add(paths, "Personal", seed_settings=False)
    assert not (paths.profile_dir("Personal") / "settings.json").exists()


def test_add_works_when_claude_dir_is_missing(paths):
    make_claude_json(paths, email="live@example.com")
    assert _add(paths, "First") == "First"
    assert links.inspect(paths).profile == "First"


def test_add_refuses_while_claude_dir_is_unmanaged(paths):
    paths.claude_dir.mkdir(parents=True)
    with pytest.raises(ShamblesError) as exc:
        _add(paths, "Personal")
    assert "Save Current Account" in str(exc.value)
    assert paths.claude_dir.is_dir()
    assert not paths.claude_dir.is_symlink()


def test_add_rejects_a_duplicate_name(paths):
    _managed(paths)
    with pytest.raises(ProfileNameError):
        _add(paths, "work")


# ---- rename -------------------------------------------------------------

def test_rename_an_inactive_profile(paths):
    _managed(paths)
    make_profile(paths, "Old", email="old@example.com")
    assert switcher.rename_profile(paths, "Old", "New", sleep=_no_sleep) == "New"
    assert paths.profile_dir("New").is_dir()
    assert not paths.profile_dir("Old").exists()
    assert links.inspect(paths).profile == "Work"


def test_rename_the_active_profile_repoints_the_link(paths):
    _managed(paths)
    switcher.rename_profile(paths, "Work", "Job", sleep=_no_sleep)
    state = links.inspect(paths)
    assert state.kind == links.MANAGED  # not DANGLING
    assert state.profile == "Job"
    assert (paths.claude_dir / ".credentials.json").exists()


def test_rename_to_the_same_name_is_a_noop(paths):
    _managed(paths)
    assert switcher.rename_profile(paths, "Work", "Work", sleep=_no_sleep) == "Work"
    assert links.inspect(paths).profile == "Work"


def test_rename_allows_a_case_change_of_itself(paths):
    _managed(paths)
    make_profile(paths, "Old")
    assert switcher.rename_profile(paths, "Old", "OLD", sleep=_no_sleep) == "OLD"


def test_rename_rejects_a_clash_with_another_profile(paths):
    _managed(paths)
    make_profile(paths, "Old")
    with pytest.raises(ProfileNameError):
        switcher.rename_profile(paths, "Old", "Work", sleep=_no_sleep)


def test_rename_unknown_profile_raises(paths):
    _managed(paths)
    with pytest.raises(ProfileNotFoundError):
        switcher.rename_profile(paths, "Ghost", "New", sleep=_no_sleep)


# ---- repair -------------------------------------------------------------

def test_remove_dangling_link(paths):
    _managed(paths)
    for child in paths.profile_dir("Work").iterdir():
        child.unlink()
    paths.profile_dir("Work").rmdir()
    switcher.remove_dangling_link(paths)
    assert links.inspect(paths).kind == links.MISSING


def test_remove_dangling_refuses_a_healthy_link(paths):
    _managed(paths)
    with pytest.raises(ShamblesError):
        switcher.remove_dangling_link(paths)
    assert links.inspect(paths).kind == links.MANAGED
