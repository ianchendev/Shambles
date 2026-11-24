// D4: a sign-in deadline in its last days, in one line: who and when, a
// Sign in button, the explanation behind an i, and a × that hides the line
// until tomorrow. The row's badge says it the rest of the time.
import QtQuick

Rectangle {
    id: root
    objectName: "deadline"
    property var deadline: ({})
    readonly property string who: deadline.account || ""
    readonly property string said: deadline.text || ""
    implicitHeight: 40
    radius: 12
    color: ui.theme.warnSurface
    border.color: ui.theme.warnBorder
    border.width: 1
    Accessible.role: Accessible.AlertMessage
    Accessible.name: said

    function esc(text) {
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    }

    Icon {
        id: mark
        x: 12
        anchors.verticalCenter: parent.verticalCenter
        name: "clock"
        size: 16
        weight: 2
        color: ui.theme.warnText
    }
    Row {
        // Who, then when. A narrow window cuts the name, never the date,
        // and says "stops" for "stops working" when even that is tight.
        id: label
        anchors.left: mark.right
        anchors.leftMargin: 8
        anchors.verticalCenter: parent.verticalCenter
        spacing: 4
        readonly property real room: actions.x - x - why.width - 18
        readonly property bool roomy: room - whenInFull.implicitWidth - spacing >= 80
        Text {
            objectName: "deadlineName"
            width: Math.max(0, Math.min(implicitWidth,
                                        label.room - when.implicitWidth - label.spacing))
            text: root.who
            color: ui.theme.warnText
            font.pixelSize: 13
            font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            id: when
            objectName: "deadlineWhen"
            text: label.roomy ? (root.deadline.when || "") : (root.deadline.whenShort || "")
            color: ui.theme.warnText
            font.pixelSize: 13
        }
    }
    Text {
        // Measures the long form, to choose between the two.
        id: whenInFull
        visible: false
        text: root.deadline.when || ""
        font.pixelSize: 13
    }
    Info {
        id: why
        anchors.left: label.right
        anchors.leftMargin: 6
        anchors.verticalCenter: parent.verticalCenter
        tip: root.deadline.tip || ""
        tint: ui.theme.warnText
    }
    Row {
        id: actions
        anchors.right: parent.right
        anchors.rightMargin: 6
        anchors.verticalCenter: parent.verticalCenter
        spacing: 2
        Btn {
            visible: !!root.deadline.canSignIn
            kind: "primary"
            text: "Sign in"
            tip: "Sign in to " + root.who + " again"
            enabled: !ui.busy
            implicitHeight: 28
            font.pixelSize: 13
            onClicked: ui.signIn(root.deadline.provider, root.who)
        }
        Btn {
            objectName: "deadlineClose"
            kind: "ghost"
            glyph: "close"
            hint: "Hide until tomorrow"
            tip: "Hide until tomorrow"
            implicitHeight: 28
            onClicked: ui.hideDeadline(root.deadline.key)
        }
    }
}
