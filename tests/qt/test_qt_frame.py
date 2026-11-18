"""The window's frame, in the real QML: moving, resizing, remembering where
it was (D5), small windows (F7), and messages that do not cover the list
(D10).

The offscreen platform has no window manager, so Qt's system move and
resize report "not supported" here and the window moves by hand instead.
That fallback is what these tests drive. The system path is the platform's
own: on X11, Qt sends _NET_WM_MOVERESIZE, which WSLg's window manager lists
in _NET_SUPPORTED.
"""

import pytest

pytest.importorskip("PySide6.QtQuick", exc_type=ImportError,
                    reason="PySide6 is not installed or cannot load")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtQuick import QQuickItem  # noqa: E402

from qt_fakes import FakeService, account, group  # noqa: E402
from qt_support import pump, qt_app  # noqa: E402,F401
from shambles.app.qt import placement  # noqa: E402
from shambles.app.snapshot import Snapshot  # noqa: E402
from test_qt_application import window  # noqa: E402,F401

SMALL = placement.MINIMUM


def items(root, name):
    """Every visible QML item called ``name``. Walked by item, not by
    QObject: what a Repeater makes is not a QObject child of the window."""
    found, todo = [], [root.contentItem()]
    while todo:
        item = todo.pop()
        if item.objectName() == name and item.isVisible():
            found.append(item)
        todo.extend(item.childItems())
    return found


def find(root, name):
    """The visible QML item called ``name``."""
    found = items(root, name)
    assert found, f"no visible item called {name!r}"
    return found[-1]


def find_visible(root, name):
    return items(root, name)


def drawn(bar):
    """Whether a scroll bar's handle is on show, not only there to grab."""
    return bar.property("contentItem").property("opacity") > 0


def rect(item):
    """Where ``item`` is drawn, in window coordinates."""
    corner = item.mapToScene(QPointF(0, 0))
    return corner.x(), corner.y(), item.width(), item.height()


def inside(inner, outer, slack=0.5):
    ix, iy, iw, ih = inner
    ox, oy, ow, oh = outer
    return (ix >= ox - slack and iy >= oy - slack
            and ix + iw <= ox + ow + slack and iy + ih <= oy + oh + slack)


def drag(root, start, delta, pump, steps=4):
    """Press at ``start``, move the pointer by ``delta`` on the screen,
    release. Positions sent are the window's own, so a window that moves
    under the pointer brings the pointer back towards where it was pressed,
    as a real one does."""
    from PySide6.QtTest import QTest

    origin = (root.x(), root.y())

    def at(step):
        moved_x, moved_y = root.x() - origin[0], root.y() - origin[1]
        return QPoint(start.x() + delta.x() * step // steps - moved_x,
                      start.y() + delta.y() * step // steps - moved_y)

    QTest.mousePress(root, Qt.LeftButton, Qt.NoModifier, start)
    for step in range(1, steps + 1):
        QTest.mouseMove(root, at(step))
        pump(timeout=0.02)
    QTest.mouseRelease(root, Qt.LeftButton, Qt.NoModifier, at(steps))
    pump(timeout=0.05)


def sized(root, pump, width, height):
    root.setWidth(width)
    root.setHeight(height)
    pump(timeout=0.1)
    root.grabWindow()
    assert (root.width(), root.height()) == (width, height)


def many():
    """Enough accounts that a short window has to scroll."""
    names = ["Work", "Personal", "Client", "Research", "Staging", "Last"]
    return Snapshot(1, [group(*(account(n, active=(i == 0))
                                for i, n in enumerate(names)))])


# -- D5: moving, resizing, remembering ------------------------------------------------


def test_the_window_can_be_made_as_small_as_the_layout_is_drawn_for(window):
    engine, _ui, _service, _messages = window()
    root = engine.rootObjects()[0]

    assert (root.minimumWidth(), root.minimumHeight()) == SMALL


def test_it_opens_where_it_was_left(window):
    service = FakeService()
    service.place = {"x": 40, "y": 30, "width": 600, "height": 480,
                     "maximized": False}

    engine, _ui, _service, _messages = window(service)
    root = engine.rootObjects()[0]

    assert (root.x(), root.y(), root.width(), root.height()) == (
        40, 30, 600, 480)


def test_dragging_the_header_moves_the_window(window, pump):
    engine, _ui, _service, messages = window()
    root = engine.rootObjects()[0]
    before = (root.x(), root.y())

    # Beside the word "Shambles": header, but no button.
    drag(root, QPoint(200, 30), QPoint(60, 40), pump)

    assert (root.x(), root.y()) == (before[0] + 60, before[1] + 40)
    assert messages == []


def test_dragging_from_a_header_button_does_not_move_the_window(window, pump):
    engine, _ui, _service, _messages = window()
    root = engine.rootObjects()[0]
    before = (root.x(), root.y())
    add = find(root, "addButton")
    x, y, w, h = rect(add)

    drag(root, QPoint(int(x + w / 2), int(y + h / 2)), QPoint(60, 40), pump)

    assert (root.x(), root.y()) == before


def test_double_clicking_the_header_maximises_and_restores(window, pump):
    from PySide6.QtGui import QWindow
    from PySide6.QtTest import QTest

    engine, _ui, _service, _messages = window()
    root = engine.rootObjects()[0]

    QTest.mouseDClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(200, 30))
    assert pump(lambda: root.visibility() == QWindow.Maximized)
    QTest.mouseDClick(root, Qt.LeftButton, Qt.NoModifier, QPoint(200, 30))
    assert pump(lambda: root.visibility() == QWindow.Windowed)


