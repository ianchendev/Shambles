"""What a stash replaces is kept, once, beside it.

Every loss path still open ends in the same write: a profile's saved login
replaced by the live one on the strength of an address that a running Claude
Code session can rewrite. Shambles cannot prove that address for Claude, so
the replaced login is kept as ``credentials.json.previous`` in the same
owner-only directory, and a wrong attribution can be undone by hand.

One generation only, but not one *write*. Both vendors rotate the refresh
token on use, so the stash of the account in use is rewritten after every
refresh. A backup moved along by each of those would be overwritten by the
second refresh after a wrong attribution, and with it the only good copy. A
refresh of the same login supersedes the old token anyway, so it is not
worth keeping and does not displace what is.
"""

import json
import os
import stat

import pytest

from conftest import posix_modes_only
from helpers import (codex_auth, credentials, healthy_ms, make_claude_json,
                     make_live_claude_login, make_live_codex_login,
                     make_profile, write_json)
from shambles import migrate, providers, state, switcher
from shambles.stores.base import StoreUnavailableError

PREVIOUS = "credentials.json.previous"

#: How far one login's sign-in deadline moved across an ordinary 8-hour
#: refresh on a real machine (2026-11-13). Claude Code recomputes the
#: deadline at every refresh as now plus the seconds the server says remain,
#: so it wobbles by rounding and network delay while the real deadline holds.
MEASURED_JITTER_MS = -1375


def claude():
    return providers.load("claude", env={})


def codex():
    return providers.load("codex", env={})


def previous(paths, provider_id, name):
    return paths.profile_dir(provider_id, name) / PREVIOUS


def claude_login(access, refresh, expires):
    blob = credentials(refresh_expires_ms=expires, access_token=access)
    blob["claudeAiOauth"]["refreshToken"] = refresh
    return blob


def set_live_claude(paths, blob):
    write_json(paths.claude_dir / ".credentials.json", blob)


def set_live_codex(paths, blob):
    write_json(paths.home / ".codex" / "auth.json", blob)


def codex_login(email, refresh):
    blob = codex_auth(email=email, exp_ms=healthy_ms(9))
    blob["tokens"]["refresh_token"] = refresh
    blob["tokens"]["account_id"] = f"acct-{email}"
    return blob


# -- the basic promise -----------------------------------------------------

def test_a_stash_that_replaces_another_login_keeps_it(paths):
    """The marked profile's saved login is replaced by whatever is live."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    make_claude_json(paths, email="w@example.test")
    work = paths.credentials("claude", "Work").read_bytes()
    set_live_claude(paths, claude_login("a-new", "r-new", healthy_ms(20)))

    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)

    assert previous(paths, "claude", "Work").read_bytes() == work


def test_identical_bytes_leave_no_backup(paths):
    make_profile(paths, "codex", "Work", email="w@example.test", active=True)
    make_profile(paths, "codex", "Other", email="o@example.test")
    (paths.home / ".codex").mkdir()
    (paths.home / ".codex" / "auth.json").write_bytes(
        paths.credentials("codex", "Work").read_bytes())

    switcher.switch(paths, codex(), "Other", platform="linux",
                    sleep=lambda _: None)

    assert not previous(paths, "codex", "Work").exists()


def test_a_profile_saved_for_the_first_time_has_nothing_to_keep(paths):
    make_claude_json(paths, email="w@example.test")
    make_live_claude_login(paths)

    switcher.save_current_account(paths, claude(), "Work", platform="linux",
                                  sleep=lambda _: None)

    assert not previous(paths, "claude", "Work").exists()


@posix_modes_only
def test_the_backup_is_owner_only(paths):
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    make_claude_json(paths, email="w@example.test")
    set_live_claude(paths, claude_login("a-new", "r-new", healthy_ms(20)))

    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)

    mode = stat.S_IMODE(os.stat(previous(paths, "claude", "Work")).st_mode)
    assert mode == 0o600


def test_nothing_is_replaced_when_the_old_login_cannot_be_kept(
        paths, monkeypatch):
    """Keeping the old login is the condition for replacing it. A backup
    that cannot be written leaves the stash as it was."""
    from shambles.stores import FileStore

    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    make_claude_json(paths, email="w@example.test")
    work = paths.credentials("claude", "Work").read_bytes()
    set_live_claude(paths, claude_login("a-new", "r-new", healthy_ms(20)))
    real = FileStore.write

    def refuse_backup(store, blob):
        if store.path.name == PREVIOUS:
            raise StoreUnavailableError("disk full")
        return real(store, blob)

    monkeypatch.setattr(FileStore, "write", refuse_backup)
    with pytest.raises(StoreUnavailableError):
        switcher.switch(paths, claude(), "Other", platform="linux",
                        sleep=lambda _: None)

    assert paths.credentials("claude", "Work").read_bytes() == work
    assert state.read_active(paths, "claude") == "Work"


# -- one generation of the right thing --------------------------------------

def test_a_refresh_of_the_same_claude_login_does_not_displace_the_backup(
        paths):
    """Claude Code rotates the refresh token and keeps the deadline it was
    given at sign-in, give or take the second or so it loses recomputing it.
    A new token with that deadline is the same login, refreshed: the old
    token is spent, and the backup keeps what it had."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    make_claude_json(paths, email="w@example.test")
    deadline = healthy_ms(25)
    write_json(paths.credentials("claude", "Work"),
               claude_login("a1", "r1", deadline))
    write_json(previous(paths, "claude", "Work"),
               claude_login("a0", "r0-kept", healthy_ms(3)))
    kept = previous(paths, "claude", "Work").read_bytes()
    set_live_claude(paths, claude_login("a2", "r2",
                                        deadline + MEASURED_JITTER_MS))

    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)

    assert previous(paths, "claude", "Work").read_bytes() == kept


