"""The window's flows, driven through the object the QML talks to.

No QML is loaded here. A slot is called the way a click would call it, and
the assertions are on what the service was asked to do and on the state the
QML would draw. The credential-safety behaviours come first, because they
are the ones a redesign is most likely to lose.
"""

import threading

import pytest

pytest.importorskip("PySide6.QtCore", exc_type=ImportError,
                    reason="PySide6 is not installed or cannot load")

from qt_fakes import (Clipboard, FakeService, account, due, failure,  # noqa: E402
                      group, saved_elsewhere, unsaved)
from qt_support import pump, qt_app  # noqa: E402,F401
from shambles.app.qt import bridge as bridge_mod  # noqa: E402
from shambles.app.service import ActionResult  # noqa: E402
from shambles.app.snapshot import Snapshot  # noqa: E402


@pytest.fixture
def make(qt_app):
    """A bridge on a fake service. Background work runs inline, so a flow
    reads top to bottom; the tests about the worker thread pass
    ``runner=None`` to get the real one."""
    def _make(service=None, **kw):
        service = service or FakeService()
        clipboard = Clipboard()
        kw.setdefault("runner", lambda work: work())
        made = bridge_mod.Bridge(service, clipboard=clipboard, **kw)
        made.start()
        return made, service, clipboard

    return _make


# -- the live login cannot be lost by a misclick --------------------------------


def test_the_live_account_cannot_be_removed_even_if_asked(make):
    ui, service, _ = make()

    ui.askRemove("claude", "Work")

    assert ui.sheet == {}
    assert service.named("remove") == []


def test_removing_asks_first_and_cancel_removes_nothing(make):
    ui, service, _ = make()

    ui.askRemove("claude", "Personal")
    assert ui.sheet["kind"] == "confirm" and ui.sheet["action"] == "remove"
    ui.dismiss()

    assert ui.sheet == {}
    assert service.named("remove") == []


def test_confirming_a_removal_removes_exactly_that_account(make):
    ui, service, _ = make()

    ui.askRemove("claude", "Personal")
    ui.confirm()

    assert service.named("remove") == [("remove", "claude", "Personal")]
    assert ui.sheet == {}
    assert "Removed Personal" in ui.toast["text"]


def test_a_second_confirm_does_nothing(make):
    """Enter held down must not act twice."""
    ui, service, _ = make()
    ui.askRemove("claude", "Personal")

    ui.confirm()
    ui.confirm()

    assert len(service.named("remove")) == 1


def test_nothing_switches_while_an_unsaved_login_is_live(make):
    """Switching would replace that login with no copy kept."""
    ui, service, _ = make(FakeService(unsaved()))

    ui.switchTo("claude", "Personal")
    ui.pressKey("1")

    assert service.named("switch") == []
    assert ui.view["keys"] == {}


def test_switching_to_the_live_account_or_a_stranger_does_nothing(make):
    ui, service, _ = make()

    ui.switchTo("claude", "Work")
    ui.switchTo("claude", "Nobody")
    ui.switchTo("claude", "Old")

    assert service.named("switch") == []


# -- switching --------------------------------------------------------------------


def test_switching_goes_through_the_service_and_says_what_to_do_next(make):
    ui, service, _ = make()
    seen = []
    ui.confirmed.connect(seen.append)

    ui.switchTo("claude", "Personal")

    assert service.named("switch") == [("switch", "claude", "Personal")]
    assert seen == ["claude/Personal"]
    assert ui.toast["text"] == "Switched to Personal."


def test_a_refused_switch_says_why_and_confirms_nothing(make):
    ui, service, _ = make()
    service.fail["switch"] = failure(
        "switch", "companion_unreadable", "The vendor config is unreadable.",
        "Repair it and retry.")
    seen = []
    ui.confirmed.connect(seen.append)

    ui.switchTo("claude", "Personal")

    assert seen == []
    assert ui.toast["tone"] == "bad"
    assert ui.toast["text"] == \
        "The vendor config is unreadable. Repair it and retry."


