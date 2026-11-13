"""Whose login is live: proof for anything done without a click.

Claude Code rotates its refresh token on every refresh (confirmed on a real
machine on 2026-11-13, and in the client: the token the server returns
replaces the old one). So for Claude, as for Codex, the stash of the account
in use holds a spent token from the first refresh after it was taken, and the
live bytes stop matching it.

What still identifies the login after a refresh is its lineage: Claude's
sign-in deadline, which a refresh recomputes to within a second or so, and
Codex's account and address, which are inside the token. Bytes or lineage are
*proof*: no other program can make a credential continue another profile's
login. The address in ``~/.claude.json`` is not: any Claude Code session
still running rewrites it from memory, and it reads as nobody while a write
is half done.

So everything Shambles does without being asked -- keeping Claude's stash
current on every refresh, moving the marker -- now requires proof. The
address is only ever a suggestion: the notice says which saved account it
names, and an explicit switch to that account is the user's answer.
"""

import copy
import json

import pytest

from helpers import (credentials, healthy_ms, make_claude_json, make_profile,
                     write_json)
from shambles import providers, state, switcher

PREVIOUS = "credentials.json.previous"
DEADLINE = healthy_ms(25)


def claude():
    return providers.load("claude", env={})


def login(access, refresh, deadline):
    blob = credentials(refresh_expires_ms=deadline, access_token=access)
    blob["claudeAiOauth"]["refreshToken"] = refresh
    return blob


def set_live(paths, blob):
    write_json(paths.claude_dir / ".credentials.json", blob)


def live_bytes(paths):
    return (paths.claude_dir / ".credentials.json").read_bytes()


def previous(paths, name):
    return paths.profile_dir("claude", name) / PREVIOUS


def kept_somewhere(paths, name, blob):
    """Still the profile's login, or its one backup."""
    if paths.credentials("claude", name).read_bytes() == blob:
        return True
    p = previous(paths, name)
    return p.exists() and p.read_bytes() == blob


def two_accounts(paths, *, work_deadline=None):
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    if work_deadline is not None:
        write_json(paths.credentials("claude", "Work"),
                   login("aw", "rw", work_deadline))
    return paths.credentials("claude", "Work").read_bytes()


# -- Claude is kept current, on proof ----------------------------------------

@pytest.fixture
def personal_refreshed(paths):
    """Personal marked and live, refreshed since its stash was taken."""
    make_profile(paths, "claude", "Work", email="w@example.test")
    make_profile(paths, "claude", "Personal", email="p@example.test",
                 active=True)
    write_json(paths.credentials("claude", "Personal"),
               login("a1", "r1", DEADLINE))
    set_live(paths, login("a2", "r2", DEADLINE - 1375))
    make_claude_json(paths, email="p@example.test")
    return paths


def test_claude_is_treated_as_rotating():
    assert claude().rotates is True


def test_a_refreshed_claude_login_is_restashed(personal_refreshed):
    paths = personal_refreshed

    assert switcher.restash_active(paths, claude(), platform="linux") is True

    assert paths.credentials("claude", "Personal").read_bytes() == \
        live_bytes(paths)
    assert not previous(paths, "Personal").exists(), (
        "a refresh of the same login is not worth a backup")


def test_a_refresh_is_restashed_whatever_the_address_on_file_says(
        personal_refreshed):
    """A session still running as Work rewrote the config. The lineage says
    the live login is Personal's, refreshed, and that is what decides."""
    paths = personal_refreshed
    make_claude_json(paths, email="w@example.test")

    assert switcher.restash_active(paths, claude(), platform="linux") is True
    assert state.inspect(paths, claude(), platform="linux").kind == \
        state.MANAGED


def test_restash_never_erases_a_profiles_identity(personal_refreshed):
    paths = personal_refreshed
    paths.claude_json.write_text(json.dumps({"cachedUsageUtilization": {
        "accountUuid": "uuid-a", "utilization": {}}}), encoding="utf-8")

    switcher.restash_active(paths, claude(), platform="linux")

    assert state.profile_email(paths, claude(), "Personal") == "p@example.test"


# -- and never on an address (review F1) -------------------------------------

def test_restash_does_not_file_another_accounts_login_on_a_stale_address(
        paths):
    """Signed in as Personal outside Shambles (a new sign-in: nothing holds
    the bytes, nothing shares the lineage) while a session still running as
    Work keeps the config saying Work. Nothing was clicked."""
    work = two_accounts(paths)
    make_claude_json(paths, email="w@example.test")
    set_live(paths, login("ap", "rp-new", healthy_ms(29)))

    switcher.restash_active(paths, claude(), platform="linux")

    assert paths.credentials("claude", "Work").read_bytes() == work


