// Drag the window by whatever this covers; double-click it to maximise.
//
// Under WSL the title bar comes from Windows' Linux window host, and on a 4K
// screen it is too small to grab. This lets the window's own header do the
// job. The system's own move where the platform has one, so the window
// manager snaps and tiles as usual; by hand where it has none.
import QtQuick

MouseArea {
    id: root
    readonly property var win: Window.window
    property point pressedAt
    property bool moving: false
    property bool system: false
    // A press and release that did not move the window.
    signal tapped()
    acceptedButtons: Qt.LeftButton

    onPressed: (mouse) => {
        pressedAt = Qt.point(mouse.x, mouse.y)
        moving = false
        system = false
    }
    onPositionChanged: (mouse) => {
        if (!pressed || !win)
            return
        var dx = mouse.x - pressedAt.x
        var dy = mouse.y - pressedAt.y
        if (!moving) {
            var far = Qt.styleHints.startDragDistance
            if (Math.abs(dx) < far && Math.abs(dy) < far)
                return
            moving = true
            system = win.startSystemMove()
        }
        if (!system && win.visibility === Window.Windowed) {
            win.x += dx
            win.y += dy
        }
    }
    onClicked: if (!moving) tapped()
    onDoubleClicked: {
        if (!win)
            return
        if (win.visibility === Window.Maximized)
            win.showNormal()
        else
            win.showMaximized()
    }
}
