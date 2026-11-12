# PyInstaller spec for the window bundle: Shambles plus Qt, as a directory.
#
#   pip install ".[gui]" pyinstaller
#   pyinstaller --noconfirm packaging/window.spec
#   -> dist/shambles-window/shambles-window
#
# A directory, not one file. A one-file build unpacks itself to a temporary
# folder on every launch, and with Qt inside that is most of a second before
# anything draws.
import re
import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
QT = ROOT / "shambles" / "app" / "qt"

datas = [
    # Read from disk at runtime, so PyInstaller cannot see them as imports.
    (str(ROOT / "shambles" / "providers" / "*.json"), "shambles/providers"),
    (str(ROOT / "shambles" / "app" / "tui" / "*.tcss"), "shambles/app/tui"),
    (str(QT / "qml" / "*.qml"), "shambles/app/qt/qml"),
    (str(QT / "fonts" / "*"), "shambles/app/qt/fonts"),
]

binaries = []
if sys.platform.startswith("linux"):
    # PyInstaller leaves the GL dispatch libraries to the system on purpose.
    # A bare Linux or WSL install has no libEGL at all, and Qt will not even
    # import without it. These two are the vendor-neutral dispatchers from
    # libglvnd, not a driver, so carrying them is safe; the build machine
    # must have them installed (libegl1).
    # SHAMBLES_BUNDLE_LIBS names an extra folder to take them from, for a
    # build machine that cannot install packages.
    import os
    wanted = ("libEGL.so.1", "libGLdispatch.so.0")
    folders = [Path(p) for p in (os.environ.get("SHAMBLES_BUNDLE_LIBS", ""),
                                 "/usr/lib/x86_64-linux-gnu",
                                 "/usr/lib/aarch64-linux-gnu",
                                 "/usr/lib64", "/usr/lib") if p]
    for name in wanted:
        found = next((d / name for d in folders if (d / name).exists()), None)
        if found is None:
            raise SystemExit(
                f"{name} is not installed on the build machine "
                "(apt install libegl1). Without it the bundle will not "
                "start on a bare Linux install.")
        binaries.append((str(found), "."))

# Qt modules the window never touches. PyInstaller collects every QML plugin
# it can find because it cannot trace QML imports, so the unused ones are
# taken back out here. A pattern that matches nothing costs only size.
UNUSED = re.compile(
    r"(Qt6?|libQt6)"
    r"(Designer\w*|Help|Sql|Test|QuickTest|PrintSupport|UiTools|Widgets"
    r"|QuickWidgets|QuickDialogs2\w*|QuickControls2(Fusion|Imagine|Material"
    r"|Universal|FluentWinUI3)\w*|Concurrent|Xml|LabsFolderListModel"
    r"|LabsPlatform|LabsQmlModels|LabsSettings|LabsSharedImage"
    r"|LabsWavefrontMesh|QuickParticles|QuickTimeline\w*|VirtualKeyboard\w*"
    r"|WaylandCompositor\w*)"
    r"([./]|$)")
UNUSED_PATHS = re.compile(
    r"PySide6/(Qt/)?("
    r"translations/"
    r"|qml/QtQuick/Controls/(Fusion|Imagine|Material|Universal|FluentWinUI3"
    r"|designer|macOS|iOS|Windows)/"
    r"|qml/QtQuick/(Dialogs|Particles|VirtualKeyboard|Timeline|tooling"
    r"|NativeStyle|LocalStorage|Pdf|Scene2D|Scene3D)/"
    r"|qml/(Qt/labs|QtTest|QtWayland|Qt5Compat|QtQuick3D)/"
    r"|plugins/(sqldrivers|designer|qmltooling|tls|networkinformation"
    r"|printsupport|styles|generic|egldeviceintegrations)/"
    r"|plugins/platformthemes/libqgtk3"
    r"|plugins/platforms/libq(eglfs|linuxfb|minimalegl|vkkhrdisplay|vnc)\b"
    r")")


def wanted(entry):
    dest = entry[0].replace("\\", "/")
    if "PySide6" not in dest:
        return True
    return not (UNUSED.search(dest.rsplit("/", 1)[-1])
                or UNUSED_PATHS.search(dest))


analysis = Analysis(
    [str(ROOT / "packaging" / "window_entry.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    excludes=["tkinter", "PySide6.QtWidgets", "PySide6.QtSql",
              "PySide6.QtTest", "PySide6.QtPrintSupport"],
)
analysis.binaries = [e for e in analysis.binaries if wanted(e)]
analysis.datas = [e for e in analysis.datas if wanted(e)]

exe = EXE(
    PYZ(analysis.pure),
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="shambles-window",
    # No console window on Windows: this is what a shortcut points at.
    console=sys.platform != "win32",
)
COLLECT(exe, analysis.binaries, analysis.datas, name="shambles-window")
