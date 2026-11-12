"""Where the live login goes before something replaces it.

``switch`` files the outgoing login under a saved profile and only then puts
the incoming one in its place. Every test here is a state in which that first
step used to be skipped or misdirected, so a refresh token was overwritten
with no error and no copy: no profile marked, the marked profile gone, a
switch that stopped between its two writes, a vendor config that names the
wrong account or none.
"""

import json

import pytest

from helpers import (NOW, credentials, healthy_ms, make_claude_json,
                     make_live_claude_login, make_live_codex_login,
                     make_profile)
from shambles import eject, providers, state, switcher
from shambles.app.service import ShamblesService
from shambles.errors import (AlreadyManagedError, DriftedLoginError,
                             ShamblesError, SwitchFailedError)
from shambles.stores.base import StoreUnavailableError

PROVIDER_IDS = ["claude", "codex"]


@pytest.fixture(params=PROVIDER_IDS)
def provider(request):
    return providers.load(request.param)


def lapsed_ms():
    """An expiry three days behind the real clock: CLOSED for both vendors."""
    return healthy_ms(-3)


def live_path(paths, provider):
    if provider.id == "claude":
        return paths.claude_dir / ".credentials.json"
    return paths.home / ".codex" / "auth.json"


def service(paths):
    return ShamblesService(paths=paths, providers=providers.all_providers(env={}),
                           platform="linux", clock_ms=lambda: NOW)


@pytest.fixture
def deferred_login(monkeypatch):
    """Replace only the external process; switching and disk reads stay real."""
    processes = []

    class DeferredLoginProcess:
        running = False

        def __init__(self, argv, **kwargs):
            processes.append(self)

        def start(self, *, on_line, on_exit):
            self.running = True

        def cancel(self):
            self.running = False

    monkeypatch.setattr("shambles.app.service.login.LoginProcess",
                        DeferredLoginProcess)
    return processes


# ---- a live login that no profile holds ----------------------------------
#
# switch() files the outgoing login under the marked profile before it puts
# the incoming one in its place. With no usable marker there is nowhere to
# file it, and it used to be overwritten anyway: the one copy of that refresh
# token, gone without an error.

def seed_unsaved(paths, provider, email="stranger@example.test"):
    """A live login that no saved profile holds a copy of."""
    if provider.id == "claude":
        make_claude_json(paths, email=email)
        return make_live_claude_login(paths, access_token="tok-unsaved")
    return make_live_codex_login(paths, email=email, exp_ms=healthy_ms(7))


def test_switching_with_no_marker_keeps_a_login_that_is_saved_nowhere(
        paths, provider):
    """Profiles exist, none is marked, and the vendor is signed in. That is
    what a machine looks like after Eject, or after the marker is lost."""
    make_profile(paths, provider.id, "Other", email="o@example.test")
    live = seed_unsaved(paths, provider)
    before = live.read_bytes()

    with pytest.raises(AlreadyManagedError) as raised:
        switcher.switch(paths, provider, "Other", platform="linux",
                        sleep=lambda _: None)

    assert "Save your current account first" in str(raised.value)
    assert live.read_bytes() == before
    assert state.read_active(paths, provider.id) is None


def test_switching_from_a_vanished_profile_keeps_the_live_login(
        paths, provider):
    """The marker names a profile whose directory is gone, so the copy-out is
    skipped. The login it would have saved must not then be replaced."""
    make_profile(paths, provider.id, "Other", email="o@example.test")
    paths.active_marker(provider.id).write_text("Gone\n", encoding="utf-8")
    live = seed_unsaved(paths, provider)
    before = live.read_bytes()

    with pytest.raises(AlreadyManagedError):
        switcher.switch(paths, provider, "Other", platform="linux",
                        sleep=lambda _: None)

    assert live.read_bytes() == before
    assert state.read_active(paths, provider.id) == "Gone"


