// What an action just did, in words, without taking the window over.
import QtQuick

Rectangle {
    id: root
    readonly property var toast: ui.toast
    readonly property bool bad: toast.tone === "bad"
    anchors.horizontalCenter: parent.horizontalCenter
    anchors.bottom: parent.bottom
    anchors.bottomMargin: 44
    width: Math.min(parent.width - 40, 580)
    height: label.implicitHeight + 26
    radius: 12
    color: bad ? ui.theme.badBg : ui.theme.toast
    border.color: bad ? ui.theme.badBorder : "transparent"
    border.width: bad ? 1 : 0
    opacity: 0
    visible: opacity > 0
    Accessible.role: Accessible.AlertMessage
    Accessible.name: toast.text || ""

    Behavior on opacity {
        enabled: ui.motion
        NumberAnimation { duration: 160 }
    }
    Text {
        id: label
        x: 16
        y: 13
        width: parent.width - 32
        text: root.toast.text || ""
        color: root.bad ? ui.theme.badText : ui.theme.onToast
        font.pixelSize: 13
        lineHeight: 1.25
        wrapMode: Text.WordWrap
    }
    MouseArea {
        anchors.fill: parent
        onClicked: root.opacity = 0
    }
    Timer {
        id: timer
        interval: root.bad ? 14000 : 7000
        onTriggered: root.opacity = 0
    }
    Connections {
        target: ui
        function onToastChanged() {
            root.opacity = 1
            timer.restart()
        }
    }
}
