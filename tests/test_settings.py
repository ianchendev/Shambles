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
