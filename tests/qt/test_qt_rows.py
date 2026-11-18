"""The rows, in the real QML: one button and one badge (D2, which fixes F3),
the deadline line (D4), a tool that is not installed (D6), Ctrl+N (D8),
and cards that survive the window being worked out again."""

import time

import pytest

pytest.importorskip("PySide6.QtQuick", exc_type=ImportError,
                    reason="PySide6 is not installed or cannot load")

from PySide6.QtCore import QPoint, Qt  # noqa: E402

from qt_fakes import FakeService, account, group, standard  # noqa: E402
from qt_support import pump, qt_app  # noqa: E402,F401
from shambles.app.snapshot import Account, Notice, Snapshot, Window  # noqa: E402
from test_qt_application import window  # noqa: E402,F401
from test_qt_frame import SMALL, find, inside, items, rect, sized  # noqa: E402

DAY_MS = 86_400_000


def now_ms():
    return int(time.time() * 1000)


def within(item, name):
    """The visible item called ``name`` inside ``item``."""
    todo = [item]
    while todo:
        here = todo.pop()
        if here.objectName() == name and here.isVisible():
            return here
        todo.extend(here.childItems())
    raise AssertionError(f"nothing called {name!r} in {item.objectName()!r}")


def click(root, item, pump):
    from PySide6.QtTest import QTest

    x, y, w, h = rect(item)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(x + w / 2), int(y + h / 2)))
    pump(timeout=0.1)


def due(name, *, days=2):
    return Account(name=name, email=f"{name.split()[0].lower()}@example.test",
                   plan="max_5x", state="closing", status_label="soon",
                   sign_in_due=True, expires_at_ms=now_ms() + days * DAY_MS)


def admin_due():
    """Ian's F3 state: a parked account due a sign-in, with a long name."""
    return Snapshot(1, [group(account("work", active=True),
                              due("Administrator account"),
                              account("client", state="closed",
                                      needs_login=True))])


# -- delegates survive a rebuild ------------------------------------------------------


def test_an_open_menu_and_its_focus_survive_the_window_being_worked_out_again(
        window, pump):
    """U1 redraws every 30 s and U2 re-reads every 60 s. Neither may close a
    menu someone has open or move their keyboard focus."""
    service = FakeService()
    engine, ui, _service, messages = window(service)
    root = engine.rootObjects()[0]
    card = find(root, "card claude/Personal")
    click(root, within(card, "more"), pump)
    rename = find(root, "menu rename")
    rename.forceActiveFocus()
    pump(timeout=0.05)
    assert root.activeFocusItem() == rename

    # A real change: Personal's usage moved, so the view is new.
    before = ui.view
    service.snap = Snapshot(1, [
        group(account("Work", active=True),
              Account(name="Personal", email="personal@example.test",
                      plan="max_5x", usage=[Window("session", 42)]),
              account("Old", state="closed", needs_login=True)),
        group(provider="codex", title="Codex")])
    ui.refresh()
    pump(timeout=0.1)
    root.grabWindow()

    assert ui.view != before
    assert find(root, "card claude/Personal") == card, "the card was made again"
    assert find(root, "menu rename") == rename, "the menu was made again"
    assert root.activeFocusItem() == rename
    assert messages == []


def test_a_row_that_moves_keeps_its_card(window, pump):
    service = FakeService()
    engine, ui, _service, _messages = window(service)
    root = engine.rootObjects()[0]
    old = find(root, "card claude/Old")

    service.snap = Snapshot(1, [group(account("Work", active=True),
                                      account("Aardvark"), account("Personal"),
                                      account("Old", state="closed",
                                              needs_login=True))])
    ui.refresh()
    pump(timeout=0.1)

    assert find(root, "card claude/Old") == old
    assert find(root, "card claude/Aardvark")


# -- D2 / F3: one button, one badge, the menu always in reach -------------------------


