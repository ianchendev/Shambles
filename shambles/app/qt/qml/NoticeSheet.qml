// One-off notices, such as a store migration at start-up.
import QtQuick

Pane {
    Component.onCompleted: okButton.forceActiveFocus()
    Row {
        width: parent.width
        spacing: 14
        SheetMark { tone: ui.sheet.tone || "ok" }
        SheetHeading {
            width: parent.width - 58
            anchors.verticalCenter: parent.verticalCenter
            text: ui.sheet.title || ""
        }
    }
    Repeater {
        model: ui.sheet.messages || []
        SheetText { text: modelData }
    }
    footer: Btn {
        id: okButton
        anchors.right: parent.right
        kind: "primary"
        text: "OK"
        onClicked: ui.dismiss()
    }
}
