import json

import pytest

from helpers import (DAY_MS, NOW, healthy_ms, make_claude_json,
                     make_live_claude_login, make_live_codex_login,
                     make_profile)
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
    ``make_live_codex_login`` defaults to 10. Both sides take that 30 from
    ``healthy_ms`` so they agree to the byte.
    """
    if provider.id == "claude":
        make_claude_json(paths, email=email)
        return make_live_claude_login(paths, access_token="tok-Work")
    return make_live_codex_login(paths, email=email, exp_ms=healthy_ms())


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


# -- rotation -----------------------------------------------------------

def test_a_rotating_provider_restashes_a_refreshed_credential(paths):
    """Codex rotates on every use, so the stashed copy goes stale the moment
    the live one refreshes. Switching away would then write back a dead
    refresh token and cost a verification email."""
    from helpers import codex_auth, write_json
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)
    live = make_live_codex_login(paths, email="c@example.com",
                                 exp_ms=NOW + 30 * DAY_MS)

    # The vendor refreshes during use, rotating the refresh token.
    rotated = codex_auth(email="c@example.com", exp_ms=NOW + 30 * DAY_MS)
    rotated["tokens"]["refresh_token"] = "refresh-2"
    write_json(live, rotated)

    assert switcher.restash_active(paths, codex, platform="linux") is True

    stashed = json.loads(paths.credentials("codex", "Work").read_text())
    assert stashed["tokens"]["refresh_token"] == "refresh-2"


def test_restash_is_a_no_op_when_nothing_changed(paths):
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)
    blob = paths.credentials("codex", "Work").read_bytes()
    (paths.home / ".codex").mkdir(parents=True, exist_ok=True)
    (paths.home / ".codex" / "auth.json").write_bytes(blob)

    assert switcher.restash_active(paths, codex, platform="linux") is False


def test_a_non_rotating_provider_is_never_restashed(paths):
    """Claude's refresh token does not rotate, so the live file drifting from
    the stash is normal and re-stashing would be pointless writes."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths, access_token="something-else")

    assert switcher.restash_active(paths, claude, platform="linux") is False


def test_restash_does_nothing_without_an_active_profile(paths):
    codex = providers.load("codex")
    make_live_codex_login(paths, email="c@example.com")
    assert switcher.restash_active(paths, codex, platform="linux") is False


def test_restash_refreshes_the_stash_for_the_same_account(paths):
    """What re-stashing corrects, now that it checks identity first.

    Codex replaces its refresh token on every use, so a stash taken before a
    refresh holds a token the server has already invalidated -- restoring one
    does not fail cleanly, it silently breaks the account. Re-stashing keeps
    the copy current.

    The identity has to match for that to be safe, so the rotation here keeps
    the address and changes the token, which is what a real refresh does. A
    login belonging to somebody else is refused instead, covered separately.

    Written as a before/after on the same profile, because a test that only
    asserted the "after" state would pass with ``restash_active`` deleted --
    an earlier version of this test did exactly that.
    """
    from shambles import profiles
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="same@example.com", active=True,
                 refresh_expires_ms=NOW + 3 * DAY_MS)
    make_live_codex_login(paths, email="same@example.com", exp_ms=healthy_ms())

    before = paths.credentials("codex", "Work").read_bytes()
    assert switcher.restash_active(paths, codex, platform="linux") is True
    after = paths.credentials("codex", "Work").read_bytes()

    assert after != before, "the stale stash was left in place"
    assert profiles.discover(paths, codex, "Work", NOW,
                             platform="linux")[0].email == "same@example.com"