def test_switching_with_no_marker_is_allowed_when_the_login_is_saved(
        paths, provider):
    """Nothing to lose: a profile already holds these exact bytes."""
    make_profile(paths, provider.id, "Work", email="w@example.test")
    make_profile(paths, provider.id, "Other", email="o@example.test")
    live_path(paths, provider).parent.mkdir(parents=True, exist_ok=True)
    work = paths.credentials(provider.id, "Work").read_bytes()
    live_path(paths, provider).write_bytes(work)

    switcher.switch(paths, provider, "Other", platform="linux",
                    sleep=lambda _: None)

    assert state.read_active(paths, provider.id) == "Other"
    assert paths.credentials(provider.id, "Work").read_bytes() == work


def test_switching_with_no_marker_and_no_login_has_nothing_to_protect(
        paths, provider):
    make_profile(paths, provider.id, "Other", email="o@example.test")
    other = paths.credentials(provider.id, "Other").read_bytes()

    switcher.switch(paths, provider, "Other", platform="linux",
                    sleep=lambda _: None)

    assert live_path(paths, provider).read_bytes() == other
    assert state.read_active(paths, provider.id) == "Other"


def test_adding_with_no_marker_keeps_a_login_that_is_saved_nowhere(
        paths, provider):
    """Add clears the live slot for the vendor to fill. Same loss, same
    refusal, and no empty profile left behind by the attempt."""
    make_profile(paths, provider.id, "Other", email="o@example.test")
    live = seed_unsaved(paths, provider)
    before = live.read_bytes()

    with pytest.raises(AlreadyManagedError):
        switcher.add_empty_account(paths, provider, "Fresh", platform="linux",
                                   sleep=lambda _: None)

    assert live.read_bytes() == before
    assert state.profile_names(paths, provider.id) == ["Other"]