def test_a_number_key_switches_and_is_ignored_while_a_sheet_is_open(make):
    """Work is live and first, so Personal, second, is Ctrl+2."""
    ui, service, _ = make()

    ui.openAdd("")
    ui.pressKey("2")
    assert service.named("switch") == []

    ui.dismiss()
    ui.pressKey("1")
    assert service.named("switch") == [], "the live account's key does nothing"
    ui.pressKey("2")
    assert service.named("switch") == [("switch", "claude", "Personal")]


def test_a_number_key_on_a_signed_out_account_starts_its_sign_in(make):
    ui, service, _ = make()

    ui.pressKey("3")

    assert service.named("start_login") == [("start_login", "claude", "Old")]
    assert ui.sheet["kind"] == "login"


# -- signing in: every ending puts the user somewhere they understand -----------


def test_sign_in_runs_the_vendor_and_shows_who_to_sign_in_as(make):
    ui, service, _ = make()

    ui.signIn("claude", "Old")

    assert service.named("start_login") == [("start_login", "claude", "Old")]
    assert ui.sheet["kind"] == "login"
    assert "old@example.test" in ui.sheet["who"]
    assert ui.sheet["cancelNote"] == \
        "Cancel puts you back on Work. Nothing is lost."


def test_only_one_sign_in_runs_at_a_time(make):
    ui, service, _ = make()
    ui.signIn("claude", "Old")

    ui.signIn("claude", "Old")
    ui.openAdd("")
    ui.switchTo("claude", "Personal")

    assert len(service.named("start_login")) == 1
    assert service.named("switch") == []
    assert ui.sheet["kind"] == "login"


def test_the_link_appears_once_printed_and_opening_always_copies(make):
    ui, service, clipboard = make()
    ui.signIn("claude", "Old")
    on_line, _ = service.login

    on_line("[vendor output hidden]")
    assert ui.sheet["url"] == ""
    on_line("https://claude.ai/oauth/authorize?client_id=x")
    assert ui.sheet["url"] == "https://claude.ai/oauth/authorize?client_id=x"

    ui.openUrl()

    assert clipboard.text == ui.sheet["url"]
    assert service.named("open") == [("open", ui.sheet["url"])]
    assert ui.sheet["copied"] is True


def test_when_no_browser_opens_the_window_says_the_link_was_copied(make):
    ui, service, clipboard = make()
    service.opens = False
    ui.signIn("claude", "Old")
    service.login[0]("https://claude.ai/oauth/authorize?client_id=x")

    ui.openUrl()

    assert clipboard.text is not None
    assert "on your clipboard" in ui.toast["text"]


def test_a_renewed_login_closes_the_sheet_and_confirms_the_account(make):
    ui, service, _ = make()
    seen = []
    ui.confirmed.connect(seen.append)
    ui.signIn("claude", "Old")

    service.settle(ActionResult(True, "login", "Logged in to Old.",
                                snapshot=service.snap))

    assert ui.sheet == {}
    assert seen == ["claude/Old"]
    assert ui.toast["text"] == "Old is signed in and in use."


def test_a_login_for_the_wrong_account_is_explained_and_can_be_retried(make):
    """Nothing was saved over the profile, and the window says so."""
    ui, service, _ = make()
    ui.signIn("claude", "Old")

    service.settle(failure(
        "login", "login_other_account",
        "Your browser signed in as work@example.test, but 'Old' is "
        "old@example.test. Nothing was saved over 'Old'.",
        "You are on 'Work', which that login belongs to."))

    assert ui.sheet["kind"] == "result"
    assert ui.sheet["title"] == "That was a different account"
    assert "Nothing was saved over 'Old'" in ui.sheet["message"]

    ui.retry()

    assert len(service.named("start_login")) == 2
    assert ui.sheet["kind"] == "login"


def test_cancelling_stops_the_vendor_and_says_where_the_user_is(make):
    ui, service, _ = make()
    ui.signIn("claude", "Old")

    ui.cancelLogin()
    assert service.handles[0].cancelled
    assert ui.sheet["cancelling"] is True, "the sheet closed before rollback"

    service.settle(failure("login", "login_cancelled", "Sign-in cancelled.",
                           "You are back on 'Work'. Nothing was lost."))

    assert ui.sheet == {}
    assert ui.toast["text"] == \
        "Sign-in cancelled. You are back on 'Work'. Nothing was lost."


