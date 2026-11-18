// What is happening while a switch runs: usually a moment, but up to 15 s
// when Claude Code is renewing its login. One line under the header, with
// the reason behind its i; the toast takes over with the result.
import QtQuick

Item {
    id: root
    objectName: "busyBar"
    width: parent ? parent.width : 0
    height: ui.busy ? box.height : 0
    clip: true
    visible: height > 0
    Accessible.role: Accessible.StatusBar
    Accessible.name: ui.busyText + (ui.busyDetail ? " " + ui.busyDetail : "")

    Behavior on height {
        enabled: ui.motion
        NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
    }

    Rectangle {
        id: box
        width: parent.width
        height: 40
        radius: 10
        color: ui.theme.infoSurface
        border.color: ui.theme.accentSoftBorder
        border.width: 1

        Item {
            id: spinner
            x: 12
            anchors.verticalCenter: parent.verticalCenter
            width: 16
            height: 16
            Rectangle {
                anchors.fill: parent
                radius: 8
                color: "transparent"
                border.color: ui.theme.accentSoftBorder
                border.width: 2
            }
            Rectangle {
                width: 5
                height: 5
                radius: 2.5
                color: ui.theme.accent
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
            anchors.leftMargin: 10
            anchors.verticalCenter: parent.verticalCenter
            width: Math.min(implicitWidth,
                            parent.width - spinner.width - 22 - (why.visible ? why.width + 18 : 12))
            text: ui.busyText
            color: ui.theme.infoText
            font.pixelSize: 13
            elide: Text.ElideRight
        }
        Info {
            id: why
            objectName: "busyInfo"
            anchors.left: label.right
            anchors.leftMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            visible: ui.busyDetail !== ""
            tip: ui.busyDetail
            tint: ui.theme.accentText
        }
    }
}