@pytest.mark.parametrize("provider_id", ["claude", "codex"])
def test_a_wrong_attribution_stays_recoverable_through_later_refreshes(
        paths, provider_id):
    """Work's saved login is replaced by Personal's (the address on file
    said Work), and then Personal's login refreshes twice and is re-stashed
    under Work each time. A backup moved along by every write would hold
    Personal's first token by then, and Work's login would be gone."""
    provider = providers.load(provider_id, env={})
    make_profile(paths, provider_id, "Work", email="w@example.test",
                 active=True)
    if provider_id == "claude":
        make_claude_json(paths, email="w@example.test")
        write_json(paths.credentials("claude", "Work"),
                   claude_login("aw", "rw", healthy_ms(20)))
        theirs = [claude_login(f"ap{i}", f"rp{i}",
                               healthy_ms(27) + i * MEASURED_JITTER_MS)
                  for i in range(3)]
        set_live = set_live_claude
    else:
        write_json(paths.credentials("codex", "Work"),
                   codex_login("w@example.test", "rw"))
        # Codex identity is inside the token, so the address cannot lie
        # about it. The same address on another ChatGPT account (a second
        # workspace) is what lets it through here.
        theirs = [codex_login("w@example.test", f"rp{i}") for i in range(3)]
        for blob in theirs:
            blob["tokens"]["account_id"] = "acct-other-workspace"
        set_live = set_live_codex
    work = paths.credentials(provider_id, "Work").read_bytes()

    for blob in theirs:
        set_live(paths, blob)
        switcher.stash_live_login(paths, provider, "Work", platform="linux",
                                  sleep=lambda _: None)

    assert previous(paths, provider_id, "Work").read_bytes() == work


# -- the migration writes a stash too ---------------------------------------

def test_the_migration_keeps_a_login_it_replaces(paths):
    """The pre-1.0 conversion files the linked profile's live login over
    whatever an earlier, interrupted run filed."""
    from helpers import make_legacy_profile

    make_legacy_profile(paths, "Work", email="w@example.test", sessions=2)
    os.symlink(paths.legacy_profiles_dir / "Work", paths.claude_dir,
               target_is_directory=True)
    make_claude_json(paths, email="w@example.test")
    paths.ensure_profile("claude", "Work")
    earlier = json.dumps(claude_login("a-old", "r-old", healthy_ms(4)))
    paths.credentials("claude", "Work").write_text(earlier, encoding="utf-8")

    migrate.run(paths, now_ms=1_785_000_000_000)

    assert previous(paths, "claude", "Work").read_text(
        encoding="utf-8") == earlier


def test_two_claude_logins_a_few_minutes_apart_are_different_logins(paths):
    """The tolerance is for the wobble of one deadline, not a window in which
    any two sign-ins look alike."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    make_claude_json(paths, email="w@example.test")
    deadline = healthy_ms(25)
    write_json(paths.credentials("claude", "Work"),
               claude_login("aw", "rw", deadline))
    work = paths.credentials("claude", "Work").read_bytes()
    set_live_claude(paths, claude_login("ax", "rx", deadline + 5 * 60_000))

    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)

    assert previous(paths, "claude", "Work").read_bytes() == work


# -- found by an independent review of the first version ---------------------

def emptied(blob_bytes):
    data = json.loads(blob_bytes)
    data["claudeAiOauth"]["refreshToken"] = ""
    return data


def test_an_emptied_login_never_replaces_a_working_one(paths):
    """A login cleared in place keeps its deadline, so it looked like the
    same login refreshed: no backup, and the working token was replaced by
    one that cannot sign in. Keeping the working one is never worse."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    make_claude_json(paths, email="w@example.test")
    work = paths.credentials("claude", "Work").read_bytes()
    set_live_claude(paths, emptied(work))

    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)

    assert paths.credentials("claude", "Work").read_bytes() == work


