import pytest

from helpers import (make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile)
from shambles import eject, providers, state


def all_providers():
    return providers.all_providers()


def test_ejecting_a_stock_machine_is_a_clean_no_op(paths):
    plan = eject.run(paths, all_providers(), platform="linux")
    assert all(not p.credentials_kept for p in plan.providers)


def test_the_active_login_is_left_installed(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    plan = eject.run(paths, all_providers(), platform="linux")

    assert (paths.claude_dir / ".credentials.json").is_file()
    claude_plan = next(p for p in plan.providers if p.provider == "claude")
    assert claude_plan.credentials_kept is True
    assert claude_plan.active == "Work"


def test_a_missing_live_login_is_restored_from_the_active_profile(paths):
    """Ejecting must never leave the user logged out."""
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)

    eject.run(paths, all_providers(), platform="linux")

    assert (paths.home / ".codex" / "auth.json").is_file()


def test_bookkeeping_goes_and_credentials_stay(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_live_claude_login(paths)

    eject.run(paths, all_providers(), platform="linux")

    assert state.read_active(paths, "claude") is None
    assert paths.credentials("claude", "Personal").is_file()


def test_every_provider_is_ejected_not_just_the_first(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_live_claude_login(paths)
    make_live_codex_login(paths, email="c@example.com")

    eject.run(paths, all_providers(), platform="linux")

    assert state.read_active(paths, "claude") is None
    assert state.read_active(paths, "codex") is None


def test_ejecting_never_deletes_a_credential(paths):
    """The whole reason Eject exists. Every profile holds a refresh token only
    recoverable through a fresh verification email."""
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_live_claude_login(paths)

    before = {
        p: paths.credentials(*p).read_bytes()
        for p in (("claude", "Work"), ("claude", "Personal"), ("codex", "Side"))
    }

    eject.run(paths, all_providers(), platform="linux")

    for key, blob in before.items():
        assert paths.credentials(*key).read_bytes() == blob


def test_ejecting_twice_is_a_no_op(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_live_claude_login(paths)

    eject.run(paths, all_providers(), platform="linux")
    plan = eject.run(paths, all_providers(), platform="linux")

    assert (paths.claude_dir / ".credentials.json").is_file()
    assert plan.providers  # still reports, does not raise


def test_the_summary_names_the_profiles_left_behind(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_live_claude_login(paths)

    text = eject.summary(eject.run(paths, all_providers(), platform="linux"))

    assert "Personal" in text
    assert str(paths.library_dir) in text


def test_the_survey_touches_nothing(paths):
    """It describes what ejecting would do. Calling it must not eject."""
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_live_claude_login(paths)

    eject.survey(paths, all_providers(), platform="linux")

    assert state.read_active(paths, "claude") == "Work"