@pytest.mark.parametrize("size", [(520, 600), SMALL])
def test_a_row_due_a_sign_in_with_a_long_name_keeps_its_menu_on_the_card(
        window, pump, size):
    """F3: Sign in beside Switch pushed the row's menu off the card, and with
    it Rename and Remove."""
    engine, _ui, _service, messages = window(FakeService(admin_due()))
    root = engine.rootObjects()[0]
    sized(root, pump, *size)

    card = find(root, "card claude/Administrator account")
    listed = rect(card)
    for name in ("more", "action", "badge"):
        assert inside(rect(within(card, name)), listed), name
    assert within(card, "action").property("text") == "Switch"
    assert inside(listed, (0, 0) + size)
    assert messages == []


def test_the_due_badge_signs_in(window, pump):
    engine, _ui, service, _messages = window(FakeService(admin_due()))
    root = engine.rootObjects()[0]

    click(root, within(find(root, "card claude/Administrator account"),
                       "badge"), pump)

    assert service.named("start_login") == [
        ("start_login", "claude", "Administrator account")]


def test_rows_have_no_details_button_and_open_from_their_menu(window, pump):
    engine, ui, _service, _messages = window()
    root = engine.rootObjects()[0]
    card = find(root, "card claude/Personal")

    click(root, within(card, "more"), pump)
    click(root, find(root, "menu details"), pump)

    assert root.property("expandedId") == "claude/Personal"


# -- D4: the deadline line ------------------------------------------------------------


def deadline_soon():
    notice = Notice("sign_in_soon", "'Admin' stops working soon.",
                    "Sign in to 'Admin' again before then.", account="Admin")
    return Snapshot(1, [group(account("Work", active=True), due("Admin"),
                              notices=[notice])])


def test_a_deadline_is_one_line_with_sign_in_and_hides_until_tomorrow(
        window, pump):
    engine, ui, service, messages = window(FakeService(deadline_soon()))
    root = engine.rootObjects()[0]
    strip = find(root, "deadline")

    assert strip.height() == 40
    click(root, within(strip, "deadlineClose"), pump)

    assert not items(root, "deadline")
    assert service.named("hide_deadline")[0][1] == "claude/Admin"
    assert messages == []


# -- D6: a tool that is not installed ---------------------------------------------------


def test_a_tool_that_is_not_installed_is_one_line_with_no_card(window, pump):
    snap = Snapshot(1, [group(account("Work", active=True)),
                        group(provider="codex", title="Codex",
                              can_sign_in=False)])
    engine, ui, _service, messages = window(FakeService(snap))
    root = engine.rootObjects()[0]
    root.grabWindow()

    assert find(root, "missingInfo")
    assert "fills in by itself" in find(root, "missingInfo").property("tip")
    assert ui.view["groups"][1]["empty"] is None
    assert ui.view["groups"][1]["notices"] == []
    assert messages == []


# -- D8: Ctrl+N, never a bare digit -----------------------------------------------------


def test_ctrl_and_a_number_switches_and_a_bare_number_does_nothing(window,
                                                                    pump):
    from PySide6.QtTest import QTest

    engine, ui, service, _messages = window()
    root = engine.rootObjects()[0]
    root.requestActivate()
    pump(timeout=0.05)

    QTest.keyClick(root, Qt.Key_2)
    pump(timeout=0.1)
    assert service.named("switch") == []

    QTest.keyClick(root, Qt.Key_2, Qt.ControlModifier)
    assert pump(lambda: service.named("switch"), timeout=3)
    assert service.named("switch") == [("switch", "claude", "Personal")]


def test_holding_ctrl_shows_every_accounts_number(window, pump):
    from PySide6.QtTest import QTest

    engine, ui, _service, _messages = window()
    root = engine.rootObjects()[0]
    root.requestActivate()

    QTest.keyPress(root, Qt.Key_Control)
    assert pump(lambda: ui.ctrlHeld)
    QTest.keyRelease(root, Qt.Key_Control)
    assert pump(lambda: not ui.ctrlHeld)


def test_the_switch_tooltip_names_the_shortcut(window, pump):
    engine, ui, _service, _messages = window(FakeService(standard()))
    root = engine.rootObjects()[0]

    personal = [a for a in ui.view["groups"][0]["others"]
                if a["name"] == "Personal"][0]
    assert personal["key"] == "2"
    assert personal["actionTip"] == "Switch to Personal"
