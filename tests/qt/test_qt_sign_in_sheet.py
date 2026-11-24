"""The sign-in sheet's new parts, driven through the bridge (S1, S2, D7).

S1: a Claude sign-in takes the code its browser page shows when the browser
cannot reach this machine. The code is a credential: the sheet and the
messages never hold it, only whether it was sent and why it was refused.

S2: a Codex sign-in can run as "Another device", which shows a one-time code
and its link with a countdown. Choosing it while the browser sign-in runs
cancels that one and starts the device one; the cancel in between is not
reported as the user's.
"""

import pytest

pytest.importorskip("PySide6.QtCore", exc_type=ImportError,
                    reason="PySide6 is not installed or cannot load")

from qt_fakes import Clipboard, FakeService, codex_pair, failure  # noqa: E402
from qt_support import qt_app  # noqa: E402,F401
from shambles.app.qt import bridge as bridge_mod  # noqa: E402
from shambles.app.service import (ActionError, ActionResult,  # noqa: E402
                                  DeviceSignIn)

NOW = 1_800_000_000_000
CODE = "SECRETcode-x9#STATE-marker"
LINK = "https://auth.openai.com/codex/device"


class Clock:
    def __init__(self):
        self.now = NOW

    def __call__(self):
        return self.now


@pytest.fixture
def make(qt_app):
    def _make(snapshot=None):
        service = FakeService(snapshot or codex_pair())
        clipboard = Clipboard()
        clock = Clock()
        made = bridge_mod.Bridge(service, clipboard=clipboard,
                                 runner=lambda work: work(), clock_ms=clock)
        made.start()
        return made, service, clipboard, clock

    return _make


def _cancelled():
    return failure("login", "login_cancelled", "Sign-in cancelled.",
                   "You are back on 'Main'. Nothing was lost.")


# -- S1: the code from the browser page --------------------------------------


def test_a_claude_sign_in_draws_the_code_field(make):
    ui, service, _, _ = make()
    ui.openAdd("claude")
    ui.submitAdd("claude", "Spare")

    assert service.named("start_add") == [("start_add", "claude", "Spare")]
    assert ui.sheet["acceptsCode"] is True
    assert ui.sheet["methods"] == []


def test_a_codex_browser_sign_in_draws_no_code_field(make):
    ui, _, _, _ = make()
    ui.signIn("codex", "Spare")
    assert ui.sheet["acceptsCode"] is False


def test_a_pasted_code_goes_to_the_sign_in_and_never_into_the_window(make):
    ui, service, clipboard, _ = make()
    ui.openAdd("claude")
    ui.submitAdd("claude", "Spare")
    shown = []
    ui.sheetChanged.connect(lambda: shown.append(repr(ui.sheet)))

    ui.submitCode(f"  {CODE}\n")

    assert service.handles[-1].codes == [f"  {CODE}\n"]
    assert ui.sheet["codeSent"] is True
    assert ui.sheet["codeError"] == ""
    seen = " ".join(shown) + repr(ui.sheet) + repr(ui.toast)
    assert "SECRET" not in seen and "marker" not in seen
    assert clipboard.text is None


def test_a_refused_code_says_why_and_can_be_pasted_again(make):
    ui, service, _, _ = make()
    ui.openAdd("claude")
    ui.submitAdd("claude", "Spare")
    handle = service.handles[-1]
    handle.answer = ActionResult(False, "send_code", error=ActionError(
        "code_invalid", "That is only part of the code. Copy all of it from "
                        "the browser page."))

    ui.submitCode(CODE.split("#")[0])

    assert ui.sheet["codeError"].startswith("That is only part of the code")
    assert ui.sheet["codeSent"] is False
    assert "SECRET" not in repr(ui.sheet)

    handle.answer = None
    ui.submitCode(CODE)
    assert ui.sheet["codeSent"] is True
    assert len(handle.codes) == 2


def test_a_code_is_sent_once(make):
    ui, service, _, _ = make()
    ui.openAdd("claude")
    ui.submitAdd("claude", "Spare")
    ui.submitCode(CODE)
    ui.submitCode(CODE)
    assert len(service.handles[-1].codes) == 1


def test_no_code_is_sent_where_none_is_taken_or_nothing_runs(make):
    ui, service, _, _ = make()
    ui.submitCode(CODE)                     # no sign-in at all
    ui.signIn("codex", "Spare")
    ui.submitCode(CODE)                     # Codex takes none
    assert service.handles[-1].codes == []


# -- S2: a code for another device -------------------------------------------


def test_codex_offers_the_choice_and_starts_in_this_browser(make):
    ui, service, _, _ = make()
    ui.signIn("codex", "Spare")

    assert [m["id"] for m in ui.sheet["methods"]] == ["browser", "device"]
    assert ui.sheet["method"] == "browser"
    assert service.devices == [False]


def test_choosing_another_device_restarts_the_sign_in_quietly(make):
    ui, service, _, _ = make()
    ui.signIn("codex", "Spare")
    first = service.handles[-1]

    ui.chooseMethod("device")

    assert first.cancelled
    assert ui.sheet["method"] == "device"
    assert ui.sheet["restarting"] is True

    service.settle(_cancelled())

    # Not a cancel the user asked for: no message, the sheet stays.
    assert ui.toast["text"] == ""
    assert service.named("start_login")[-1] == ("start_login", "codex",
                                                "Spare")
    assert service.devices == [False, True]
    assert ui.sheet["kind"] == "login"
    assert ui.sheet["method"] == "device"
    assert ui.sheet["restarting"] is False