def test_the_corner_grip_resizes_the_window(window, pump):
    engine, _ui, _service, _messages = window()
    root = engine.rootObjects()[0]
    sized(root, pump, 600, 500)
    x, y, w, h = rect(find(root, "resizeGrip"))

    assert inside((x, y, w, h), (0, 0, 600, 500))
    drag(root, QPoint(int(x + w / 2), int(y + h / 2)), QPoint(-80, 50), pump)

    assert (root.width(), root.height()) == (520, 550)


def test_the_corner_grip_stops_at_the_minimum(window, pump):
    engine, _ui, _service, _messages = window()
    root = engine.rootObjects()[0]
    sized(root, pump, 500, 400)
    x, y, w, h = rect(find(root, "resizeGrip"))

    drag(root, QPoint(int(x + w / 2), int(y + h / 2)), QPoint(-200, -200),
         pump)

    assert (root.width(), root.height()) == SMALL


def test_where_the_window_was_moved_to_is_saved_once_it_settles(window, pump):
    engine, _ui, service, _messages = window()
    root = engine.rootObjects()[0]
    pump(timeout=1.0)
    service.calls.clear()

    drag(root, QPoint(200, 30), QPoint(60, 40), pump)
    assert pump(lambda: service.named("set_window_place"), timeout=3)

    x, y, width, height, maximized = service.named("set_window_place")[-1][1:]
    assert (x, y) == (root.x(), root.y())
    assert (width, height, maximized) == (root.width(), root.height(), False)


def test_a_maximised_window_keeps_its_ordinary_size_for_next_time(window,
                                                                  pump):
    engine, _ui, service, _messages = window()
    root = engine.rootObjects()[0]
    sized(root, pump, 600, 500)
    pump(timeout=1.0)

    root.showMaximized()
    assert pump(lambda: service.named("set_window_place")
                and service.named("set_window_place")[-1][-1] is True,
                timeout=3)

    assert service.named("set_window_place")[-1][3:5] == (600, 500)


def test_a_window_left_maximised_opens_maximised(window, pump):
    from PySide6.QtGui import QWindow

    service = FakeService()
    service.place = {"x": 40, "y": 30, "width": 600, "height": 480,
                     "maximized": True}

    engine, _ui, _service, _messages = window(service)
    root = engine.rootObjects()[0]

    assert pump(lambda: root.visibility() == QWindow.Maximized)


def test_a_narrow_window_drops_the_address_line_from_rows(window, pump):
    engine, _ui, _service, _messages = window()
    root = engine.rootObjects()[0]

    sized(root, pump, 760, 600)
    wide = items(root, "address")
    sized(root, pump, *SMALL)
    narrow = items(root, "address")

    # Work is live and keeps its line; Personal and Old are rows.
    assert len(wide) == 3 and len(narrow) == 1


# -- F7: a small window loses nothing ------------------------------------------------


def open_each_sheet(ui, service):
    """Every sheet, each left open in turn: yields its name."""
    from qt_fakes import failure

    ui.openAdd("")
    yield "add"
    ui.dismiss()
    ui.signIn("claude", "Old")
    service.login[0]("https://claude.ai/oauth/authorize?client_id=x")
    yield "sign-in"
    service.settle(failure("login", "login_other_account",
                           "A different account.", "Try a private window."))
    yield "result"
    ui.dismiss()
    ui.askRename("claude", "Personal")
    yield "rename"
    ui.dismiss()
    ui.askRemove("claude", "Personal")
    yield "remove"
    ui.dismiss()
    ui.askEject()
    yield "eject"
    ui.confirm()
    yield "notice"
    ui.dismiss()