def test_closing_the_sheet_mid_sign_in_cancels_rather_than_abandons(make):
    """Escape must not leave a vendor process running behind a closed sheet."""
    ui, service, _ = make()
    ui.signIn("claude", "Old")

    ui.dismiss()

    assert service.handles[0].cancelled
    assert ui.sheet["kind"] == "login"


def test_closing_the_window_mid_sign_in_cancels_and_waits_for_rollback(make):
    ui, service, _ = make()
    ui.signIn("claude", "Old")

    ui.shutdown()

    assert service.handles[0].cancelled
    assert service.handles[0].waited is not None, \
        "exited without waiting for the user to be put back"


def test_vendor_output_from_another_thread_reaches_the_sheet(make, pump):
    """The service calls back off the GUI thread; nothing may be touched there."""
    ui, service, _ = make()
    ui.signIn("claude", "Old")
    on_line, _ = service.login

    worker = threading.Thread(
        target=on_line, args=("https://claude.ai/oauth/authorize?x=1",))
    worker.start()
    worker.join()

    assert ui.sheet["url"] == "", "state changed on the worker thread"
    assert pump(lambda: ui.sheet.get("url") != "")


def test_a_sign_in_that_cannot_start_reports_and_leaves_nothing_running(make):
    ui, service, _ = make()
    service.fail["start_login"] = failure(
        "login", "login_unavailable", "claude is not installed.",
        "Install it, then try again.")

    ui.signIn("claude", "Old")

    assert ui.sheet["kind"] == "result" and ui.sheet["retry"] is False
    ui.dismiss()
    ui.switchTo("claude", "Personal")
    assert service.named("switch"), "a failed start left the window locked"


# -- adding -----------------------------------------------------------------------


def test_adding_needs_a_name_before_anything_moves(make):
    ui, service, _ = make()
    ui.openAdd("claude")

    ui.submitAdd("claude", "   ")

    assert service.named("start_add") == []
    assert ui.sheet["kind"] == "add" and ui.sheet["error"]


def test_a_name_the_core_refuses_goes_back_to_the_form_with_it_kept(make):
    ui, service, _ = make()
    service.fail["start_add"] = failure(
        "add", "operation_refused", "A profile named 'Work' already exists.")
    ui.openAdd("claude")

    ui.submitAdd("claude", "Work")

    assert ui.sheet["kind"] == "add"
    assert ui.sheet["error"] == "A profile named 'Work' already exists."
    assert ui.sheet["name"] == "Work"


def test_adding_an_account_already_saved_says_which_one(make):
    ui, service, _ = make()
    ui.openAdd("claude")
    ui.submitAdd("claude", "Second")

    service.settle(failure(
        "add", "login_duplicate",
        "You signed in as work@example.test, which is already saved as "
        "'Work'. Nothing was saved under 'Second'.", "You are on 'Work' now."))

    assert ui.sheet["title"] == "That account is already saved"
    assert "'Work'" in ui.sheet["message"]


def test_a_provider_without_its_cli_cannot_be_added_to(make):
    snapshot = Snapshot(1, [group(account("Work", active=True),
                                  can_sign_in=False)])
    ui, service, _ = make(FakeService(snapshot))

    ui.submitAdd("claude", "Second")

    assert service.named("start_add") == []


# -- saving, renaming, ejecting, theme, startup ------------------------------------


def test_a_refused_save_is_said_beside_the_field(make):
    ui, service, _ = make(FakeService(unsaved()))
    service.fail["save_current"] = failure(
        "save_current", "operation_refused", "That name is already in use.")

    ui.saveCurrent("claude", "Work")

    assert ui.view["groups"][0]["save"]["error"] == \
        "That name is already in use."


def test_saving_the_current_login_passes_the_trimmed_name(make):
    ui, service, _ = make(FakeService(unsaved()))

    ui.saveCurrent("claude", "  New Hire ")

    assert service.named("save_current") == \
        [("save_current", "claude", "New Hire")]
    assert "Saved New Hire" in ui.toast["text"]