def test_an_add_restarts_as_a_sign_in_to_the_account_it_made(make):
    ui, service, _, _ = make()
    ui.openAdd("codex")
    ui.submitAdd("codex", "Third")

    ui.chooseMethod("device")
    service.settle(_cancelled())

    assert service.named("start_add") == [("start_add", "codex", "Third")]
    assert service.named("start_login") == [("start_login", "codex",
                                             "Third")]
    assert service.devices == [False, True]


def test_cancel_during_a_restart_is_a_cancel(make):
    ui, service, _, _ = make()
    ui.signIn("codex", "Spare")
    ui.chooseMethod("device")

    ui.cancelLogin()
    service.settle(_cancelled())

    assert ui.sheet == {}
    assert len(service.named("start_login")) == 1
    assert "cancelled" in ui.toast["text"].lower()


def test_a_sign_in_that_ends_otherwise_mid_restart_is_reported(make):
    ui, service, _, _ = make()
    ui.signIn("codex", "Spare")
    ui.chooseMethod("device")

    service.settle(ActionResult(True, "login", "Logged in to Spare.",
                                snapshot=service.snap))

    assert ui.sheet == {}
    assert len(service.named("start_login")) == 1


def test_the_same_method_or_no_choice_does_nothing(make):
    ui, service, _, _ = make()
    ui.signIn("codex", "Spare")
    ui.chooseMethod("browser")
    ui.chooseMethod("carrier pigeon")
    assert not service.handles[-1].cancelled

    service.settle(_cancelled())
    ui.openAdd("claude")
    ui.submitAdd("claude", "Spare")
    ui.chooseMethod("device")
    assert not service.handles[-1].cancelled


def _device_sheet(make):
    ui, service, clipboard, clock = make()
    ui.signIn("codex", "Spare")
    ui.chooseMethod("device")
    service.settle(_cancelled())
    service.device_code(DeviceSignIn("CODE-12345", LINK,
                                     NOW + 15 * 60_000))
    return ui, service, clipboard, clock


def test_the_code_and_link_show_with_a_countdown(make):
    ui, _, _, _ = _device_sheet(make)

    assert ui.sheet["device"] == {"code": "CODE-12345", "url": LINK,
                                  "expiresAtMs": NOW + 15 * 60_000}
    assert ui.sheet["expiresIn"] == "expires in 15:00"
    assert ui._countdown.isActive()


def test_the_countdown_moves_the_sheet_and_never_the_rows(make):
    ui, _, _, clock = _device_sheet(make)
    views, sheets = [], []
    ui.viewChanged.connect(lambda: views.append(1))
    ui.sheetChanged.connect(lambda: sheets.append(1))

    clock.now += 28_000
    ui.countDown()

    assert ui.sheet["expiresIn"] == "expires in 14:32"
    assert sheets == [1]
    assert views == []


def test_the_countdown_stops_at_expiry(make):
    ui, _, _, clock = _device_sheet(make)
    clock.now += 15 * 60_000
    ui.countDown()
    assert ui.sheet["expiresIn"] == "expired"
    assert not ui._countdown.isActive()


def test_the_countdown_stops_when_the_sheet_closes(make):
    ui, service, _, _ = _device_sheet(make)
    service.settle(ActionResult(True, "login", "Logged in to Spare.",
                                snapshot=service.snap))
    assert ui.sheet == {}
    assert not ui._countdown.isActive()


def test_copy_code_and_copy_link(make):
    ui, _, clipboard, _ = _device_sheet(make)

    ui.copyCode()
    assert clipboard.text == "CODE-12345"
    assert ui.sheet["codeCopied"] is True

    ui.copyUrl()
    assert clipboard.text == LINK


def test_a_device_code_for_a_browser_sign_in_is_ignored(make):
    ui, service, _, _ = make()
    ui.signIn("codex", "Spare")
    service.device_code(DeviceSignIn("CODE-12345", LINK, NOW + 900_000))
    assert ui.sheet["device"]["code"] == ""
    assert not ui._countdown.isActive()


# -- after a device sign-in fails ----------------------------------------------


def test_device_codes_off_offers_the_browser_and_starts_it(make):
    ui, service, _, _ = _device_sheet(make)

    service.settle(failure(
        "login", "device_sign_in_off",
        'Codex said: "device code login is not enabled for this Codex '
        'server. Use the browser login or verify the server URL."',
        "You are back on 'Main'. Nothing was lost. Then sign in to 'Spare' "
        "again."))

    assert ui.sheet["kind"] == "result"
    assert ui.sheet["retryLabel"] == "Use this browser"
    ui.retry()
    assert service.named("start_login")[-1] == ("start_login", "codex",
                                                "Spare")
    assert service.devices[-1] is False
    assert ui.sheet["method"] == "browser"


def test_try_again_after_an_expired_code_asks_for_a_new_code(make):
    ui, service, _, _ = _device_sheet(make)

    service.settle(failure(
        "login", "login_failed", "The code expired before it was entered.",
        "You are back on 'Main'. Nothing was lost. Sign in to 'Spare' again "
        "for a new code."))

    assert ui.sheet["retryLabel"] == "Try again"
    ui.retry()
    assert service.devices[-1] is True
    assert ui.sheet["method"] == "device"


def test_try_again_after_a_browser_sign_in_stays_in_the_browser(make):
    ui, service, _, _ = make()
    ui.signIn("codex", "Spare")

    service.settle(failure("login", "login_failed",
                           "The vendor's sign-in did not finish.",
                           "You are back on 'Main'. Nothing was lost."))
    ui.retry()

    assert service.devices == [False, False]
