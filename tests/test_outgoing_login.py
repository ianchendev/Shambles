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

from helpers import (NOW, healthy_ms, make_claude_json,
                     make_live_claude_login, make_live_codex_login,
                     make_profile)
from shambles import providers, state, switcher
from shambles.app.service import ShamblesService
from shambles.errors import AlreadyManagedError, SwitchFailedError

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
    from shambles.errors import DriftedLoginError

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
    still agrees. The next switch used to file Personal's token under Work."""
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
    from shambles.errors import DriftedLoginError

    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    make_claude_json(paths, email="w@example.test")
    personal = paths.credentials("claude", "Personal").read_bytes()
    live_path(paths, claude).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, claude).write_bytes(personal)
    work = paths.credentials("claude", "Work").read_bytes()

    with pytest.raises(DriftedLoginError):
        switcher.stash_live_login(paths, claude, "Work", platform="linux",
                                  sleep=lambda _: None)

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


def test_saving_a_login_a_profile_already_holds_names_that_profile(
        paths, provider):
    """No marker, and the live bytes are Work's own stash. Saving it again
    under a second name is never what was meant; saying where it already is
    lets the user switch to it, which puts the marker back."""
    make_profile(paths, provider.id, "Work", email="w@example.test")
    live_path(paths, provider).parent.mkdir(parents=True, exist_ok=True)
    live_path(paths, provider).write_bytes(
        paths.credentials(provider.id, "Work").read_bytes())

    with pytest.raises(AlreadyManagedError) as raised:
        switcher.save_current_account(paths, provider, "Again",
                                      platform="linux", sleep=lambda _: None)

    assert "already saved as 'Work'" in str(raised.value)
    assert state.profile_names(paths, provider.id) == ["Work"]


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