def test_a_refused_rename_keeps_the_sheet_open_with_the_reason(make):
    ui, service, _ = make()
    service.fail["rename"] = failure(
        "rename", "operation_refused", "Names cannot contain '/'.")
    ui.askRename("claude", "Personal")

    ui.submitRename("a/b")

    assert ui.sheet["kind"] == "rename"
    assert ui.sheet["error"] == "Names cannot contain '/'."


def test_renaming_to_the_same_name_is_not_a_rename(make):
    ui, service, _ = make()
    ui.askRename("claude", "Personal")

    ui.submitRename(" Personal ")

    assert service.named("rename") == [] and ui.sheet == {}


def test_eject_says_what_it_will_do_before_and_what_it_did_after(make):
    ui, service, _ = make()

    ui.askEject()
    assert ui.sheet["kind"] == "confirm"
    assert "Nothing is deleted" in ui.sheet["message"]
    assert "Logins for Personal stay on disk." in ui.sheet["message"]
    assert service.named("eject") == []

    ui.confirm()

    assert len(service.named("eject")) == 1
    assert ui.sheet["kind"] == "notice"
    assert ui.sheet["messages"] == ["Shambles has handed back 2 accounts."]


def test_the_theme_follows_the_choice_then_the_system(make):
    ui, service, _ = make(system_dark=lambda: True)
    assert ui.dark is True, "ignored a dark desktop"

    ui.setTheme("light")
    assert (ui.dark, service.theme) == (False, "light")

    unknown, _, _ = make(system_dark=lambda: None)
    assert unknown.dark is False, "an unknown scheme must read as light"


def test_startup_migrations_are_said_once_over_the_accounts(make):
    from types import SimpleNamespace
    service = FakeService()
    service.migrations = (SimpleNamespace(
        code="store_moved", ok=True, message="Your profiles moved."),)

    ui, _, _ = make(service)

    assert ui.sheet["kind"] == "notice"
    assert ui.sheet["messages"] == ["Your profiles moved."]
    assert ui.view["count"] == 3, "the accounts were not read behind it"


def test_a_refresh_that_raises_does_not_take_the_window_down(make):
    ui, service, _ = make()

    def boom():
        raise RuntimeError("store exploded")

    service.refresh = boom
    ui.refresh()

    assert ui.toast["tone"] == "bad"
    assert ui.view["count"] == 3, "the last good view was thrown away"



# -- settling a login that is saved under another name ----------------------------


def test_settling_switches_to_the_account_the_notice_names(make):
    ui, service, _ = make(FakeService(saved_elsewhere()))
    seen = []
    ui.confirmed.connect(seen.append)

    ui.settle("claude")

    assert service.named("switch") == [("switch", "claude", "Home")]
    assert seen == ["claude/Home"]


def test_settling_does_nothing_where_there_is_nothing_to_settle(make):
    ui, service, _ = make()

    ui.settle("claude")
    ui.settle("nobody")

    assert service.named("switch") == []


def test_while_unsettled_only_the_named_account_can_be_switched_to(make):
    ui, service, _ = make(FakeService(saved_elsewhere()))

    ui.switchTo("claude", "Third")
    ui.pressKey("1")

    assert all(call[2] == "Home" for call in service.named("switch")), \
        "switched somewhere the core would refuse, or worse"


