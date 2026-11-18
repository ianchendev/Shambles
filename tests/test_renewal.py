"""D11: renewing a parked account keeps you on the one you were using.

Signing an account in has to make it live for the length of the sign-in,
because the vendor writes its new login to the one live location. When that
account was parked and its login still worked -- a renewal before its
deadline -- the user only wanted it renewed, so once the new login is saved
Shambles switches back. A lapsed account signed in to be used stays live,
as before.
"""

import datetime

import pytest

from helpers import (DAY_MS, healthy_ms, make_claude_json,
                     make_live_claude_login, make_profile)
from shambles import providers, state
from shambles.app.service import ShamblesService


@pytest.fixture
def vendor(monkeypatch):
    """The vendor's login, finished by the test. Disk stays real."""
    processes = []

    class Deferred:
        running = False

        def __init__(self, argv, **kwargs):
            processes.append(self)

        def start(self, *, on_line, on_exit):
            self.running = True
            self.on_exit = on_exit

        def finish(self, code=0):
            self.running = False
            self.on_exit(code)

        def cancel(self):
            if self.running:
                self.finish(-15)

    monkeypatch.setattr("shambles.app.service.login.LoginProcess", Deferred)
    monkeypatch.setattr("shambles.app.service.login.available",
                        lambda provider: True)
    return processes


def service(paths):
    # The real clock: liveness is judged against it (see healthy_ms).
    return ShamblesService(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux")


def work_live_admin_parked(paths, *, admin_expires_ms):
    make_profile(paths, "claude", "Work", email="work@example.test",
                 active=True)
    make_profile(paths, "claude", "Admin", email="admin@example.test",
                 refresh_expires_ms=admin_expires_ms)
    make_claude_json(paths, email="work@example.test")
    make_live_claude_login(paths, access_token="tok-Work")


def sign_in(paths, vendor, name, *, new_expiry):
    """Run the sign-in; the vendor writes a fresh login for ``name``."""
    done = []
    handle = service(paths).start_login("claude", name, lambda line: None,
                                        done.append)
    make_claude_json(paths, email=f"{name.lower()}@example.test")
    make_live_claude_login(paths, access_token=f"tok-{name}-renewed",
                           refresh_expires_ms=new_expiry)
    vendor[0].finish(0)
    assert handle.wait(timeout=10)
    return done[0]


def live_token(paths):
    return (paths.claude_dir / ".credentials.json").read_text()


def day_month(ms):
    when = datetime.datetime.fromtimestamp(ms / 1000)
    return f"{when.day} {when.strftime('%b')}"


def test_renewing_a_parked_account_puts_you_back_on_the_one_you_were_on(
        paths, vendor):
    work_live_admin_parked(paths, admin_expires_ms=healthy_ms(2))
    renewed_until = healthy_ms(30)

    result = sign_in(paths, vendor, "Admin", new_expiry=renewed_until)

    assert result.ok, result.error
    assert state.read_active(paths, "claude") == "Work"
    assert "tok-Work" in live_token(paths)
    saved = paths.credentials("claude", "Admin").read_text()
    assert "tok-Admin-renewed" in saved
    assert result.summary == (f"Admin renewed until {day_month(renewed_until)}."
                              " You're still on Work.")
    assert result.offer is not None
    assert (result.offer.action, result.offer.provider,
            result.offer.account, result.offer.label) == (
        "switch", "claude", "Admin", "Use Admin")


def test_the_work_login_comes_back_byte_for_byte(paths, vendor):
    """The switch back is the ordinary switch: Work's login is the one
    that was set aside, not a copy of anything."""
    work_live_admin_parked(paths, admin_expires_ms=healthy_ms(2))
    before = live_token(paths)

    sign_in(paths, vendor, "Admin", new_expiry=healthy_ms(30))

    assert live_token(paths) == before


def test_signing_in_a_lapsed_account_leaves_you_on_it(paths, vendor):
    """Signing in a lapsed account is how you get to use it: as today."""
    work_live_admin_parked(paths, admin_expires_ms=healthy_ms(-1))

    result = sign_in(paths, vendor, "Admin", new_expiry=healthy_ms(30))

    assert result.ok, result.error
    assert state.read_active(paths, "claude") == "Admin"
    assert "tok-Admin-renewed" in live_token(paths)
    assert result.offer is None


def test_renewing_the_account_in_use_moves_nothing(paths, vendor):
    make_profile(paths, "claude", "Work", email="work@example.test",
                 active=True, refresh_expires_ms=healthy_ms(2))
    make_profile(paths, "claude", "Admin", email="admin@example.test")
    make_claude_json(paths, email="work@example.test")
    make_live_claude_login(paths, access_token="tok-Work",
                           refresh_expires_ms=healthy_ms(2))

    result = sign_in(paths, vendor, "Work", new_expiry=healthy_ms(30))

    assert result.ok, result.error
    assert state.read_active(paths, "claude") == "Work"
    assert result.offer is None


def test_if_the_switch_back_fails_the_renewal_still_counts(
        paths, vendor, monkeypatch):
    """The new login is saved before anything else moves. A switch back
    that is refused leaves you on Admin, and says so."""
    from shambles import switcher
    from shambles.errors import SwitchFailedError

    work_live_admin_parked(paths, admin_expires_ms=healthy_ms(2))
    real = switcher.switch
    calls = []

    def second_refused(*args, **kwargs):
        calls.append(args[2])
        if len(calls) > 1:
            raise SwitchFailedError("refused for the test")
        return real(*args, **kwargs)

    monkeypatch.setattr(switcher, "switch", second_refused)

    result = sign_in(paths, vendor, "Admin", new_expiry=healthy_ms(30))

    assert result.ok
    assert calls == ["Admin", "Work"]
    assert state.read_active(paths, "claude") == "Admin"
    assert "tok-Admin-renewed" in paths.credentials("claude", "Admin").read_text()
    assert "You're on Admin now" in result.summary
    assert result.offer is None


def test_an_offer_reaches_the_wire(paths):
    from shambles.app.service import ActionOffer, ActionResult
    result = ActionResult(True, "login", "Done.",
                          offer=ActionOffer("switch", "claude", "Admin",
                                            "Use Admin"))
    assert result.to_dict()["offer"] == {
        "action": "switch", "provider": "claude", "account": "Admin",
        "label": "Use Admin"}


def test_no_offer_is_null_on_the_wire():
    from shambles.app.service import ActionResult
    assert ActionResult(True, "login").to_dict()["offer"] is None