def test_a_refused_add_leaves_no_empty_profile_behind(paths):
    """The directory was created before the switch that refused, so every
    refused Add left a blank card, and the name could not be used again."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_claude_json(paths, email="stranger@example.test")
    make_live_claude_login(paths, access_token="tok-stranger")

    with pytest.raises(DriftedLoginError):
        switcher.add_empty_account(paths, claude, "Fresh", platform="linux",
                                   sleep=lambda _: None)

    assert state.profile_names(paths, "claude") == ["Work"]


def test_begin_relogin_goes_back_to_whoever_holds_the_live_login(
        paths, provider):
    """No marker, but the live bytes are Work's own stash: nothing is lost by
    switching, and Work is where a cancelled sign-in should return to."""
    make_profile(paths, provider.id, "Work", email="w@example.test")
    make_profile(paths, provider.id, "Old", email="o@example.test",
                 refresh_expires_ms=lapsed_ms())
    live_path(paths, provider).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, provider).write_bytes(
        paths.credentials(provider.id, "Work").read_bytes())

    assert switcher.begin_relogin(paths, provider, "Old", platform="linux",
                                  sleep=lambda _: None) == "Work"


# ---- a switch that stops between its two writes ---------------------------

def test_an_interrupted_switch_does_not_cost_the_outgoing_token(
        paths, monkeypatch):
    """The live credential was replaced and then the marker could not be
    written. The marker still names Work while the live login is Personal's,
    and ~/.claude.json has not been touched yet, so by address everything
    still agrees. The next switch used to file Personal's token under Work.

    What saves it is that the live bytes are still exactly Personal's stash.
    That holds until the vendor next refreshes the token; after that nothing
    on disk can tell whose login it is, and this protection is gone."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    make_claude_json(paths, email="w@example.test")
    make_live_claude_login(paths, access_token="tok-Work")
    work = paths.credentials("claude", "Work").read_bytes()
    personal = paths.credentials("claude", "Personal").read_bytes()

    real = state.write_active

    def disk_full(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(state, "write_active", disk_full)
    with pytest.raises(SwitchFailedError):
        switcher.switch(paths, claude, "Personal", platform="linux",
                        sleep=lambda _: None)
    monkeypatch.setattr(state, "write_active", real)

    assert state.read_active(paths, "claude") == "Work"
    assert live_path(paths, claude).read_bytes() == personal

    # The user tries again, as anybody would.
    switcher.switch(paths, claude, "Personal", platform="linux",
                    sleep=lambda _: None)

    assert paths.credentials("claude", "Work").read_bytes() == work
    assert paths.credentials("claude", "Personal").read_bytes() == personal
    assert state.read_active(paths, "claude") == "Personal"
    assert state.profile_email(paths, claude, "Personal") == "p@example.test"


def test_stashing_refuses_a_login_another_profile_already_holds(paths):
    """Byte for byte Personal's stash, so it is Personal's login whatever the
    address on file says. Filing it under Work would replace Work's token."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    make_claude_json(paths, email="w@example.test")
    personal = paths.credentials("claude", "Personal").read_bytes()
    live_path(paths, claude).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, claude).write_bytes(personal)
    work = paths.credentials("claude", "Work").read_bytes()

    with pytest.raises(DriftedLoginError) as raised:
        switcher.stash_live_login(paths, claude, "Work", platform="linux",
                                  sleep=lambda _: None)

    # Decided by the bytes, so worded from them. The two addresses agree
    # here, and "signed in as w@, but Work holds w@" explains nothing.
    assert "the one saved as 'Personal'" in str(raised.value)
    assert "w@example.test" not in str(raised.value)
    assert paths.credentials("claude", "Work").read_bytes() == work


# ---- the identity filed beside a credential -------------------------------

def test_stashing_never_erases_a_profiles_identity(paths):
    """~/.claude.json can carry a usage cache and, for a while, no account:
    Claude Code drops the account on sign-out and rewrites the rest from
    memory. Filing that as the profile's identity left it with no address,
    which also switches the drift check off for it from then on."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    make_live_claude_login(paths, access_token="tok-Work")
    paths.claude_json.write_text(json.dumps({"cachedUsageUtilization": {
        "accountUuid": "uuid-a", "utilization": {}}}), encoding="utf-8")

    switcher.switch(paths, claude, "Personal", platform="linux",
                    sleep=lambda _: None)

    assert state.profile_email(paths, claude, "Work") == "w@example.test"


def test_stashing_with_no_live_login_files_no_identity(paths):
    """An identity describes a login. With the store empty there is none, and
    whatever ~/.claude.json says belongs to some other moment: here, a session
    still running as Work put its account back after Add had cleared it.
    Filing that made the new, empty profile read as Work's, and the sign-in
    it then offered was pre-filled with Work's address."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_claude_json(paths, email="w@example.test")
    make_live_claude_login(paths, access_token="tok-Work")
    created = switcher.add_empty_account(paths, claude, "New", platform="linux",
                                         sleep=lambda _: None)
    make_claude_json(paths, email="w@example.test")   # the running session

    switcher.abandon_new_account(paths, claude, created, "Work",
                                 platform="linux", sleep=lambda _: None)

    assert state.read_active(paths, "claude") == "Work"
    assert state.profile_email(paths, claude, "New") is None


def test_saving_a_login_a_profile_already_holds_marks_that_profile(
        paths, provider):
    """No marker, and the live bytes are Work's own stash: the state Eject
    leaves until the vendor next refreshes. The window offers Save here. A
    second copy under a new name is never what was meant, and refusing would
    make that button one that can only say no. What is missing is the marker,
    so that is what Save writes, and it says which profile it was."""
    make_profile(paths, provider.id, "Work", email="w@example.test")
    live_path(paths, provider).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, provider).write_bytes(
        paths.credentials(provider.id, "Work").read_bytes())

    saved = switcher.save_current_account(paths, provider, "Again",
                                          platform="linux",
                                          sleep=lambda _: None)

    assert saved == "Work"
    assert state.read_active(paths, provider.id) == "Work"
    assert state.profile_names(paths, provider.id) == ["Work"]


def test_save_works_in_the_state_eject_leaves_behind(paths, provider):
    """End to end: eject, come back, press Save."""
    make_profile(paths, provider.id, "Work", email="w@example.test",
                 active=True)
    live_path(paths, provider).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, provider).write_bytes(
        paths.credentials(provider.id, "Work").read_bytes())
    eject.run(paths, [provider], platform="linux", sleep=lambda _: None)
    assert state.inspect(paths, provider, platform="linux").kind == state.UNKNOWN

    switcher.save_current_account(paths, provider, "Default", platform="linux",
                                  sleep=lambda _: None)

    assert state.inspect(paths, provider, platform="linux").kind == state.MANAGED


# --- A login no profile holds must survive every way of starting one -------

def test_login_keeps_a_live_login_that_is_saved_nowhere(paths, deferred_login,
                                                        fake_vendor):
    """start_login makes the target live with a plain switch. With no profile
    marked, that replaced whatever the vendor was signed in as, and the
    window's own re-login guard was never consulted."""
    fake_vendor("codex")    # on PATH, so the refusal is not for lack of a CLI
    make_profile(paths, "codex", "Old", email="o@example.test",
                 refresh_expires_ms=NOW - 1)
    live = make_live_codex_login(paths, email="stranger@example.test",
                                 exp_ms=healthy_ms(7))
    before = live.read_bytes()
    done = []

    handle = service(paths).start_login("codex", "Old", lambda line: None,
                                        done.append)

    assert handle.wait(timeout=1)
    assert done[0].ok is False
    assert not any(process.running for process in deferred_login), (
        "the vendor was started anyway")
    assert live.read_bytes() == before
    assert state.read_active(paths, "codex") is None


# ---- removing the profile that holds the live login ----------------------

def test_removing_the_profile_that_holds_the_live_login_is_refused(paths):
    """The marker says Work; the bytes in the store are Personal's. Remove
    checked only the marker, so it deleted the one saved copy of the login
    that was actually live -- and with that copy gone nothing could tell the
    live login was not Work's, so the next switch filed it under Work."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    make_claude_json(paths, email="w@example.test")
    live_path(paths, claude).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, claude).write_bytes(
        paths.credentials("claude", "Personal").read_bytes())

    with pytest.raises(AlreadyManagedError) as raised:
        switcher.remove_profile(paths, claude, "Personal", platform="linux")

    assert "signed in as" in str(raised.value)
    assert paths.credentials("claude", "Personal").exists()


def seed_duplicates(paths, provider):
    """One login saved under two names, Beta marked, and live."""
    make_profile(paths, provider.id, "Alpha", email="same@example.test")
    make_profile(paths, provider.id, "Beta", email="same@example.test",
                 active=True)
    blob = paths.credentials(provider.id, "Alpha").read_bytes()
    paths.credentials(provider.id, "Beta").write_bytes(blob)
    if provider.id == "claude":
        make_claude_json(paths, email="same@example.test")
    live_path(paths, provider).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, provider).write_bytes(blob)
    return blob


def test_the_unmarked_duplicate_of_the_live_login_can_be_removed(
        paths, provider):
    """Holding the live bytes is a reason to refuse only when nobody else
    does. With two holders the unmarked one is a spare copy, and refusing
    left a duplicate that could never be cleaned up."""
    blob = seed_duplicates(paths, provider)

    switcher.remove_profile(paths, provider, "Alpha", platform="linux")

    assert state.profile_names(paths, provider.id) == ["Beta"]
    assert paths.credentials(provider.id, "Beta").read_bytes() == blob
    assert live_path(paths, provider).read_bytes() == blob


def test_following_the_refusal_gets_a_duplicate_removed(paths, provider):
    """'Switch to another profile first, then remove this one.'"""
    seed_duplicates(paths, provider)

    with pytest.raises(AlreadyManagedError):
        switcher.remove_profile(paths, provider, "Beta", platform="linux")
    switcher.switch(paths, provider, "Alpha", platform="linux",
                    sleep=lambda _: None)
    switcher.remove_profile(paths, provider, "Beta", platform="linux")

    assert state.profile_names(paths, provider.id) == ["Alpha"]


def test_a_parked_profile_can_still_be_removed(paths, provider):
    make_profile(paths, provider.id, "Work", email="w@example.test",
                 active=True)
    make_profile(paths, provider.id, "Personal", email="p@example.test")
    live_path(paths, provider).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, provider).write_bytes(
        paths.credentials(provider.id, "Work").read_bytes())

    switcher.remove_profile(paths, provider, "Personal", platform="linux")

    assert state.profile_names(paths, provider.id) == ["Work"]


# ---- undoing an Add that came to nothing ----------------------------------

def test_a_cancelled_add_does_not_undo_a_switch_made_elsewhere(paths, provider):
    """Two windows. One is waiting on the vendor's sign-in for a new profile;
    in the other the user switches to a profile that has no login yet. When
    the first is cancelled it saw an empty slot, took that for its own, and
    switched the user back off the profile they had just chosen.

    abandon_relogin already refuses unless the profile it is undoing is still
    the live one. The two functions now share that rule."""
    make_profile(paths, provider.id, "Work", email="w@example.test",
                 active=True)
    make_profile(paths, provider.id, "Spare", token=False)
    live_path(paths, provider).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, provider).write_bytes(
        paths.credentials(provider.id, "Work").read_bytes())
    created = switcher.add_empty_account(paths, provider, "New",
                                         platform="linux", sleep=lambda _: None)
    switcher.switch(paths, provider, "Spare", platform="linux",   # elsewhere
                    sleep=lambda _: None)

    assert switcher.abandon_new_account(paths, provider, created, "Work",
                                        platform="linux",
                                        sleep=lambda _: None) is False
    assert state.read_active(paths, provider.id) == "Spare"



# ---- filing bytes a profile already holds ---------------------------------

def test_a_holder_with_no_identity_is_not_given_the_address_on_file(paths):
    """No marker, the live bytes are Personal's stash, and ~/.claude.json
    names Work because a session is still running as Work. The bytes are
    already safe under Personal, so there is nothing to copy; the only thing
    a stash would add is that address, on the wrong profile."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test")
    make_profile(paths, "claude", "Personal")           # credential, no sidecar
    make_profile(paths, "claude", "Other", email="o@example.test")
    make_claude_json(paths, email="w@example.test")
    live_path(paths, claude).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, claude).write_bytes(
        paths.credentials("claude", "Personal").read_bytes())

    switcher.switch(paths, claude, "Other", platform="linux",
                    sleep=lambda _: None)

    assert state.profile_email(paths, claude, "Personal") is None
    assert not paths.account("claude", "Personal").exists()