def test_restash_does_not_file_a_login_when_the_address_is_unreadable(paths):
    """~/.claude.json caught mid-rewrite reads as nobody, and nobody used
    to count as agreement."""
    work = two_accounts(paths)
    set_live(paths, login("ap", "rp-new", healthy_ms(29)))
    paths.claude_json.write_text('{"numStartups": 4', encoding="utf-8")

    switcher.restash_active(paths, claude(), platform="linux")

    assert paths.credentials("claude", "Work").read_bytes() == work
    make_claude_json(paths, email="p@example.test")
    assert state.inspect(paths, claude(), platform="linux").kind == \
        state.DRIFTED, "a copy made on no evidence would now hide the drift"


def test_opening_the_window_files_nothing_on_an_unreadable_address(
        paths, make_app):
    work = two_accounts(paths)
    set_live(paths, login("ap", "rp-new", healthy_ms(29)))
    paths.claude_json.write_text('{"numStartups": 4', encoding="utf-8")

    app = make_app(paths)
    app.update()

    assert paths.credentials("claude", "Work").read_bytes() == work


def test_a_restash_never_replaces_a_working_login_with_an_emptied_one(paths):
    work = two_accounts(paths)
    make_claude_json(paths, email="w@example.test")
    emptied = json.loads(work)
    emptied["claudeAiOauth"]["refreshToken"] = ""
    set_live(paths, emptied)

    switcher.restash_active(paths, claude(), platform="linux")

    assert paths.credentials("claude", "Work").read_bytes() == work


def test_a_login_with_no_deadline_is_never_restashed(paths):
    """Credentials the VS Code extension writes carry no deadline, so there
    is no lineage to prove anything with."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    blob = login("aw", "rw", 0)
    del blob["claudeAiOauth"]["refreshTokenExpiresAt"]
    write_json(paths.credentials("claude", "Work"), blob)
    work = paths.credentials("claude", "Work").read_bytes()
    make_claude_json(paths, email="w@example.test")
    other = copy.deepcopy(blob)
    other["claudeAiOauth"]["refreshToken"] = "rp"
    set_live(paths, other)

    assert switcher.restash_active(paths, claude(), platform="linux") is False
    assert paths.credentials("claude", "Work").read_bytes() == work


# -- the marker: proof moves it, an address only suggests ---------------------

def test_the_address_alone_does_not_say_who_owns_the_live_login(paths):
    two_accounts(paths)
    make_claude_json(paths, email="p@example.test")
    set_live(paths, login("ap", "rp-new", healthy_ms(29)))

    assert state.owner_of_live(paths, claude(), platform="linux") is None
    assert state.owner_by_address(paths, claude(), platform="linux") == \
        "Personal"


def test_the_bytes_say_so(paths):
    two_accounts(paths)
    set_live(paths, json.loads(
        paths.credentials("claude", "Personal").read_text()))

    assert state.owner_of_live(paths, claude(), platform="linux") == "Personal"


def test_so_does_the_lineage(paths):
    two_accounts(paths)
    write_json(paths.credentials("claude", "Personal"),
               login("ap1", "rp1", DEADLINE))
    set_live(paths, login("ap2", "rp2", DEADLINE + 900))

    assert state.owner_of_live(paths, claude(), platform="linux") == "Personal"


def test_adoption_does_not_move_the_marker_on_an_address(paths):
    """What every interface runs on refresh, with no click."""
    two_accounts(paths)
    make_claude_json(paths, email="p@example.test")
    set_live(paths, login("ap", "rp-new", healthy_ms(29)))

    assert switcher.adopt_live_owner(paths, claude(), platform="linux") is None
    assert state.read_active(paths, "claude") == "Work"


def test_adoption_moves_the_marker_on_lineage(paths):
    two_accounts(paths)
    write_json(paths.credentials("claude", "Personal"),
               login("ap1", "rp1", DEADLINE))
    set_live(paths, login("ap2", "rp2", DEADLINE + 900))
    make_claude_json(paths, email="w@example.test")      # a stale session

    assert switcher.adopt_live_owner(paths, claude(), platform="linux") == \
        "Personal"


def test_switching_to_the_account_the_address_names_is_the_answer(paths):
    """Signed in again in the browser as Personal, which is saved. The
    notice says so and says to switch to Personal; doing that files the new
    login under Personal, keeping the one it replaces."""
    from shambles.app.service import ShamblesService

    two_accounts(paths)
    personal = paths.credentials("claude", "Personal").read_bytes()
    work = paths.credentials("claude", "Work").read_bytes()
    make_claude_json(paths, email="p@example.test")
    set_live(paths, login("a-new", "r-new", healthy_ms(29)))
    fresh = live_bytes(paths)

    result = ShamblesService(paths=paths, providers=[claude()],
                             platform="linux").switch("claude", "Personal")

    assert result.ok, result.error
    assert state.read_active(paths, "claude") == "Personal"
    assert paths.credentials("claude", "Personal").read_bytes() == fresh
    assert previous(paths, "Personal").read_bytes() == personal
    assert paths.credentials("claude", "Work").read_bytes() == work
    assert live_bytes(paths) == fresh


def test_switching_anywhere_else_is_still_refused(paths):
    from shambles.errors import DriftedLoginError

    two_accounts(paths)
    make_profile(paths, "claude", "Third", email="t@example.test")
    make_claude_json(paths, email="p@example.test")
    set_live(paths, login("a-new", "r-new", healthy_ms(29)))
    fresh = live_bytes(paths)

    with pytest.raises(DriftedLoginError):
        switcher.switch(paths, claude(), "Third", platform="linux",
                        sleep=lambda _: None)
    assert live_bytes(paths) == fresh


# -- the common case after a switch (review F12) -----------------------------

def _session_outlived_the_switch(paths):
    """Switch Work -> Personal with a VS Code session still running as Work.
    At its next refresh that session adopts Personal's stored login, so the
    live token is Personal's, refreshed; and it rewrites ~/.claude.json from
    memory with Work's address."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    make_claude_json(paths, email="w@example.test")
    set_live(paths, json.loads(paths.credentials("claude", "Work").read_text()))
    work = paths.credentials("claude", "Work").read_bytes()
    switcher.switch(paths, claude(), "Personal", platform="linux",
                    sleep=lambda _: None)
    personal = json.loads(paths.credentials("claude", "Personal").read_text())
    refreshed = copy.deepcopy(personal)
    refreshed["claudeAiOauth"]["accessToken"] = "a-session"
    refreshed["claudeAiOauth"]["refreshToken"] = "r-session"
    refreshed["claudeAiOauth"]["refreshTokenExpiresAt"] -= 1375
    set_live(paths, refreshed)
    make_claude_json(paths, email="w@example.test")
    return work, live_bytes(paths)


