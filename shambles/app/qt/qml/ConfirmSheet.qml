// A question before something that cannot be undone: remove, eject.
import QtQuick

Pane {
    // Cancel holds the focus, so Enter on a destructive question
    // answers no.
    Component.onCompleted: keepButton.forceActiveFocus()
    SheetHeading { text: ui.sheet.title || "" }
    SheetText { text: ui.sheet.message || "" }
    Column {
        // What each tool is left on, a line each (D7).
        visible: (ui.sheet.lines || []).length > 0
        width: parent.width
        spacing: 2
        Repeater {
            model: ui.sheet.lines || []
            SheetText { text: modelData }
        }
    }
    Column {
        visible: (ui.sheet.path || "") !== ""
        width: parent.width
        spacing: 6
        TipText {
            text: ui.sheet.pathLabel || ""
            tip: ui.sheet.pathTip || ""
        }
        FolderPath { text: ui.sheet.path || "" }
    }
    footer: Row {
        anchors.right: parent.right
        spacing: 10
        Btn { id: keepButton; text: "Cancel"; onClicked: ui.dismiss() }
        Btn {
            kind: "danger"
            text: ui.sheet.confirmLabel || "Continue"
            onClicked: ui.confirm()
        }
    }
}