def test_finishing_an_interrupted_switch_does_not_mislabel_the_incoming(
        paths, monkeypatch):
    """The same, reached the way it really happens: the profile switched to
    has a login and no stored address yet."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal")           # credential, no sidecar
    make_claude_json(paths, email="w@example.test")
    make_live_claude_login(paths, access_token="tok-Work")
    work = paths.credentials("claude", "Work").read_bytes()

    real = state.write_active

    def disk_full(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(state, "write_active", disk_full)
    with pytest.raises(SwitchFailedError):
        switcher.switch(paths, claude, "Personal", platform="linux",
                        sleep=lambda _: None)
    monkeypatch.setattr(state, "write_active", real)
    switcher.switch(paths, claude, "Personal", platform="linux",
                    sleep=lambda _: None)

    assert paths.credentials("claude", "Work").read_bytes() == work
    assert state.profile_email(paths, claude, "Personal") is None


# ---- what counts as a login worth refusing for ----------------------------

def signed_out_husk():
    blob = credentials(access_token="tok-gone")
    blob["claudeAiOauth"]["refreshToken"] = ""       # cleared by the vendor
    return json.dumps(blob).encode("utf-8")


@pytest.mark.parametrize("live_bytes", [signed_out_husk(), b""],
                         ids=["signed-out-husk", "zero-byte-file"])
def test_bytes_that_are_not_a_login_are_not_a_reason_to_refuse(paths,
                                                              live_bytes):
    """'Save your current account first' about a credential the vendor has
    emptied, or an empty file. Neither can sign in, and the only way past the
    refusal was to save it as a profile that was dead on arrival."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Other", email="o@example.test")
    live_path(paths, claude).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, claude).write_bytes(live_bytes)

    switcher.switch(paths, claude, "Other", platform="linux",
                    sleep=lambda _: None)

    assert state.read_active(paths, "claude") == "Other"


