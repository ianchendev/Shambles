// A question before something that cannot be undone: remove, eject.
import QtQuick

Pane {
    // Cancel holds the focus, so Enter on a destructive question
    // answers no.
    Component.onCompleted: keepButton.forceActiveFocus()
    SheetHeading { text: ui.sheet.title || "" }
    SheetText { text: ui.sheet.message || "" }
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
