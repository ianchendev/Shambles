"""How the window is started: rendering, scale, motion, and the real QML."""

import pytest

pytest.importorskip("PySide6.QtQuick", exc_type=ImportError,
                    reason="PySide6 is not installed or cannot load")

from qt_fakes import FakeService, failure, unsaved  # noqa: E402
from qt_support import pump, qt_app  # noqa: E402,F401
from shambles.app.qt import application  # noqa: E402
from shambles.app.service import ActionResult  # noqa: E402

WSL = {"WSL_DISTRO_NAME": "Ubuntu"}


# -- environment --------------------------------------------------------------


def test_wsl_gets_software_rendering_because_its_gpu_path_is_unreliable():
    assert application.environment(WSL)["QT_QUICK_BACKEND"] == "software"
    assert "QT_QUICK_BACKEND" not in application.environment({})


def test_the_renderer_can_be_overruled_either_way():
    assert "QT_QUICK_BACKEND" not in application.environment(
        {**WSL, "SHAMBLES_RENDER": "gpu"})
    assert application.environment(
        {"SHAMBLES_RENDER": "software"})["QT_QUICK_BACKEND"] == "software"


def test_what_the_user_already_set_is_never_replaced():
    env = {**WSL, "QT_QUICK_BACKEND": "rhi", "QT_SCALE_FACTOR": "3",
           "SHAMBLES_SCALE": "2", "QT_QUICK_CONTROLS_STYLE": "Fusion"}

    assert application.environment(env) == {}


def test_shambles_scale_means_here_what_it_means_in_the_tk_window():
    assert application.environment(
        {"SHAMBLES_SCALE": "1.5"})["QT_SCALE_FACTOR"] == "1.5"
    for nonsense in ("0.2", "9", "big", ""):
        assert "QT_SCALE_FACTOR" not in application.environment(
            {"SHAMBLES_SCALE": nonsense})


def test_a_wide_screen_reporting_no_scaling_is_relaunched_larger():
    """WSLg reports a 4K panel as 96 dpi; a 1x window there is unreadable."""
    assert application.auto_scale(3840, 1.0, {}) == 1.5
    assert application.auto_scale(1920, 1.0, {}) is None
    assert application.auto_scale(3840, 2.0, {}) is None


def test_a_relaunch_happens_once_and_never_over_the_users_choice():
    assert application.auto_scale(
        3840, 1.0, {application.RESCALED_ENV: "1"}) is None
    assert application.auto_scale(3840, 1.0, {"QT_SCALE_FACTOR": "1"}) is None
    assert application.auto_scale(3840, 1.0, {"SHAMBLES_SCALE": "1"}) is None


def test_motion_follows_the_same_switch_as_the_tk_window():
    assert application.wants_motion({}) is True
    assert application.wants_motion({"SHAMBLES_MOTION": "0"}) is False
    assert application.wants_motion({"SHAMBLES_MOTION": "off"}) is False
    assert application.wants_motion({}, flag=False) is False


# -- the real window ------------------------------------------------------------


@pytest.fixture
def window(qt_app, pump):
    """The real QML on a fake service, with every Qt warning collected."""
    from PySide6.QtCore import qInstallMessageHandler

    messages = []
    previous = qInstallMessageHandler(
        lambda _mode, _context, text: messages.append(text))
    made = {}

    def _build(service=None):
        service = service or FakeService()
        engine, bridge = application.build(service, motion=False, app=qt_app)
        made.update(engine=engine, bridge=bridge)
        pump(timeout=0.05)
        return engine, bridge, service, messages

    yield _build

    engine = made.pop("engine", None)
    if engine is not None:
        # The QML reads the bridge until it is gone, so it goes first -- and
        # really goes: processEvents() alone does not run deferred deletes,
        # and QML left alive past its bridge is torn down at interpreter
        # exit in whatever order the collector picks.
        from PySide6.QtCore import QCoreApplication, QEvent
        for root in engine.rootObjects():
            root.deleteLater()
        engine.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        pump(timeout=0.02)
    made.clear()
    qInstallMessageHandler(previous)


