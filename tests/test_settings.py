import json
import os

import pytest

from conftest import posix_modes_only
from shambles import settings


def test_settings_live_beside_the_rest_of_the_store(paths):
    assert paths.settings_path == paths.library_dir / "settings.json"


def test_a_home_with_no_settings_file_reads_as_defaults(paths):
    """A fresh install has no settings file and must not need one."""
    assert settings.load_settings(paths) == {}
    assert settings.update_check_enabled(paths) is False


def test_update_checks_are_off_until_somebody_turns_them_on(paths):
    """The privacy default. Nothing here reaches the network on its own."""
    assert settings.update_check_enabled(paths) is False
    settings.set_update_check(paths, True)
    assert settings.update_check_enabled(paths) is True
    settings.set_update_check(paths, False)
    assert settings.update_check_enabled(paths) is False


def test_unreadable_settings_read_as_defaults_rather_than_raising(paths):
    """A truncated or hand-mangled file must not stop Shambles starting.

    Settings hold a preference, not a credential -- there is nothing here
    worth refusing to run over.
    """
    paths.ensure_store()
    paths.settings_path.write_text("{not json", encoding="utf-8")
    assert settings.load_settings(paths) == {}
    assert settings.update_check_enabled(paths) is False


def test_settings_that_are_not_an_object_read_as_defaults(paths):
    paths.ensure_store()
    paths.settings_path.write_text("[1, 2, 3]", encoding="utf-8")
    assert settings.load_settings(paths) == {}
    assert settings.update_check_enabled(paths) is False


@pytest.mark.parametrize("value", ["true", "yes", 1, "1", None, {}, "false"])
def test_only_a_real_json_true_opens_the_network(paths, value):
    """Hand-edited near-misses stay off.

    The setting gates an outbound request, so the one direction it must never
    fail in is "on by accident". ``"true"`` the string is not ``true``.
    """
    settings.save_settings(paths, {settings.UPDATE_CHECK: value})
    assert settings.update_check_enabled(paths) is False


def test_toggling_one_setting_leaves_the_others_alone(paths):
    """Whatever else the file grows, a toggle rewrites one key, not the file."""
    settings.save_settings(paths, {"something.else": "kept"})
    settings.set_update_check(paths, True)
    assert settings.load_settings(paths) == {"something.else": "kept",
                                             settings.UPDATE_CHECK: True}


def test_saving_creates_the_store_it_writes_into(paths):
    """No caller has to remember to mkdir first."""
    assert not paths.library_dir.exists()
    settings.set_update_check(paths, True)
    assert paths.settings_path.is_file()


def test_what_lands_on_disk_is_json_a_person_can_edit(paths):
    """The key on disk is the key the CLI and the docs name."""
    settings.set_update_check(paths, True)
    written = json.loads(paths.settings_path.read_text(encoding="utf-8"))
    assert written == {"update.check": True}


@posix_modes_only
def test_settings_are_written_owner_only_like_the_rest_of_the_store(paths):
    """It sits in the same directory as the tokens; it is written the same
    way, so a stray umask cannot leave a 644 file among 600s."""
    settings.set_update_check(paths, True)
    assert oct(os.stat(paths.settings_path).st_mode)[-3:] == "600"
    assert oct(os.stat(paths.library_dir).st_mode)[-3:] == "700"


def test_a_stored_theme_that_is_not_a_theme_reads_as_system(paths):
    """A hand-edited file must not hand the window a colour it cannot draw."""
    settings.save_settings(paths, {settings.WINDOW_THEME: "sepia"})

    assert settings.window_theme(paths) == "system"


def test_setting_the_theme_keeps_the_other_settings(paths):
    settings.set_update_check(paths, True)

    settings.set_window_theme(paths, "light")

    assert settings.window_theme(paths) == "light"
    assert settings.update_check_enabled(paths) is True


# -- where the window was -------------------------------------------------------


def test_a_home_with_no_stored_window_place_reads_as_none(paths):
    assert settings.window_place(paths) is None


def test_the_window_place_round_trips_and_keeps_the_other_settings(paths):
    settings.set_window_theme(paths, "dark")

    settings.set_window_place(paths, 120, -40, 600, 500, maximized=True)

    assert settings.window_place(paths) == {
        "x": 120, "y": -40, "width": 600, "height": 500, "maximized": True}
    assert settings.window_theme(paths) == "dark"


def test_storing_the_same_place_again_does_not_rewrite_the_file(paths):
    """The window reports its place after every move; most reports repeat
    the last one, and a settings file rewritten for nothing is churn in a
    directory that also holds logins."""
    assert settings.set_window_place(paths, 10, 20, 700, 600) is True
    before = os.stat(paths.settings_path).st_mtime_ns
    os.utime(paths.settings_path, ns=(before - 10**9, before - 10**9))

    assert settings.set_window_place(paths, 10, 20, 700, 600) is False

    assert os.stat(paths.settings_path).st_mtime_ns == before - 10**9


@pytest.mark.parametrize("stored", [
    "760x720",
    [10, 20, 700, 600],
    {"x": 10, "y": 20, "width": 700},
    {"x": 10, "y": 20, "width": 0, "height": 600},
    {"x": 10, "y": 20, "width": 700, "height": -5},
    {"x": "10", "y": 20, "width": 700, "height": 600},
    {"x": True, "y": 20, "width": 700, "height": 600},
    {"x": 1.5, "y": 20, "width": 700, "height": 600},
])
def test_a_stored_place_that_is_not_a_place_reads_as_none(paths, stored):
    """A hand-edited file is a guess at the format; the window opens where
    it would have opened with no file at all."""
    settings.save_settings(paths, {settings.WINDOW_PLACE: stored})

    assert settings.window_place(paths) is None


def test_a_place_without_a_maximised_flag_reads_as_not_maximised(paths):
    settings.save_settings(paths, {settings.WINDOW_PLACE: {
        "x": 1, "y": 2, "width": 700, "height": 600, "maximized": "yes"}})

    assert settings.window_place(paths)["maximized"] is False


@pytest.mark.parametrize("bad", [
    (1, 2, 0, 600), (1, 2, 700, -1), ("1", 2, 700, 600), (1.5, 2, 700, 600),
])
def test_storing_a_place_that_is_not_one_raises_before_writing(paths, bad):
    with pytest.raises(ValueError):
        settings.set_window_place(paths, *bad)

    assert not paths.settings_path.exists()
