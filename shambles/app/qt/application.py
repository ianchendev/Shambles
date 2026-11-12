"""Start the Qt window on a :class:`~shambles.app.service.ShamblesService`.

Importing this module imports PySide6, so nothing outside ``shambles gui``
may import it: the CLI and the terminal UI have to keep working on an
install that has no Qt at all.
"""

import os
import signal
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QFontDatabase, QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine

from .bridge import Bridge

HERE = Path(__file__).resolve().parent
QML = HERE / "qml" / "Main.qml"
FONTS = HERE / "fonts"
FONT_FAMILY = "Inter"

#: ``SHAMBLES_SCALE`` is the Tk window's knob; the same values mean the same
#: thing here so nobody has to learn a second one.
SCALE_ENV = "SHAMBLES_SCALE"
SCALE_LIMITS = (1.0, 4.0)
#: ``software`` or ``gpu``, to overrule the choice made below.
RENDER_ENV = "SHAMBLES_RENDER"
MOTION_ENV = "SHAMBLES_MOTION"
MOTION_OFF = frozenset({"0", "off", "no", "none", "false"})

#: A screen this wide that reports no scaling is a HiDPI panel behind
#: something that hides its density -- WSLg does exactly this -- and a window
#: drawn at 1x on it is too small to read.
WIDE_SCREEN_PX = 2560
WIDE_SCREEN_SCALE = 1.5
#: Set on the relaunched process so it cannot relaunch itself again.
RESCALED_ENV = "SHAMBLES_RESCALED"

#: How often to hand control back to Python so a pending Ctrl+C is seen.
SIGNAL_POLL_MS = 150


def is_wsl(env) -> bool:
    return bool(env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"))


def environment(env) -> dict:
    """What to add to the environment before Qt starts.

    Returns only additions. Anything the user already set is left alone, so
    ``QT_QUICK_BACKEND=...`` or ``QT_SCALE_FACTOR=...`` on the command line
    still wins over every choice made here.
    """
    extra = {}
    # One style everywhere. Left to itself Qt picks a different one per
    # platform, and the window is drawn by its own QML either way.
    if "QT_QUICK_CONTROLS_STYLE" not in env:
        extra["QT_QUICK_CONTROLS_STYLE"] = "Basic"

    # Under WSL the GPU path goes through a D3D12 translation layer that has
    # an open bug drawing Qt Quick windows black or transparent
    # (microsoft/wslg#1025). The software renderer draws this window
    # identically and cannot hit it.
    render = env.get(RENDER_ENV, "").strip().lower()
    if "QT_QUICK_BACKEND" not in env:
        if render == "software" or (render != "gpu" and is_wsl(env)):
            extra["QT_QUICK_BACKEND"] = "software"

    scale = _scale(env.get(SCALE_ENV))
    if scale is not None and "QT_SCALE_FACTOR" not in env:
        extra["QT_SCALE_FACTOR"] = f"{scale:g}"
    return extra


def _scale(value):
    """``SHAMBLES_SCALE`` as a usable factor, or None."""
    try:
        scale = float(value)
    except (TypeError, ValueError):
        return None
    low, high = SCALE_LIMITS
    return scale if low <= scale <= high else None


def auto_scale(screen_width: int, device_pixel_ratio: float, env):
    """The scale to relaunch at, or None to carry on as started.

    Qt fixes its scale factor before the first window exists, and the only
    way to learn the screen's size is to start. So a wide screen reporting no
    scaling costs one relaunch, and only when the user has not chosen a
    scale themselves.
    """
    if env.get(RESCALED_ENV) or "QT_SCALE_FACTOR" in env:
        return None
    if _scale(env.get(SCALE_ENV)) is not None:
        return None
    if device_pixel_ratio > 1.0 or screen_width < WIDE_SCREEN_PX:
        return None
    return WIDE_SCREEN_SCALE


def wants_motion(env, flag=True) -> bool:
    return flag and env.get(MOTION_ENV, "").strip().lower() not in MOTION_OFF


def _relaunch(scale, *, execv=os.execv):
    os.environ["QT_SCALE_FACTOR"] = f"{scale:g}"
    os.environ[RESCALED_ENV] = "1"
    if getattr(sys, "frozen", False):
        argv = [sys.executable, *sys.argv[1:]]
    else:
        argv = [sys.executable, *sys.orig_argv[1:]]
    execv(sys.executable, argv)


def _system_dark(app):
    scheme = app.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return None


def load_fonts() -> None:
    """Register the bundled typeface.

    Shipped rather than taken from the system because a bare Linux install
    has one sans-serif and it is not one anybody would choose.
    """
    for path in sorted(FONTS.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def build(service, *, motion=True, app=None):
    """Make the engine, bridge and window. Returns ``(engine, bridge)``.

    Separate from :func:`run_window` so a test can build the real window
    against a fake service and never enter an event loop.
    """
    app = app or QGuiApplication.instance()
    load_fonts()
    font = app.font()
    font.setFamily(FONT_FAMILY)
    font.setPixelSize(14)
    app.setFont(font)

    bridge = Bridge(service, clipboard=app.clipboard(),
                    system_dark=lambda: _system_dark(app), motion=motion)
    app.styleHints().colorSchemeChanged.connect(
        lambda _scheme: bridge.system_theme_changed())

    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("ui", bridge)
    bridge.start()
    engine.load(QUrl.fromLocalFile(str(QML)))
    return engine, bridge


def run_window(service, *, motion=True, argv=None) -> int:
    """Open the window and run until it closes. Returns the exit status."""
    os.environ.update(environment(os.environ))
    app = QGuiApplication(list(argv) if argv is not None else sys.argv[:1])
    app.setApplicationName("Shambles")
    app.setDesktopFileName("shambles")

    screen = app.primaryScreen()
    if screen is not None:
        scale = auto_scale(screen.size().width(), screen.devicePixelRatio(),
                           os.environ)
        if scale is not None:
            _relaunch(scale)

    engine, bridge = build(service, motion=wants_motion(os.environ, motion),
                           app=app)
    if not engine.rootObjects():
        sys.stderr.write("Shambles could not load its window.\n")
        return 1

    # Qt's event loop blocks in C++, and Python only runs signal handlers
    # between bytecodes. Without a timer to hand control back, Ctrl+C is
    # recorded and never delivered.
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, lambda *_: app.quit())
        except (ValueError, OSError):
            pass
    pump = QTimer()
    pump.timeout.connect(lambda: None)
    pump.start(SIGNAL_POLL_MS)

    try:
        return app.exec()
    finally:
        # A sign-in still running would be orphaned, and the account it was
        # set aside for would stay signed out. Cancelling puts the user back.
        bridge.shutdown()
        del engine
