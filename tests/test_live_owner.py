"""Which saved profile is the machine actually signed in as?

Answering that from the email alone reads `~/.claude.json`, a file Claude
Code owns and rewrites from its own memory whenever a session is running. So
a VS Code session could rewrite it moments after a switch, and the window's
drift correction would move the active marker straight back to the account
the user had just switched away from. The token on disk was the new one the
whole time, which is why usage updated while the address did not.

A credential the profile stashed is proof no other process can forge.
"""

import json

import pytest

from helpers import (NOW, credentials, make_claude_json,
                     make_live_claude_login, make_profile, write_json)
from shambles import providers, state, switcher


def claude(env=None):
    return next(p for p in providers.all_providers(env=env or {})
                if p.id == "claude")


@pytest.fixture
def two_accounts(paths):
    make_profile(paths, "claude", "Work", email="work@corp.test", active=True)
    make_profile(paths, "claude", "Personal", email="me@home.test")
    make_claude_json(paths, email="work@corp.test")
    make_live_claude_login(paths)
    return paths


def clobber_identity(paths, email):
    """Stand in for a running Claude Code session rewriting its own config."""
    path = paths.home / ".claude.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["oauthAccount"]["emailAddress"] = email
    path.write_text(json.dumps(data), encoding="utf-8")


def test_the_stashed_credential_identifies_the_owner(two_accounts):
    paths = two_accounts
    switcher.switch(paths, claude(), "Personal", platform="linux")
    clobber_identity(paths, "work@corp.test")

    assert state.owner_of_live(paths, claude(), platform="linux") == "Personal"


def test_a_clobbered_config_no_longer_moves_the_marker(two_accounts):
    """The whole bug, end to end, as the window would have run it."""
    paths = two_accounts
    switcher.switch(paths, claude(), "Personal", platform="linux")
    clobber_identity(paths, "work@corp.test")

    current = state.inspect(paths, claude(), platform="linux")
    owner = state.owner_of_live(paths, claude(), platform="linux")
    assert owner == current.profile == "Personal"


def test_the_address_still_answers_when_no_credential_matches(paths):
    """Codex rotates its token, so the stash drifts from the live copy.

    Identity has to fall back to the address there, which is what it always
    used before.
    """
    make_profile(paths, "claude", "Work", email="work@corp.test", active=True)
    make_claude_json(paths, email="work@corp.test")
    make_live_claude_login(paths)
    write_json(paths.credentials("claude", "Work"),
               credentials(NOW + 86_400_000, access_token="a-different-token"))

    assert state.owner_of_live(paths, claude(), platform="linux") == "Work"


def test_an_unknown_login_still_belongs_to_nobody(two_accounts):
    paths = two_accounts
    clobber_identity(paths, "stranger@elsewhere.test")
    write_json(paths.home / ".claude" / ".credentials.json",
               credentials(NOW + 86_400_000, access_token="nobody-elses"))

    assert state.owner_of_live(paths, claude(), platform="linux") is None


def test_stashing_is_allowed_when_the_credential_is_already_that_profiles(
        two_accounts):
    """A clobbered address must not make Shambles refuse its own login.

    ``belongs_to`` guards the write that costs a refresh token, so a false
    refusal here is a dialog in front of somebody who did nothing wrong.
    """
    paths = two_accounts
    switcher.switch(paths, claude(), "Personal", platform="linux")
    clobber_identity(paths, "work@corp.test")

    assert switcher.belongs_to(paths, claude(), "Personal",
                               platform="linux") is True


def test_a_genuinely_different_login_is_still_refused(two_accounts):
    """The protection that matters: never file one account's token as another."""
    paths = two_accounts
    clobber_identity(paths, "work@corp.test")
    write_json(paths.home / ".claude" / ".credentials.json",
               credentials(NOW + 86_400_000, access_token="somebody-elses"))

    assert switcher.belongs_to(paths, claude(), "Personal",
                               platform="linux") is False