def test_settling_on_the_real_service_files_the_login_and_loses_nothing(
        qt_app, paths):
    """Signed in again in the browser as Home, which is saved, while Work is
    still marked. Nothing proves the login is Home's, so the window offers no
    Save and holds every other Switch; its one button switches to Home,
    which files the fresh login there and keeps Home's old one beside it."""
    import json

    from helpers import (credentials, healthy_ms, make_claude_json,
                         make_profile, write_json)
    from shambles import providers, state
    from shambles.app.service import ShamblesService

    def login(access, refresh, days):
        # Different deadlines on purpose: a login whose deadline matches a
        # profile's to the second continues that profile's login, which is
        # proof, and proof settles itself on refresh. This test is about the
        # case nothing proves.
        blob = credentials(refresh_expires_ms=healthy_ms(days),
                           access_token=access)
        blob["claudeAiOauth"]["refreshToken"] = refresh
        return blob

    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Home", email="h@example.test")
    make_profile(paths, "claude", "Third", email="t@example.test")
    write_json(paths.credentials("claude", "Home"), login("a-old", "r-old", 12))
    old_home = paths.credentials("claude", "Home").read_bytes()
    work = paths.credentials("claude", "Work").read_bytes()
    make_claude_json(paths, email="h@example.test")
    write_json(paths.claude_dir / ".credentials.json", login("a-new", "r-new", 29))
    fresh = (paths.claude_dir / ".credentials.json").read_bytes()

    service = ShamblesService(paths=paths,
                              providers=[providers.load("claude", env={})],
                              platform="linux")
    ui = bridge_mod.Bridge(service, clipboard=Clipboard(),
                           runner=lambda work: work())
    ui.start()
    shown = ui.view["groups"][0]

    assert shown["save"] is None, "offered to save a login that is Home's"
    assert shown["settle"]["account"] == "Home"
    others = {a["name"]: a for a in shown["others"]}
    assert others["Third"]["actionEnabled"] is False

    ui.switchTo("claude", "Third")
    assert (paths.claude_dir / ".credentials.json").read_bytes() == fresh

    ui.settle("claude")

    assert state.read_active(paths, "claude") == "Home"
    assert paths.credentials("claude", "Home").read_bytes() == fresh
    assert (paths.profile_dir("claude", "Home")
            / "credentials.json.previous").read_bytes() == old_home
    assert paths.credentials("claude", "Work").read_bytes() == work
    assert ui.view["groups"][0]["settle"] is None
    assert ui.view["groups"][0]["live"]["name"] == "Home"
    assert json.loads(fresh) == json.loads(
        (paths.claude_dir / ".credentials.json").read_bytes())



# -- R10: a switch runs off the window's thread ------------------------------------


def test_a_switch_does_not_hold_the_window_while_it_waits(make, pump):
    """A switch can wait up to 15 s on Claude Code's refresh lock. The Tk
    window freezes for that long; this one must keep drawing."""
    import threading

    service = FakeService()
    service.hold = threading.Event()
    ui, _, _ = make(service, runner=None)
    seen = []
    ui.confirmed.connect(seen.append)

    ui.switchTo("claude", "Personal")

    assert ui.busy is True, "the click did not return before the switch did"
    assert pump(lambda: "renewing" in ui.busyText), \
        "never said why nothing has happened yet"
    # D10: one line on show; the reason and the time limit behind its i.
    assert ui.busyText == "Waiting for Claude Code to finish renewing"
    assert "renewing its login" in ui.busyDetail
    assert "15 s" in ui.busyDetail
    assert seen == []

    service.hold.set()
    assert pump(lambda: not ui.busy, timeout=5)
    assert seen == ["claude/Personal"]
    assert ui.busyText == "" and ui.busyDetail == ""
    assert "Switched to Personal" in ui.toast["text"]


def test_nothing_else_moves_while_a_switch_is_running(make, pump):
    import threading

    service = FakeService()
    service.hold = threading.Event()
    ui, _, _ = make(service, runner=None)

    ui.switchTo("claude", "Personal")
    ui.switchTo("claude", "Personal")
    ui.pressKey("1")
    ui.signIn("claude", "Old")
    ui.askRemove("claude", "Personal")
    ui.openAdd("")

    assert ui.sheet == {}
    assert service.named("start_login") == []
    service.hold.set()
    assert pump(lambda: not ui.busy, timeout=5)
    assert len(service.named("switch")) == 1


def test_closing_mid_switch_waits_for_it_to_finish(make, pump):
    """An interrupted switch is the one thing that could lose a login. The
    window waits for it rather than exiting under it."""
    import threading

    service = FakeService()
    service.hold = threading.Event()
    ui, _, _ = make(service, runner=None)
    ui.switchTo("claude", "Personal")
    assert ui.busy

    threading.Timer(0.3, service.hold.set).start()
    ui.shutdown()

    assert service.named("switch") == [("switch", "claude", "Personal")]


