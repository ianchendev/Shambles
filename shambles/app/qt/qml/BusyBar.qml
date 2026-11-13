// What is happening while a switch runs: usually a moment, but up to 15 s
// when Claude Code is renewing its login. Said in place of the toast, which
// takes over with the result.
import QtQuick

Rectangle {
    id: root
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 44
    width: Math.min(parent.width - 40, 580)
    height: label.implicitHeight + 26
    radius: 12
    color: ui.theme.toast
    visible: ui.busy
    Accessible.role: Accessible.StatusBar
    Accessible.name: ui.busyText

    Item {
        id: spinner
        x: 16
        anchors.verticalCenter: parent.verticalCenter
        width: 16
        height: 16
        Rectangle {
            anchors.fill: parent
            radius: 8
            color: "transparent"
            border.color: ui.theme.onToast
            border.width: 2
            opacity: 0.3
        }
        Rectangle {
            width: 5
            height: 5
            radius: 2.5
            color: ui.theme.onToast
            x: 5.5
            y: -1
        }
        RotationAnimation on rotation {
            running: root.visible && ui.motion
            from: 0
            to: 360
            duration: 1000
            loops: Animation.Infinite
        }
    }
    Text {
        id: label
        anchors.left: spinner.right
        anchors.leftMargin: 12
        anchors.right: parent.right
        anchors.rightMargin: 16
        anchors.verticalCenter: parent.verticalCenter
        text: ui.busyText
        color: ui.theme.onToast
        font.pixelSize: 13
        lineHeight: 1.25
        wrapMode: Text.WordWrap
    }
}
