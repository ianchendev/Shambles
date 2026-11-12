"""How the service reports a refusal: the code has to mean what it says."""

import pytest

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
