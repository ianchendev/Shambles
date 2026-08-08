import json

import pytest

from helpers import (DAY_MS, NOW, make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile)
from shambles import providers, state, switcher
from shambles.errors import AlreadyManagedError, ProfileNotFoundError

PROVIDER_IDS = ["claude", "codex"]


@pytest.fixture(params=PROVIDER_IDS)
def provider(request):
    return providers.load(request.param)


def seed_live(paths, provider, email):
    """Put a live login in place, matching what the active profile holds.

    Those two are the same bytes in reality: a profile's stash *is* a copy of
    the live credential, made when it was last active. The fixtures have to
    agree on that or the round-trip test measures fixture drift rather than
    the copy -- ``make_profile`` builds Codex tokens 30 days out while
    ``make_live_codex_login`` defaults to 10.
    """
    if provider.id == "claude":
        make_claude_json(paths, email=email)
        return make_live_claude_login(paths, access_token="tok-Work")
    return make_live_codex_login(paths, email=email, exp_ms=NOW + 30 * DAY_MS)


# -- the core promise ---------------------------------------------------

def test_credentials_survive_a_round_trip_unmodified(paths, provider):
    """Work -> Personal -> Work leaves the credential byte-identical.

    THE load-bearing test. If this regresses the tool stops solving the
    problem it exists for: a mutated refresh token costs a verification
    email, which is the entire thing being avoided. Parametrized over every
    provider, per DD-4 -- adding a provider means passing this suite.
    """
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    make_profile(paths, provider.id, "Personal", email="p@example.com")
    seed_live(paths, provider, "w@example.com")

    before = paths.credentials(provider.id, "Work").read_bytes()

    switcher.switch(paths, provider, "Personal", platform="linux", sleep=lambda _: None)
    switcher.switch(paths, provider, "Work", platform="linux", sleep=lambda _: None)

    assert paths.credentials(provider.id, "Work").read_bytes() == before


def test_the_outgoing_login_is_stashed_before_the_incoming_one_lands(paths, provider):
    """Switching away is never lossy, even to a profile with no token."""
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    make_profile(paths, provider.id, "Empty", token=False)
    live = seed_live(paths, provider, "w@example.com")
    original = live.read_bytes()

    switcher.switch(paths, provider, "Empty", platform="linux", sleep=lambda _: None)

    assert paths.credentials(provider.id, "Work").read_bytes() == original


def test_switching_to_a_never_logged_in_profile_clears_the_live_login(paths, provider):
    """Cleared, not left holding the previous account -- otherwise the vendor
    silently keeps using the account you just switched away from."""
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    make_profile(paths, provider.id, "Empty", token=False)
    seed_live(paths, provider, "w@example.com")

    switcher.switch(paths, provider, "Empty", platform="linux", sleep=lambda _: None)

    store = provider.store(home=paths.home, platform="linux")
    assert store.read() is None


def test_the_active_marker_follows_the_switch(paths, provider):
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    make_profile(paths, provider.id, "Personal", email="p@example.com")
    seed_live(paths, provider, "w@example.com")

    switcher.switch(paths, provider, "Personal", platform="linux", sleep=lambda _: None)

    assert state.read_active(paths, provider.id) == "Personal"


def test_switching_one_provider_leaves_the_other_alone(paths):
    claude, codex = providers.load("claude"), providers.load("codex")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_profile(paths, "codex", "Other", email="o@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)
    make_live_codex_login(paths, email="c@example.com")

    claude_before = (paths.claude_dir / ".credentials.json").read_bytes()
    switcher.switch(paths, codex, "Other", platform="linux", sleep=lambda _: None)

    assert (paths.claude_dir / ".credentials.json").read_bytes() == claude_before
    assert state.read_active(paths, "claude") == "Work"


# -- claude's companion splice -----------------------------------------

def test_the_splice_preserves_every_unrelated_key(paths):
    """~/.claude.json holds every project, MCP server and machine ID. A switch
    replaces two keys and nothing else."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    switcher.switch(paths, claude, "Personal", platform="linux", sleep=lambda _: None)

    config = json.loads(paths.claude_json.read_text(encoding="utf-8"))
    assert config["numStartups"] == 42
    assert config["machineID"] == "machine"
    assert config["projects"] == {"/some/dir": {"allowedTools": []}}
    assert config["oauthAccount"]["emailAddress"] == "p@example.com"


def test_an_unreadable_config_aborts_before_anything_moves(paths):
    """Splicing onto unparseable JSON would replace every project and MCP
    server with two keys. Refuse first, move nothing."""
    from shambles.errors import ConfigUnreadableError
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_live_claude_login(paths)
    paths.claude_json.write_text("{ this is not json", encoding="utf-8")

    live_before = (paths.claude_dir / ".credentials.json").read_bytes()

    with pytest.raises(ConfigUnreadableError):
        switcher.switch(paths, claude, "Personal", platform="linux", sleep=lambda _: None)

    assert (paths.claude_dir / ".credentials.json").read_bytes() == live_before
    assert state.read_active(paths, "claude") == "Work"


def test_codex_needs_no_companion_and_writes_none(paths):
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)
    make_profile(paths, "codex", "Other", email="o@example.com")
    make_live_codex_login(paths, email="c@example.com")

    switcher.switch(paths, codex, "Other", platform="linux", sleep=lambda _: None)

    assert not paths.claude_json.exists()


# -- guards -------------------------------------------------------------

def test_switching_to_a_missing_profile_is_refused(paths, provider):
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    with pytest.raises(ProfileNotFoundError):
        switcher.switch(paths, provider, "Ghost", platform="linux", sleep=lambda _: None)


def test_removing_the_active_profile_is_refused(paths, provider):
    """Enforced in code, not only by hiding the button. Hiding a control is
    not a safety property."""
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    with pytest.raises(AlreadyManagedError):
        switcher.remove_profile(paths, provider, "Work", platform="linux")


def test_a_name_escaping_the_store_is_refused(paths, provider):
    """remove_profile deletes a tree, so it re-checks rather than trusting how
    the name arrived."""
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    with pytest.raises(ProfileNotFoundError):
        switcher.remove_profile(paths, provider, "..", platform="linux")


def test_add_creates_an_empty_profile_and_activates_it(paths, provider):
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    seed_live(paths, provider, "w@example.com")

    switcher.add_empty_account(paths, provider, "Fresh", platform="linux",
                               sleep=lambda _: None)

    assert state.read_active(paths, provider.id) == "Fresh"
    assert provider.store(home=paths.home, platform="linux").read() is None


def test_saving_the_current_account_captures_the_live_login(paths, provider):
    live = seed_live(paths, provider, "w@example.com")

    switcher.save_current_account(paths, provider, "Work", platform="linux",
                                  sleep=lambda _: None)

    assert paths.credentials(provider.id, "Work").read_bytes() == live.read_bytes()
    assert state.read_active(paths, provider.id) == "Work"


def test_renaming_carries_the_active_marker(paths, provider):
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    switcher.rename_profile(paths, provider, "Work", "Job", sleep=lambda _: None)
    assert state.read_active(paths, provider.id) == "Job"
    assert paths.profile_dir(provider.id, "Job").is_dir()