def test_a_close_request_mid_switch_is_held_until_it_finishes(make, pump):
    import threading

    service = FakeService()
    service.hold = threading.Event()
    ui, _, _ = make(service, runner=None)
    quit_asked = []
    ui.quitRequested.connect(lambda: quit_asked.append(True))

    assert ui.closeRequested() is True, "an idle window must close at once"
    ui.switchTo("claude", "Personal")
    assert ui.closeRequested() is False
    assert "closes when" in ui.busyText

    service.hold.set()
    assert pump(lambda: quit_asked == [True], timeout=5)


def test_settling_also_runs_off_the_windows_thread(make, pump):
    import threading

    service = FakeService(saved_elsewhere())
    service.hold = threading.Event()
    ui, _, _ = make(service, runner=None)

    ui.settle("claude")
    assert ui.busy
    service.hold.set()
    assert pump(lambda: not ui.busy, timeout=5)
    assert service.named("switch") == [("switch", "claude", "Home")]


# -- R11: a sign-in that is due, before the date -------------------------------------


def test_a_due_sign_in_can_be_started_from_its_notice_and_its_row(make):
    ui, service, _ = make(FakeService(due()))

    ui.signIn("claude", "Work")
    assert service.named("start_login") == [("start_login", "claude", "Work")]
    ui.cancelLogin()
    service.settle(failure("login", "login_cancelled", "Sign-in cancelled."))

    ui.signIn("claude", "Spare")
    assert service.named("start_login")[-1] == ("start_login", "claude", "Spare")


# -- D5: the window opens where it was left ----------------------------------------

LAPTOP = (0, 0, 1920, 1040)


def test_the_window_opens_where_it_was_left(make):
    service = FakeService()
    service.place = {"x": 300, "y": 200, "width": 640, "height": 500,
                     "maximized": True}

    ui, _, _ = make(service, screens=lambda: ([LAPTOP], LAPTOP))

    assert ui.place == service.place


def test_a_place_on_a_screen_that_has_gone_opens_in_the_centre(make):
    service = FakeService()
    service.place = {"x": 2400, "y": 200, "width": 640, "height": 500,
                     "maximized": False}

    ui, _, _ = make(service, screens=lambda: ([LAPTOP], LAPTOP))

    assert (ui.place["x"], ui.place["y"]) == (640, 270)


def test_where_the_window_is_left_is_handed_to_the_service(make):
    ui, service, _ = make()

    ui.rememberPlace(10, 20, 700, 600, False)

    assert service.named("set_window_place") == [
        ("set_window_place", 10, 20, 700, 600, False)]


def test_a_place_that_cannot_be_saved_says_nothing(make):
    """Moving a window is not worth an error message; the next run opens
    where the window manager puts it."""
    ui, service, _ = make()
    service.fail["set_window_place"] = failure(
        "set_window_place", "unwritable", "Could not save.")
    toast = dict(ui.toast)

    ui.rememberPlace(10, 20, 700, 600, True)

    assert ui.toast == toast


# -- D10: messages -------------------------------------------------------------------


def test_a_message_can_offer_one_next_step_and_it_runs_once(make):
    ui, _service, _ = make()
    ran = []

    ui._say("Admin renewed.", action=("Use Admin", lambda: ran.append(1)))
    assert ui.toast["actionLabel"] == "Use Admin"
    ui.toastAction()
    ui.toastAction()

    assert ran == [1]


def test_a_later_message_takes_the_earlier_ones_action_with_it(make):
    ui, _service, _ = make()
    ran = []
    ui._say("Admin renewed.", action=("Use Admin", lambda: ran.append(1)))

    ui._say("Switched to Personal.")
    ui.toastAction()

    assert ui.toast["actionLabel"] == "" and ran == []

# -- U1: the window keeps its own time --------------------------------------------