@pytest.mark.parametrize("apart_ms, same", [
    (abs(MEASURED_JITTER_MS), True),      # one login, refreshed
    (10_000, True),                       # the edge of the tolerance
    (11_000, False),
    (30_000, False),                      # two sign-ins half a minute apart
])
def test_how_far_apart_two_deadlines_may_be_and_still_be_one_login(apart_ms,
                                                                  same):
    deadline = healthy_ms(25)
    older = json.dumps(claude_login("a1", "r1", deadline)).encode()
    newer = json.dumps(claude_login("a2", "r2", deadline + apart_ms)).encode()

    assert claude().same_login(older, newer) is same


@pytest.mark.parametrize("value", ["true", "NaN", "Infinity", '""', "null"])
def test_a_deadline_that_is_not_a_number_proves_nothing(value):
    blob = ('{"claudeAiOauth": {"refreshToken": "r", '
            f'"refreshTokenExpiresAt": {value}}}}}').encode()
    assert claude().same_login(blob, blob) is False


def test_two_codex_logins_in_one_workspace_are_different_logins():
    """tokens.account_id is the ChatGPT account, which a Team workspace
    shares among its members. The address in the token tells them apart."""
    mine = codex_login("w@example.test", "rw")
    theirs = codex_login("colleague@example.test", "rc")
    for blob in (mine, theirs):
        blob["tokens"]["account_id"] = "acct-team"

    assert codex().same_login(json.dumps(mine).encode(),
                              json.dumps(theirs).encode()) is False


def test_a_codex_token_that_names_nobody_proves_nothing():
    mine = codex_login("w@example.test", "r1")
    later = codex_login("w@example.test", "r2")
    later["tokens"]["id_token"] = "unreadable"

    assert codex().same_login(json.dumps(mine).encode(),
                              json.dumps(later).encode()) is False


def test_identical_bytes_are_not_written_again(paths, monkeypatch):
    """With no deadline there is no lineage, so only the identity check
    keeps a backup from being written over identical bytes."""
    from shambles import profiles
    from shambles.stores import FileStore

    paths.ensure_profile("claude", "Work")
    blob = json.dumps({"claudeAiOauth": {"accessToken": "a",
                                         "refreshToken": "r"}}).encode()
    paths.credentials("claude", "Work").write_bytes(blob)
    writes = []
    monkeypatch.setattr(FileStore, "write",
                        lambda store, payload: writes.append(store.path))

    profiles.save_credential(paths, claude(), "Work", blob)

    assert writes == []


def test_an_empty_stash_is_not_kept(paths):
    from shambles import profiles

    paths.ensure_profile("claude", "Work")
    paths.credentials("claude", "Work").write_bytes(b"")

    profiles.save_credential(paths, claude(), "Work",
                             json.dumps(claude_login("a", "r", 1)).encode())

    assert not previous(paths, "claude", "Work").exists()


def test_a_failed_write_leaves_the_backup_as_it_was(paths, monkeypatch):
    """The backup is written first. If the login itself then cannot be
    written, the backup has been replaced by a copy of what is still there,
    and the one it held is gone."""
    from shambles import profiles
    from shambles.stores import FileStore

    paths.ensure_profile("claude", "Work")
    write_json(paths.credentials("claude", "Work"),
               claude_login("aw", "rw", healthy_ms(20)))
    write_json(previous(paths, "claude", "Work"),
               claude_login("a0", "r0-kept", healthy_ms(3)))
    kept = previous(paths, "claude", "Work").read_bytes()
    real = FileStore.write

    def refuse_login(store, blob):
        if store.path.name == "credentials.json":
            raise StoreUnavailableError("locked")
        return real(store, blob)

    monkeypatch.setattr(FileStore, "write", refuse_login)
    with pytest.raises(StoreUnavailableError):
        profiles.save_credential(
            paths, claude(), "Work",
            json.dumps(claude_login("ax", "rx", healthy_ms(10))).encode())

    assert previous(paths, "claude", "Work").read_bytes() == kept
