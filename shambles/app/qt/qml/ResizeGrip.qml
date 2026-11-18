// The corner to drag the window bigger or smaller by. The system's own
// resize where the platform has one; by hand where it has none.
import QtQuick

MouseArea {
    id: root
    objectName: "resizeGrip"
    readonly property var win: Window.window
    property point pressedAt
    property bool moving: false
    property bool system: false
    width: 18
    height: 18
    anchors.right: parent.right
    anchors.bottom: parent.bottom
    visible: !!win && win.visibility === Window.Windowed
    acceptedButtons: Qt.LeftButton
    cursorShape: Qt.SizeFDiagCursor
    hoverEnabled: true

    onPressed: (mouse) => {
        pressedAt = Qt.point(mouse.x, mouse.y)
        moving = false
        system = false
    }
    onPositionChanged: (mouse) => {
        if (!pressed || !win)
            return
        if (!moving) {
            moving = true
            system = win.startSystemResize(Qt.RightEdge | Qt.BottomEdge)
        }
        if (!system) {
            win.width = Math.max(win.minimumWidth, win.width + mouse.x - pressedAt.x)
            win.height = Math.max(win.minimumHeight, win.height + mouse.y - pressedAt.y)
        }
    }

    Canvas {
        // Three short diagonals, the usual mark for a corner that resizes.
        anchors.fill: parent
        anchors.margins: 3
        antialiasing: true
        property color tint: ui.theme.muted
        onTintChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d")
            ctx.reset()
            ctx.strokeStyle = tint
            ctx.lineWidth = 1.4
            ctx.lineCap = "round"
            for (var i = 0; i < 3; i++) {
                var o = 1 + i * 4
                ctx.beginPath()
                ctx.moveTo(width - 1, o)
                ctx.lineTo(o, height - 1)
                ctx.stroke()
            }
        }
    }
}