def test_a_countdown_and_a_reset_follow_the_clock_while_the_window_sits_open(
        make):
    """Nothing is re-read: the tick only redraws what the bridge already
    holds, at the time it is drawn."""
    from qt_fakes import with_usage

    now = [1_790_000_000_000]
    ui, service, _ = make(FakeService(with_usage(now[0])),
                          clock_ms=lambda: now[0])
    live = ui.view["groups"][0]["live"]["usage"][0]
    assert (live["state"], live["resetsIn"]) == ("current", "in 2h")
    reads = len(service.calls)

    now[0] += 2 * 3_600_000 + 60_000
    ui.tick()

    live = ui.view["groups"][0]["live"]["usage"][0]
    assert live["state"] == "reset"
    assert len(service.calls) == reads


def test_the_redraw_tick_runs_every_half_minute_once_started(make):
    ui, _service, _ = make()

    assert ui._clock.isActive()
    assert ui._clock.interval() == bridge_mod.REDRAW_MS == 30_000


def test_a_tick_that_changes_nothing_does_not_redraw(make):
    """Every viewChanged recreates every card in today's QML, closing an
    open menu and dropping focus. A timer nobody asked for must not."""
    from qt_fakes import with_usage

    now = [1_790_000_000_000]
    ui, _service, _ = make(FakeService(with_usage(now[0])),
                           clock_ms=lambda: now[0])
    redraws = []
    ui.viewChanged.connect(lambda: redraws.append(now[0]))

    now[0] += 10_000          # "in 2h" still reads "in 2h"
    ui.tick()
    assert redraws == []

    now[0] += 60_000          # now "in 1h 59m"
    ui.tick()
    assert len(redraws) == 1


# -- D4: a deadline line closed until tomorrow --------------------------------------

DAY_MS = 86_400_000


def due_soon():
    from shambles.app.snapshot import Account, Notice

    notice = Notice("sign_in_soon", "'Work' stops working soon.",
                    "Sign in to 'Work' again before then.", account="Work")
    work = Account(name="Work", email="work@example.test", active=True,
                   state="closing", status_label="soon", sign_in_due=True,
                   expires_at_ms=NOON + DAY_MS)
    return Snapshot(1, [group(work, account("Other"), notices=[notice])])


#: 2026-11-18, midday local time, so a day either side is another date.
NOON = int(__import__("datetime").datetime(2026, 11, 18, 12).timestamp()
           * 1000)


def test_closing_a_deadline_line_hides_it_for_the_rest_of_the_day(make):
    clock = [NOON]
    ui, service, _ = make(FakeService(due_soon()), clock_ms=lambda: clock[0])
    assert ui.view["groups"][0]["deadline"]["account"] == "Work"

    ui.hideDeadline("claude/Work")

    assert ui.view["groups"][0]["deadline"] is None
    assert service.named("hide_deadline") == [
        ("hide_deadline", "claude/Work", "2026-11-18")]
    clock[0] = NOON + DAY_MS // 2 + 3_600_000
    ui.tick()
    assert ui.view["groups"][0]["deadline"]["account"] == "Work", \
        "back the next morning"


def test_a_line_closed_earlier_today_stays_closed_in_a_new_window(make):
    service = FakeService(due_soon())
    service.hidden = {"claude/Work": "2026-11-18"}

    ui, _, _ = make(service, clock_ms=lambda: NOON)

    assert ui.view["groups"][0]["deadline"] is None


# -- D8: Ctrl held shows every number ----------------------------------------------


def test_holding_ctrl_is_said_once_per_change(make):
    ui, _, _ = make()
    seen = []
    ui.ctrlHeldChanged.connect(lambda: seen.append(ui.ctrlHeld))

    ui.set_ctrl_held(True)
    ui.set_ctrl_held(True)
    ui.set_ctrl_held(False)

    assert seen == [True, False]


# -- U2: the window keeps itself current ------------------------------------------