def test_an_empty_store_is_not_drift_whatever_the_address_on_file_says(paths):
    """Nobody is signed in. ~/.claude.json still names a stranger, so the
    state read as DRIFTED and the switch was refused with 'Signed in as
    stranger', with nothing to save and no way on but a new vendor sign-in."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    make_claude_json(paths, email="stranger@example.test")
    work = paths.credentials("claude", "Work").read_bytes()
    assert not live_path(paths, claude).exists()

    switcher.switch(paths, claude, "Personal", platform="linux",
                    sleep=lambda _: None)

    assert state.read_active(paths, "claude") == "Personal"
    assert paths.credentials("claude", "Work").read_bytes() == work
    assert state.profile_email(paths, claude, "Work") == "w@example.test"


def test_begin_relogin_still_comes_back_to_the_marked_profile_from_an_empty_store(
        paths, provider):
    """Nothing is live, so nothing is at stake, but the marked profile is
    still where the user was and where a cancelled sign-in returns to."""
    make_profile(paths, provider.id, "Work", email="w@example.test",
                 active=True)
    make_profile(paths, provider.id, "Old", email="o@example.test",
                 refresh_expires_ms=lapsed_ms())

    assert switcher.begin_relogin(paths, provider, "Old", platform="linux",
                                  sleep=lambda _: None) == "Work"


# ---- a live file caught between truncate and write ------------------------

def test_an_empty_live_file_does_not_replace_the_saved_token(paths, provider):
    """Neither vendor replaces its credential file atomically, so a read can
    land after the truncate and before the write and see zero bytes. Those
    were filed as the outgoing login: the saved token replaced by an empty
    file, and then the live slot overwritten too."""
    make_profile(paths, provider.id, "Work", email="w@example.test",
                 active=True)
    make_profile(paths, provider.id, "Other", email="o@example.test")
    if provider.id == "claude":
        make_claude_json(paths, email="w@example.test")
    live_path(paths, provider).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, provider).write_bytes(b"")
    work = paths.credentials(provider.id, "Work").read_bytes()

    switcher.switch(paths, provider, "Other", platform="linux",
                    sleep=lambda _: None)

    assert paths.credentials(provider.id, "Work").read_bytes() == work


def test_an_empty_live_file_is_not_restashed(paths):
    """The same read, on the path that runs at every refresh with no click."""
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="w@example.test", active=True)
    live_path(paths, codex).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, codex).write_bytes(b"")
    work = paths.credentials("codex", "Work").read_bytes()

    assert switcher.restash_active(paths, codex, platform="linux") is False
    assert paths.credentials("codex", "Work").read_bytes() == work


# ---- an Add whose login did arrive ----------------------------------------

def test_abandoning_keeps_an_add_whose_login_another_window_already_filed(
        paths):
    """Codex. The vendor signs in, and a second window's refresh files that
    login under the new profile before the first window gives up. The slot
    then holds exactly what the profile holds, which is the test
    abandon_relogin uses for 'nothing new arrived'. For a new profile
    anything in the slot is the login it was waiting for."""
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="w@example.test", active=True)
    make_live_codex_login(paths, email="w@example.test", exp_ms=healthy_ms())
    paths.credentials("codex", "Work").write_bytes(
        live_path(paths, codex).read_bytes())
    created = switcher.add_empty_account(paths, codex, "New", platform="linux",
                                         sleep=lambda _: None)
    make_live_codex_login(paths, email="new@example.test")    # the vendor
    assert switcher.restash_active(paths, codex, platform="linux")  # window 2

    assert switcher.abandon_new_account(paths, codex, created, "Work",
                                        platform="linux",
                                        sleep=lambda _: None) is False
    assert state.read_active(paths, "codex") == "New"


# ---- an Add that fails after it has become the live profile ---------------

def test_an_add_that_fails_after_the_marker_moved_keeps_its_directory(
        paths, monkeypatch):
    """The cleanup after a refused Add removes the new directory. Once the
    marker names it, removing it would leave a marker pointing at nothing."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_claude_json(paths, email="w@example.test")
    make_live_claude_login(paths, access_token="tok-Work")

    def splice_fails(self, data, *, home):
        raise StoreUnavailableError("the config is held by another process")

    monkeypatch.setattr(type(claude), "companion_write", splice_fails)
    with pytest.raises(ShamblesError):
        switcher.add_empty_account(paths, claude, "Fresh", platform="linux",
                                   sleep=lambda _: None)

    assert state.read_active(paths, "claude") == "Fresh"
    assert paths.profile_dir("claude", "Fresh").is_dir()