def test_after_a_session_outlives_a_switch_the_login_is_still_personals(paths):
    _session_outlived_the_switch(paths)

    current = state.inspect(paths, claude(), platform="linux")

    assert (current.kind, current.profile) == (state.MANAGED, "Personal")


def test_switching_back_to_work_works_and_loses_nothing(paths):
    work, personal_now = _session_outlived_the_switch(paths)
    switcher.restash_active(paths, claude(), platform="linux")
    switcher.adopt_live_owner(paths, claude(), platform="linux")

    switcher.switch(paths, claude(), "Work", platform="linux",
                    sleep=lambda _: None)

    assert live_bytes(paths) == work
    assert kept_somewhere(paths, "Personal", personal_now)


def test_the_window_files_nothing_over_work_after_that(paths, make_app):
    work, _ = _session_outlived_the_switch(paths)

    app = make_app(paths)
    app.update()

    assert state.read_active(paths, "claude") == "Personal"
    assert paths.credentials("claude", "Work").read_bytes() == work


def test_the_whole_episode_restores_works_own_login(paths):
    """Review F1e. Personal signs in outside Shambles while a session still
    running as Work keeps the config saying Work; refreshes of the window
    happen; the session exits and the config names Personal; the marker
    follows on whatever each interface offers; the user switches to Work."""
    work = two_accounts(paths)
    make_claude_json(paths, email="w@example.test")
    set_live(paths, login("ap1", "rp1", healthy_ms(29)))
    switcher.restash_active(paths, claude(), platform="linux")

    set_live(paths, login("ap2", "rp2", healthy_ms(29)))
    make_claude_json(paths, email="p@example.test")
    switcher.restash_active(paths, claude(), platform="linux")
    switcher.adopt_live_owner(paths, claude(), platform="linux")
    if state.read_active(paths, "claude") != "Personal":
        switcher.switch(paths, claude(), "Personal", platform="linux",
                        sleep=lambda _: None)
    switcher.restash_active(paths, claude(), platform="linux")

    switcher.switch(paths, claude(), "Work", platform="linux",
                    sleep=lambda _: None)

    assert live_bytes(paths) == work
