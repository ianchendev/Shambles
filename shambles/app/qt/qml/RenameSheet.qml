// Renaming an account.
import QtQuick

Pane {
    spacing: 14
    Component.onCompleted: {
        renameField.forceActiveFocus()
        renameField.selectAll()
    }
    SheetHeading { text: ui.sheet.title || "" }
    SheetLabel { text: "New name" }
    Field {
        id: renameField
        width: parent.width
        label: "New name"
        text: ui.sheet.name || ""
        onAccepted: ui.submitRename(text)
    }
    Text {
        visible: text !== ""
        width: parent.width
        text: ui.sheet.error || ""
        color: ui.theme.badText
        font.pixelSize: 13
        wrapMode: Text.WordWrap
    }
    footer: Row {
        anchors.right: parent.right
        spacing: 10
        Btn { text: "Cancel"; onClicked: ui.dismiss() }
        Btn { kind: "primary"; text: "Rename"; onClicked: ui.submitRename(renameField.text) }
    }
}
