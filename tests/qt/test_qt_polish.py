"""D7, D9 and D12 in the real QML: shorter sheets, a tooltip on every icon
button, one height per place, a focus ring of its own colour, and old
figures drawn as a pattern."""

import pytest

pytest.importorskip("PySide6.QtQuick", exc_type=ImportError,
                    reason="PySide6 is not installed or cannot load")

from PySide6.QtCore import Qt  # noqa: E402

from qt_fakes import FakeService, account, group  # noqa: E402
from qt_support import pump, qt_app  # noqa: E402,F401
from shambles.app.qt import theme  # noqa: E402
from shambles.app.service import ActionPlan  # noqa: E402
from shambles.app.snapshot import Account, Snapshot, Window  # noqa: E402
from test_qt_application import window  # noqa: E402,F401
from test_qt_frame import SMALL, find, inside, items, rect, sized  # noqa: E402


def every_item(root):
    todo, found = [root.contentItem()], []
    while todo:
        item = todo.pop()
        found.append(item)
        todo.extend(item.childItems())
    return found


def buttons(root):
    """Every visible Btn: the only items with an ``iconOnly`` property."""
    return [item for item in every_item(root)
            if item.isVisible() and item.property("iconOnly") is not None]


# -- D9 ------------------------------------------------------------------------------


def test_every_icon_button_says_what_it_does(window, pump):
    engine, ui, _service, _messages = window()
    root = engine.rootObjects()[0]
    ui._say("Could not read your accounts.", "bad")
    pump(timeout=0.1)
    root.grabWindow()

    icons = [b for b in buttons(root) if b.property("iconOnly")]
    assert len(icons) >= 5, "refresh, menu, toast close and the row menus"
    for button in icons:
        assert button.property("hint"), button.objectName()


def test_header_buttons_are_36_and_row_buttons_32(window, pump):
    engine, _ui, _service, _messages = window()
    root = engine.rootObjects()[0]
    header = find(root, "header")
    _hx, _hy, _hw, header_height = rect(header)

    for button in buttons(root):
        _x, y, _w, h = rect(button)
        if y + h <= header_height:
            assert h == 36, button.property("text")
    for name in ("card claude/Personal", "card claude/Old"):
        card = find(root, name)
        for button in [b for b in buttons(root)
                       if inside(rect(b), rect(card))]:
            assert button.height() == 32, (name, button.property("text"))


def test_the_refresh_button_does_not_promise_files_only():
    """On macOS an explicit refresh reads the Keychain."""
    source = open("shambles/app/qt/qml/Main.qml", encoding="utf-8").read()

    assert "local files only" not in source


# -- D12 -----------------------------------------------------------------------------


def test_keyboard_focus_is_drawn_in_its_own_colour(window, pump):
    from PySide6.QtTest import QTest

    engine, ui, _service, _messages = window()
    root = engine.rootObjects()[0]
    root.requestActivate()
    pump(timeout=0.05)

    QTest.keyClick(root, Qt.Key_Tab)
    assert pump(lambda: items(root, "focusRing"), timeout=1)
    ring = items(root, "focusRing")[0]
    x, y, _w, h = rect(ring)
    image = root.grabWindow()

    # Halfway down the ring's left edge: the outer stroke, then the gap.
    edge = image.pixelColor(int(x) + 1, int(y + h / 2)).name()
    gap = image.pixelColor(int(x) + 3, int(y + h / 2)).name()
    assert edge == theme.LIGHT["focus"]
    assert gap == theme.LIGHT["focusGap"]
    assert edge != theme.LIGHT["accent"]


def old_reading():
    old = [Window("session", 40, severity="ok", stale=True),
           Window("week", 70, severity="ok", stale=True)]
    return Snapshot(1, [group(account("Work", active=True),
                              Account(name="Old figures",
                                      email="old@example.test",
                                      plan="max_5x", usage=old))])


def test_an_old_figure_is_a_pattern_not_a_paler_grey(window, pump):
    engine, _ui, _service, messages = window(FakeService(old_reading()))
    root = engine.rootObjects()[0]
    root.grabWindow()

    card = find(root, "card claude/Old figures")
    stripes = [i for i in items(root, "oldStripes")
               if inside(rect(i), rect(card))]
    assert len(stripes) == 2
    assert messages == []


# -- D7 ------------------------------------------------------------------------------


def eject_with_details(service):
    service.plan_eject = lambda: ActionPlan(
        "eject", None, None, True, "Eject Shambles?",
        ("Shambles will stop managing your accounts. Nothing is deleted.",
         "Afterwards:\nLogins stay in /tmp/example."),
        details={"keeps": [{"provider": "Claude Code", "account": "Work",
                            "signedIn": True}],
                 "parked": ["Personal", "Old"],
                 "store": "/tmp/example/.shambles"})


@pytest.mark.parametrize("size", [(760, 720), SMALL])
def test_eject_puts_its_folder_on_a_line_of_its_own(window, pump, size):
    service = FakeService()
    eject_with_details(service)
    engine, ui, _service, messages = window(service)
    root = engine.rootObjects()[0]
    sized(root, pump, *size)

    ui.askEject()
    pump(timeout=0.1)
    root.grabWindow()

    path = find(root, "folderPath")
    assert inside(rect(path), rect(find(root, "sheetPanel")))
    assert messages == []
    if size == (760, 720):
        # Room for all of it: no scroll bar. A rule drawn while the text
        # was still being laid out used to keep the sheet scrolling.
        assert not [bar for bar in items(root, "sheetScrollBar")
                    if bar.property("contentItem").property("opacity") > 0]
        assert inside(rect(path), rect(find(root, "sheetBody")))