def test_coming_back_to_the_window_re_reads_files_only(make):
    """Focus is not an explicit action, so it must never reach the
    Keychain: refresh_files, not refresh."""
    from qt_fakes import with_usage

    now = [1_790_000_000_000]
    ui, service, _ = make(clock_ms=lambda: now[0])
    service.snap = with_usage(now[0])
    service.calls.clear()

    ui.windowFocused()          # the focus the window gets as it opens
    assert service.named("refresh_files") == []

    now[0] += bridge_mod.FOCUS_GAP_MS
    ui.windowFocused()

    assert service.named("refresh_files") == [("refresh_files",)]
    assert service.named("refresh") == []
    assert ui.view["groups"][0]["live"]["name"] == "Work"
    assert ui.view["groups"][0]["others"][0]["name"] == "Dev"


def test_a_file_written_by_the_vendor_is_picked_up_by_the_poll(make):
    ui, service, _ = make()
    service.calls.clear()

    ui.poll()
    assert service.named("refresh_files") == []

    service.signature = (("claude.json", 2, 10),)
    ui.poll()
    ui.poll()

    assert service.named("refresh_files") == [("refresh_files",)]


def test_the_timers_run_once_the_window_has_started(make):
    ui, _service, _ = make()

    assert ui._poll.isActive() and ui._poll.interval() == bridge_mod.POLL_MS
    assert ui._minute.isActive()
    assert ui._minute.interval() == bridge_mod.REREAD_MS == 60_000


def test_nothing_is_re_read_under_a_running_switch(make):
    import threading

    ui, service, _ = make(runner=None)
    service.hold = threading.Event()
    ui.switchTo("claude", "Personal")
    assert ui.busy
    service.calls = [c for c in service.calls if c[0] != "refresh_files"]

    ui.windowFocused()
    ui.reread()

    assert service.named("refresh_files") == []
    service.hold.set()
    ui.shutdown()


def test_nothing_is_re_read_under_a_running_sign_in(make):
    ui, service, _ = make()
    ui.signIn("claude", "Old")
    assert ui.sheet["kind"] == "login"
    service.calls.clear()

    ui.windowFocused()
    ui.reread()

    assert service.named("refresh_files") == []


def test_a_files_only_read_with_no_answer_leaves_the_window_as_it_was(make):
    """No snapshot means the service could not answer without the
    Keychain. The window keeps what it shows rather than blanking it."""
    ui, service, _ = make()
    before = ui.view
    service.fail["refresh_files"] = ActionResult(True, "refresh_files")

    ui.reread()

    assert ui.view == before


def test_a_re_read_that_changes_nothing_does_not_redraw(make):
    ui, _service, _ = make()
    redraws = []
    ui.viewChanged.connect(lambda: redraws.append(1))

    ui.reread()
    ui.poll()

    assert redraws == []


def test_the_header_says_when_the_window_last_read(make):
    now = [1_790_000_000_000]
    ui, _service, _ = make(clock_ms=lambda: now[0])
    assert ui.updatedText == "Updated just now"
    assert "Nothing goes online" in ui.updatedTip

    now[0] += 5 * 60_000
    ui.tick()
    assert ui.updatedText == "Updated 5m ago"

    ui.reread()
    assert ui.updatedText == "Updated just now"


def test_a_login_changed_outside_shambles_keeps_the_view_and_says_refresh(make):
    from shambles.app.service import ActionError

    ui, service, _ = make()
    before = ui.view
    service.fail["refresh_files"] = ActionResult(
        False, "refresh_files", error=ActionError(
            "changed_outside", "Claude Code's login changed outside Shambles."))

    ui.reread()
    ui.tick()

    assert ui.view == before
    assert ui.updatedText == "Changed outside Shambles · Refresh"
    assert "Refresh" in ui.updatedTip

    del service.fail["refresh_files"]
    ui.refresh()
    assert ui.updatedText == "Updated just now"


def test_a_login_changed_outside_is_not_asked_about_again_every_poll(make):
    from shambles.app.service import ActionError

    ui, service, _ = make()
    service.fail["refresh_files"] = ActionResult(
        False, "refresh_files", error=ActionError("changed_outside", "Changed."))
    service.signature = (("claude.json", 9, 9),)
    service.calls.clear()

    ui.poll()
    ui.poll()
    ui.poll()

    assert len(service.named("refresh_files")) == 1