def long_eject(service):
    from shambles.app.service import ActionPlan

    after = "\n".join(f"Logins for account {n} stay in /tmp/example/{n}."
                      for n in range(12))
    service.plan_eject = lambda: ActionPlan(
        "eject", None, None, True, "Stop using Shambles?",
        ("Shambles will stop managing your accounts. Nothing is deleted.",
         "Afterwards:\n" + after))


def test_every_sheet_keeps_its_buttons_in_reach_at_the_smallest_size(window,
                                                                      pump):
    service = FakeService()
    long_eject(service)
    engine, ui, _service, messages = window(service)
    root = engine.rootObjects()[0]
    sized(root, pump, *SMALL)
    whole = (0, 0) + SMALL

    for name in open_each_sheet(ui, service):
        pump(timeout=0.1)
        root.grabWindow()
        panel = rect(find(root, "sheetPanel"))
        footer = rect(find(root, "sheetFooter"))
        assert footer[3] > 0, name
        assert inside(panel, whole), name
        assert inside(footer, panel), name

    assert messages == []


def test_a_sheet_too_long_for_the_window_says_it_scrolls(window, pump):
    service = FakeService()
    long_eject(service)
    engine, ui, _service, _messages = window(service)
    root = engine.rootObjects()[0]
    sized(root, pump, *SMALL)

    ui.askEject()
    pump(timeout=0.1)
    root.grabWindow()

    assert drawn(find(root, "sheetScrollBar"))

    sized(root, pump, 760, 720)
    ui.dismiss()
    ui.askRename("claude", "Personal")
    pump(timeout=0.1)
    root.grabWindow()
    assert not [bar for bar in items(root, "sheetScrollBar") if drawn(bar)]


def test_opening_an_account_near_the_bottom_brings_its_details_into_view(
        window, pump):
    engine, _ui, _service, _messages = window(FakeService(many()))
    root = engine.rootObjects()[0]
    sized(root, pump, *SMALL)
    scroller = find(root, "scroller")
    assert scroller.property("contentY") == 0

    root.setProperty("expandedId", "claude/Last")
    card = find(root, "card claude/Last")

    def shown():
        root.grabWindow()
        view = rect(scroller)
        return inside(rect(card), view, slack=1)

    assert pump(shown, timeout=2), (rect(card), rect(scroller))


# -- D10: messages push the list down ------------------------------------------------


def test_a_message_pushes_the_list_down_instead_of_covering_it(window, pump):
    engine, ui, _service, _messages = window()
    root = engine.rootObjects()[0]
    scroller = find(root, "scroller")
    top = rect(scroller)[1]

    ui._say("Switched to Personal. Start a new session to pick it up.")
    toast = find(root, "toast")
    assert pump(lambda: rect(scroller)[1] >= top + toast.height())

    tx, ty, tw, th = rect(toast)
    assert ty + th <= rect(scroller)[1]
    assert ty >= rect(find(root, "header"))[3]


def test_an_error_has_a_close_button_and_stays_until_closed(window, pump):
    from PySide6.QtTest import QTest

    engine, ui, _service, _messages = window()
    root = engine.rootObjects()[0]

    ui._say("Could not read your accounts.", "bad")
    pump(timeout=0.1)
    close = find(root, "toastClose")
    x, y, w, h = rect(close)
    QTest.mouseClick(root, Qt.LeftButton, Qt.NoModifier,
                     QPoint(int(x + w / 2), int(y + h / 2)))

    assert pump(lambda: not find_visible(root, "toast"))


def test_an_ordinary_message_has_no_close_button(window, pump):
    engine, ui, _service, _messages = window()
    root = engine.rootObjects()[0]

    ui._say("Renamed to Home.")
    pump(timeout=0.1)

    assert find_visible(root, "toast")
    assert not find_visible(root, "toastClose")


def test_the_waiting_line_is_one_line_with_its_reason_behind_an_i(window,
                                                                   pump):
    import threading

    service = FakeService()
    service.hold = threading.Event()
    engine, ui, _service, messages = window(service)
    root = engine.rootObjects()[0]
    sized(root, pump, *SMALL)

    ui.switchTo("claude", "Personal")
    assert pump(lambda: "renewing" in ui.busyText, timeout=5)
    pump(timeout=0.2)
    root.grabWindow()
    bar = find(root, "busyBar")
    info = find(root, "busyInfo")

    assert bar.height() == 40
    assert inside(rect(info), rect(bar))
    assert "15 s" in info.property("tip")
    service.hold.set()
    assert pump(lambda: not ui.busy, timeout=5)
    assert messages == []