def test_switching_away_captures_a_rotation_even_without_restash(paths):
    """The guarantee that makes restash a display fix rather than a data fix.

    Recorded because it is easy to assume re-stashing is what protects the
    token on switch-away. It is not -- ``switch`` stashing the outgoing login
    is. Both matter; conflating them produced a vacuous test once already.
    """
    from helpers import codex_auth, write_json
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)
    make_profile(paths, "codex", "Other", email="o@example.com")
    live = make_live_codex_login(paths, email="c@example.com",
                                 exp_ms=NOW + 30 * DAY_MS)

    rotated = codex_auth(email="c@example.com", exp_ms=NOW + 30 * DAY_MS)
    rotated["tokens"]["refresh_token"] = "refresh-2"
    write_json(live, rotated)

    switcher.switch(paths, codex, "Other", platform="linux", sleep=lambda _: None)

    kept = json.loads(paths.credentials("codex", "Work").read_text())
    assert kept["tokens"]["refresh_token"] == "refresh-2"


# ---- a login that never completes must not strand the user --------------

def _live_blob(paths, provider):
    return provider.store(home=paths.home, platform="linux").read()


def _write_live_blob(paths, provider, blob):
    provider.store(home=paths.home, platform="linux").write(blob)


def test_abandoning_a_new_account_restores_the_previous_one(paths):
    claude = providers.load("claude")
    """Adding an account switches to it so the vendor writes the credential
    there. If the sign-in is cancelled or fails, the user is left signed out
    of a working account with an empty profile active."""
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_claude_login(paths)

    created = switcher.add_empty_account(paths, claude, "New", platform="linux")
    assert state.read_active(paths, "claude") == created
    assert _live_blob(paths, claude) is None, "the vendor needs an empty slot"

    switcher.abandon_new_account(paths, claude, created, "Work",
                                 platform="linux")

    assert state.read_active(paths, "claude") == "Work"
    assert _live_blob(paths, claude) is not None, "still signed out"


def test_abandoning_keeps_the_profile_for_a_retry(paths):
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_claude_login(paths)

    created = switcher.add_empty_account(paths, claude, "New", platform="linux")
    switcher.abandon_new_account(paths, claude, created, "Work",
                                 platform="linux")

    assert created in state.profile_names(paths, "claude"), \
        "the named profile was destroyed; the user cannot retry the sign-in"


def test_abandoning_the_very_first_account_is_a_no_op(paths):
    claude = providers.load("claude")
    """No previous profile to go back to, and nothing was signed in before."""
    created = switcher.add_empty_account(paths, claude, "First",
                                         platform="linux")
    switcher.abandon_new_account(paths, claude, created, None,
                                 platform="linux")
    assert state.read_active(paths, "claude") == created


def test_abandoning_a_profile_that_did_get_a_login_leaves_it_alone(paths):
    claude = providers.load("claude")
    """Only called on failure, but it must not undo a successful sign-in if
    the caller is ever wrong about which happened."""
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_claude_login(paths)

    created = switcher.add_empty_account(paths, claude, "New", platform="linux")
    _write_live_blob(paths, claude, b'{"claudeAiOauth": {"refreshToken": "x"}}')

    switcher.abandon_new_account(paths, claude, created, "Work",
                                 platform="linux")

    assert state.read_active(paths, "claude") == created, \
        "rolled back over a login that had actually succeeded"


