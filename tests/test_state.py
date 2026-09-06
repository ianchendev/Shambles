import pytest

from helpers import (make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile)
from shambles import providers, state


@pytest.fixture
def claude():
    return providers.load("claude")


@pytest.fixture
def codex():
    return providers.load("codex")


def test_no_profiles_reads_as_unmanaged(paths, claude):
    assert state.inspect(paths, claude, platform="linux").kind == state.UNMANAGED


def test_a_marked_profile_matching_the_live_login_is_managed(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    current = state.inspect(paths, claude, platform="linux")

    assert current.kind == state.MANAGED
    assert current.profile == "Work"
    assert current.live_email == "w@example.com"


def test_a_manual_login_elsewhere_reads_as_drifted(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="someone@else.com")

    current = state.inspect(paths, claude, platform="linux")

    assert current.kind == state.DRIFTED
    assert current.live_email == "someone@else.com"
    assert current.expected_email == "w@example.com"


def test_a_marker_naming_a_deleted_profile_is_surfaced(paths, claude):
    paths.ensure_provider("claude")
    state.write_active(paths, "claude", "Ghost")

    current = state.inspect(paths, claude, platform="linux")

    assert current.kind == state.MISSING_PROFILE
    assert current.profile == "Ghost"


def test_profiles_but_no_marker_reads_as_unknown(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com")
    assert state.inspect(paths, claude, platform="linux").kind == state.UNKNOWN


def test_codex_identity_comes_from_the_token(paths, codex):
    """No sidecar, no splice: the JWT is the whole story."""
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)
    make_live_codex_login(paths, email="c@example.com")

    current = state.inspect(paths, codex, platform="linux")

    assert current.kind == state.MANAGED
    assert current.live_email == "c@example.com"


def test_each_provider_has_its_own_active_profile(paths, claude, codex):
    """Two providers, two independent markers. Neither can shadow the other."""
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_live_codex_login(paths, email="c@example.com")

    assert state.inspect(paths, claude, platform="linux").profile == "Work"
    assert state.inspect(paths, codex, platform="linux").profile == "Side"


def test_config_dir_override_is_reported_per_provider(paths, claude, codex):
    env = {"CODEX_HOME": "/somewhere/else"}
    assert state.config_dir_override(claude, home=paths.home, env=env) is None
    assert state.config_dir_override(codex, home=paths.home, env=env) == "/somewhere/else"


def test_pointing_the_variable_at_the_default_is_not_an_override(paths, codex):
    """Setting it explicitly to where it already points changes nothing and
    must not raise a false alarm."""
    env = {"CODEX_HOME": str(paths.home / ".codex")}
    assert state.config_dir_override(codex, home=paths.home, env=env) is None
