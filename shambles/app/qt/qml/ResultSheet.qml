// A sign-in that ended some way other than working.
import QtQuick

Pane {
    Component.onCompleted: (ui.sheet.retry ? retryButton : closeButton).forceActiveFocus()
    Row {
        width: parent.width
        spacing: 14
        SheetMark { tone: ui.sheet.tone || "bad" }
        SheetHeading {
            width: parent.width - 58
            anchors.verticalCenter: parent.verticalCenter
            text: ui.sheet.title || ""
        }
    }
    SheetText { visible: text !== ""; text: ui.sheet.message || "" }
    SheetCallout { visible: text !== ""; text: ui.sheet.remedy || "" }
    footer: Row {
        anchors.right: parent.right
        spacing: 10
        Btn { id: closeButton; text: "Close"; onClicked: ui.dismiss() }
        Btn {
            id: retryButton
            visible: !!ui.sheet.retry
            kind: "primary"
            text: ui.sheet.retryLabel || "Try again"
            onClicked: ui.retry()
        }
    }
}
