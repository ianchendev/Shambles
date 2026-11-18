// The window's tooltip: a short explanation beside the thing it explains.
// One look everywhere, in place of each platform's own.
import QtQuick
import QtQuick.Controls.Basic

ToolTip {
    id: root
    delay: 450
    padding: 0
    // Long tips wrap rather than run across the window.
    width: Math.min(implicitWidth, 280)
    contentItem: Text {
        text: root.text
        color: ui.theme.onToast
        font.pixelSize: 12
        lineHeight: 1.3
        wrapMode: Text.WordWrap
        leftPadding: 10
        rightPadding: 10
        topPadding: 7
        bottomPadding: 7
    }
    background: Rectangle {
        radius: 8
        color: ui.theme.toast
    }
}