def test_the_window_loads_and_draws_without_a_single_qml_warning(window,
                                                                 pump):
    from PySide6.QtQuick import QQuickWindow  # noqa: F401

    engine, _bridge, _service, messages = window()

    assert engine.rootObjects(), "Main.qml did not load"
    root = engine.rootObjects()[0]
    image = root.grabWindow()
    pump(timeout=0.05)

    assert messages == []
    assert image.width() >= 520 and image.height() >= 420
    colours = {image.pixelColor(x, y).name()
               for x in range(0, image.width(), 40)
               for y in range(0, image.height(), 40)}
    assert len(colours) > 3, "the window drew as a single flat colour"


def test_every_sheet_and_both_themes_draw_without_a_qml_warning(window, pump):
    """Each sheet is its own QML component; a typo in one only shows when
    that sheet opens, which for the rarer ones is never during development."""
    engine, ui, service, messages = window()
    root = engine.rootObjects()[0]

    def shown():
        pump(timeout=0.05)
        root.grabWindow()

    for choice in ("dark", "light"):
        ui.setTheme(choice)
        ui.openAdd("")
        shown()
        ui.dismiss()
        ui.askRename("claude", "Personal")
        shown()
        ui.dismiss()
        ui.askRemove("claude", "Personal")
        shown()
        ui.dismiss()
        ui.askEject()
        shown()
        ui.confirm()
        shown()
        ui.dismiss()
        ui.signIn("claude", "Old")
        service.login[0]("https://claude.ai/oauth/authorize?client_id=x")
        shown()
        service.settle(failure("login", "login_other_account",
                               "A different account.", "Try a private window."))
        shown()
        ui.dismiss()
        ui.switchTo("claude", "Personal")
        assert pump(lambda: not ui.busy, timeout=5)
        root.setProperty("expandedId", "claude/Old")
        shown()

    assert messages == []


def test_the_settle_card_draws_and_settles_without_a_qml_warning(window,
                                                                pump):
    from qt_fakes import saved_elsewhere

    engine, ui, service, messages = window(FakeService(saved_elsewhere()))
    root = engine.rootObjects()[0]
    pump(timeout=0.05)
    root.grabWindow()
    ui.settle("claude")
    assert pump(lambda: not ui.busy, timeout=5)

    assert service.named("switch") == [("switch", "claude", "Home")]
    assert messages == []


def test_the_busy_strip_and_a_due_sign_in_draw_without_a_qml_warning(
        window, pump):
    """R10 and R11 in the real QML: the strip that explains a switch waiting
    on Claude Code's refresh, and Sign in beside Switch on a due account."""
    import threading

    from qt_fakes import due

    service = FakeService(due())
    service.hold = threading.Event()
    engine, ui, _service, messages = window(service)
    root = engine.rootObjects()[0]
    root.setProperty("expandedId", "claude/Spare")
    pump(timeout=0.05)
    root.grabWindow()

    ui.switchTo("claude", "Spare")
    assert pump(lambda: "renewing its login" in ui.busyText, timeout=5)
    root.grabWindow()
    service.hold.set()
    assert pump(lambda: not ui.busy, timeout=5)
    root.grabWindow()

    assert messages == []


def test_the_unsaved_login_and_empty_states_draw_without_a_qml_warning(
        window, pump):
    engine, ui, service, messages = window(FakeService(unsaved()))
    root = engine.rootObjects()[0]
    pump(timeout=0.05)
    root.grabWindow()

    from qt_fakes import group
    from shambles.app.snapshot import Snapshot
    service.snap = Snapshot(1, [group(), group(provider="codex",
                                              title="Codex",
                                              can_sign_in=False)])
    ui.refresh()
    pump(timeout=0.05)
    root.grabWindow()
    ui.setFilter("nothing matches this")
    pump(timeout=0.05)

    assert messages == []


def test_a_sign_in_finishing_as_the_window_closes_does_not_touch_dead_qml(
        window, pump):
    engine, ui, service, messages = window()
    ui.signIn("claude", "Old")
    ui.shutdown()
    service.settle(ActionResult(True, "login", snapshot=service.snap))
    pump(timeout=0.05)

    assert messages == []
