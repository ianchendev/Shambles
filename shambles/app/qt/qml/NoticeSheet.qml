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
        // {text, path, tip}: a path on its own line, the why behind an i.
        model: ui.sheet.messages || []
        Column {
            width: parent.width
            spacing: 6
            TipText {
                text: modelData.text || ""
                tip: modelData.tip || ""
            }
            FolderPath {
                visible: (modelData.path || "") !== ""
                text: modelData.path || ""
            }
        }
    }
    footer: Btn {
        id: okButton
        anchors.right: parent.right
        kind: "primary"
        text: "OK"
        onClicked: ui.dismiss()
    }
}
