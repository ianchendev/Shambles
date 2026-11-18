// What an action just did, in words. Slides in under the header and pushes
// the list down, so it never covers a row's buttons. Errors stay until
// closed or replaced, and so do warnings (tone "warn": something a switch
// did not reach); anything else goes by itself.
import QtQuick

Item {
    id: root
    objectName: "toast"
    readonly property var toast: ui.toast
    readonly property bool bad: toast.tone === "bad"
    readonly property bool warn: toast.tone === "warn"
    // Read before it goes: an error, or advice on what to do next.
    readonly property bool stays: bad || warn
    property bool shown: false
    width: parent ? parent.width : 0
    height: shown ? box.height : 0
    clip: true
    visible: height > 0
    Accessible.role: Accessible.AlertMessage
    Accessible.name: toast.text || ""

    Behavior on height {
        enabled: ui.motion
        NumberAnimation { duration: 160; easing.type: Easing.OutCubic }
    }

    Rectangle {
        id: box
        width: parent.width
        height: Math.max(40, label.implicitHeight + 20)
        radius: 10
        color: root.bad ? ui.theme.badSurface
             : root.warn ? ui.theme.warnSurface : ui.theme.infoSurface
        border.color: root.bad ? ui.theme.badBorder
                    : root.warn ? ui.theme.warnBorder : ui.theme.accentSoftBorder
        border.width: 1

        MouseArea {
            // Anything that does not stay goes away when clicked.
            anchors.fill: parent
            enabled: !root.stays
            onClicked: root.shown = false
        }
        Icon {
            id: mark
            x: 12
            y: 12
            name: root.stays ? "alert" : "check"
            size: 16
            weight: 2.2
            color: root.bad ? ui.theme.badText
                 : root.warn ? ui.theme.warnText : ui.theme.accentText
        }
        Text {
            id: label
            anchors.left: mark.right
            anchors.leftMargin: 10
            anchors.right: actions.left
            anchors.rightMargin: 8
            anchors.verticalCenter: parent.verticalCenter
            text: root.toast.text || ""
            color: root.bad ? ui.theme.badText
                 : root.warn ? ui.theme.warnText : ui.theme.infoText
            font.pixelSize: 13
            lineHeight: 1.25
            wrapMode: Text.WordWrap
        }
        Row {
            id: actions
            anchors.right: parent.right
            anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 4
            Btn {
                // What the message offers to do next, if anything.
                objectName: "toastAction"
                visible: (root.toast.actionLabel || "") !== ""
                kind: "soft"
                text: root.toast.actionLabel || ""
                implicitHeight: 30
                font.pixelSize: 13
                onClicked: {
                    root.shown = false
                    ui.toastAction()
                }
            }
            Btn {
                objectName: "toastClose"
                visible: root.stays
                kind: "ghost"
                glyph: "close"
                hint: "Close this message"
                implicitHeight: 30
                onClicked: root.shown = false
            }
        }
    }
    Timer {
        id: timer
        interval: 7000
        onTriggered: root.shown = false
    }
    Connections {
        target: ui
        function onToastChanged() {
            root.shown = (ui.toast.text || "") !== ""
            if (root.stays)
                timer.stop()
            else
                timer.restart()
        }
    }
}