def test_a_config_that_goes_unreadable_mid_switch_is_not_replaced(paths):
    """The pre-check at the top of switch() is not the only reader.

    companion_write re-reads ~/.claude.json to splice the identity into it,
    and Claude Code rewrites that file on its own schedule -- which is the
    documented reason the pre-check exists at all. Between the check and the
    splice sits the whole credential swap, each step retried with sleeps, so a
    read landing mid-write is exactly the window the guard was meant to cover.

    Reading it with a parser that answers {} for unusable input turns the
    splice into a truncation: every project, MCP server and machine ID
    replaced by the two identity keys.
    """
    from shambles.errors import ConfigUnreadableError

    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    # Parseable when switch() checks it...
    from shambles import configjson
    configjson.load_for_write(paths.claude_json)

    # ...and truncated by the time the identity is spliced in.
    original = paths.claude_json.read_text(encoding="utf-8")
    truncated = original[: len(original) // 2]
    paths.claude_json.write_text(truncated, encoding="utf-8")

    with pytest.raises(ConfigUnreadableError):
        claude.companion_write({"oauthAccount": {"emailAddress": "p@example.com"}},
                               home=paths.home)

    assert paths.claude_json.read_text(encoding="utf-8") == truncated, (
        "the unreadable config was overwritten instead of refused")


def test_a_rollback_survives_an_unreadable_store(paths, monkeypatch):
    """The guard around the store read names an exception the module never
    imported, so instead of returning False it raises NameError.

    NameError is not a ShamblesError, so the GUI's own handler does not catch
    it either: the user gets a traceback, no rollback, and is left signed out
    of a working account with an empty new profile active -- the exact state
    this function exists to undo.
    """
    from shambles.stores.base import StoreUnavailableError

    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Empty", token=False)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    class Refusing:
        def read(self):
            raise StoreUnavailableError("keychain is locked")

    monkeypatch.setattr(switcher, "_store", lambda *a, **k: Refusing())

    assert switcher.abandon_new_account(
        paths, claude, "Empty", "Work", platform="linux",
        sleep=lambda _: None) is False


# ---- a live login that belongs to someone else ---------------------------
#
# Reported from a real machine: a work token lapsed, the user signed in
# through the browser as their personal account, and opening Shambles showed
# the personal address on the "Ian Work" card. Nothing had been destroyed --
# but the next switch would have filed that personal login under "Ian Work",
# overwriting the work refresh token with it.

def test_switching_while_signed_in_as_someone_else_is_refused(paths):
    """Nothing moves. The outgoing copy-out files the *live* login under the
    marked profile, so switching while drifted overwrites that profile's
    saved token with a stranger's -- the one loss this tool exists to
    prevent, reachable by clicking the button the card offers."""
    from shambles.errors import DriftedLoginError

    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    # Signed in as someone else entirely, outside Shambles.
    make_claude_json(paths, email="stranger@example.com")
    make_live_claude_login(paths, access_token="tok-STRANGER")

    before = paths.credentials("claude", "Work").read_bytes()

    with pytest.raises(DriftedLoginError) as raised:
        switcher.switch(paths, claude, "Personal", platform="linux",
                        sleep=lambda _: None)

    assert "stranger@example.com" in str(raised.value)
    assert "Work" in str(raised.value)
    assert paths.credentials("claude", "Work").read_bytes() == before, (
        "the marked profile's token was overwritten by a foreign login")
    assert state.read_active(paths, "claude") == "Work", "the marker moved"


def test_stashing_refuses_to_file_a_foreign_login_under_a_profile(paths):
    """The guard sits on the write itself, not only on switch(), so every
    caller inherits it."""
    from shambles.errors import DriftedLoginError

    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="stranger@example.com")
    make_live_claude_login(paths, access_token="tok-STRANGER")

    before = paths.credentials("claude", "Work").read_bytes()
    with pytest.raises(DriftedLoginError):
        switcher.stash_live_login(paths, claude, "Work", platform="linux",
                                  sleep=lambda _: None)
    assert paths.credentials("claude", "Work").read_bytes() == before


def test_stashing_into_a_profile_with_no_identity_is_still_allowed(paths):
    """Saving the current login as a brand new account is the ordinary path
    and has no identity to contradict."""
    claude = providers.load("claude")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    switcher.stash_live_login(paths, claude, "Fresh", platform="linux",
                              sleep=lambda _: None)
    assert paths.credentials("claude", "Fresh").exists()


def test_restash_refuses_a_live_credential_that_is_not_this_profiles(paths):
    """restash_active runs on every window refresh, so this one destroys a
    token with no click at all: open the window while signed in as someone
    else and the marked profile's stash is replaced."""
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="work@example.com", active=True)
    make_live_codex_login(paths, email="stranger@example.com")

    before = paths.credentials("codex", "Work").read_bytes()
    assert switcher.restash_active(paths, codex, platform="linux") is False
    assert paths.credentials("codex", "Work").read_bytes() == before, (
        "merely opening the window overwrote a saved token")
