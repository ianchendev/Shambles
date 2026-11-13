// The live login is a saved account's, but another account is marked.
// One button settles it: switching to the account the login belongs to.
import QtQuick

Rectangle {
    id: root
    property var settle: ({})
    implicitHeight: col.implicitHeight + 36
    radius: 14
    color: ui.theme.warnSurface
    border.color: ui.theme.warnBorder
    border.width: 2

    Rectangle {
        x: 18
        y: 18
        width: 42
        height: 42
        radius: 21
        color: ui.theme.warnBg
        Icon { anchors.centerIn: parent; name: "alert"; color: ui.theme.warnText; size: 20 }
    }
    Column {
        id: col
        x: 74
        y: 18
        width: parent.width - 92
        spacing: 8
        Text {
            width: parent.width
            text: root.settle.title || ""
            color: ui.theme.text
            font.pixelSize: 16
            font.weight: Font.DemiBold
            wrapMode: Text.WordWrap
        }
        Text {
            width: parent.width
            text: root.settle.body || ""
            color: ui.theme.muted
            font.pixelSize: 13
            lineHeight: 1.25
            wrapMode: Text.WordWrap
        }
        Btn {
            kind: "primary"
            text: root.settle.label || ""
            enabled: !ui.busy
            implicitHeight: 40
            onClicked: ui.settle(root.settle.provider)
        }
    }
}
