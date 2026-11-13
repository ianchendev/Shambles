"""How the service reports a refusal: the code has to mean what it says."""

import pytest

from conftest import posix_only
from helpers import NOW, healthy_ms, make_live_codex_login, make_profile
from shambles import providers, switcher
from shambles.app.service import ShamblesService
from shambles.stores.base import StoreUnavailableError


def service(paths):
    return ShamblesService(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux", clock_ms=lambda: NOW)


def test_a_more_specific_store_error_is_still_a_store_error(paths, monkeypatch):
    """Codes were looked up by exact class, so a subclass of a mapped error
    fell through to 'operation_refused' and lost its recovery advice."""
    class StoreLocked(StoreUnavailableError):
        pass

    make_profile(paths, "codex", "Work", email="w@example.test", active=True)
    make_profile(paths, "codex", "Other", email="o@example.test")

    def locked(*args, **kwargs):
        raise StoreLocked("The store is locked.")

    monkeypatch.setattr(switcher, "switch", locked)

    result = service(paths).switch("codex", "Other")

    assert result.ok is False
    assert result.error.code == "store_unavailable"
    assert "Unlock" in result.error.recovery


@pytest.mark.parametrize("action", ["save_current", "add"])
def test_a_refused_save_or_add_is_not_reported_as_a_protected_profile(
        paths, action):
    """AlreadyManagedError carries four different refusals. Only the one
    raised by Remove means 'this is the active profile'."""
    if action == "save_current":
        make_profile(paths, "codex", "Work", email="w@example.test",
                     active=True)
    make_live_codex_login(paths, email="w@example.test", exp_ms=healthy_ms())

    result = getattr(service(paths), action)("codex", "Personal")

    assert result.ok is False
    assert result.error.code == "operation_refused"


def test_removing_the_active_profile_is_still_reported_as_protected(paths):
    make_profile(paths, "codex", "Work", email="w@example.test", active=True)
    app = service(paths)

    result = app.remove(app.plan_remove("codex", "Work"))

    assert result.ok is False
    assert result.error.code == "active_profile_protected"
    assert "Switch away" in result.error.recovery


# -- a sign-in that is refused before the vendor ever runs ------------------

class NeverStarted:
    """Stands in for the vendor process; a refusal must not reach it."""
    running = False

    def __init__(self, argv, **kwargs):
        pass

    def start(self, *, on_line, on_exit):
        self.running = True

    def cancel(self):
        self.running = False


@posix_only
def test_a_refused_sign_in_says_why(paths, monkeypatch, fake_vendor):
    """Every login failure was reported as 'The login could not be
    completed.' That is right for a store error, whose text carries paths
    and whatever the OS said. It is wrong for the switcher's own refusals,
    which are written for the user and are the only place the way out is
    named: here, that the machine is signed in as somebody else."""
    monkeypatch.setattr("shambles.app.service.login.LoginProcess", NeverStarted)
    fake_vendor("codex")
    make_profile(paths, "codex", "Work", email="w@example.test", active=True)
    make_profile(paths, "codex", "Old", email="o@example.test",
                 refresh_expires_ms=NOW - 1)
    make_live_codex_login(paths, email="stranger@example.test",
                          exp_ms=healthy_ms(7))
    done = []

    service(paths).start_login("codex", "Old", lambda line: None, done.append)

    assert done[0].ok is False
    assert "Signed in as stranger@example.test" in done[0].error.message


@posix_only
def test_a_store_failure_during_sign_in_still_says_nothing_private(
        paths, monkeypatch, fake_vendor):
    """The other half: what the store said stays out of the result."""
    monkeypatch.setattr("shambles.app.service.login.LoginProcess", NeverStarted)
    fake_vendor("codex")
    make_profile(paths, "codex", "Old", email="o@example.test",
                 refresh_expires_ms=NOW - 1)

    def locked(*args, **kwargs):
        raise StoreUnavailableError("/private/path: the store is locked")

    monkeypatch.setattr(switcher, "switch", locked)
    monkeypatch.setattr(switcher, "begin_relogin", locked, raising=False)
    done = []

    service(paths).start_login("codex", "Old", lambda line: None, done.append)

    assert done[0].ok is False
    assert "/private/path" not in str(done[0].to_dict())
