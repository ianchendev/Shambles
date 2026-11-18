// Everything that used to be a separate dialog: adding, signing in, the
// result of a sign-in, confirmations, renaming, and one-off notices. Drawn
// inside the window, over a scrim, so nothing opens that the window manager
// can lose behind another window.
//
// This file is the frame: the scrim and the panel. Each kind of sheet is
// its own file (AddSheet, LoginSheet, ResultSheet, ConfirmSheet,
// RenameSheet, NoticeSheet), and each is a Pane: what it says, which
// scrolls when the window is too short for it, and its buttons, which never
// scroll out of reach.
import QtQuick

Item {
    id: root
    anchors.fill: parent
    visible: ui.sheetOpen
    readonly property var sheet: ui.sheet
    readonly property string kind: sheet.kind || ""

    Rectangle {
        anchors.fill: parent
        color: ui.theme.scrim
    }
    WindowMover {
        // Clicking outside closes a form, but never a running sign-in or a
        // confirmation: those end by a deliberate button. Dragging moves
        // the window, as the header does when no sheet is up.
        anchors.fill: parent
        hoverEnabled: true
        onWheel: (wheel) => { wheel.accepted = true }
        onTapped: {
            if (root.kind !== "login" && root.kind !== "confirm")
                ui.dismiss()
        }
    }

    Rectangle {
        id: panel
        objectName: "sheetPanel"
        width: Math.min(540, parent.width - 40)
        height: Math.min(content.implicitHeight + 2 * pad, parent.height - 40)
        anchors.centerIn: parent
        radius: 18
        color: ui.theme.sheet
        border.color: ui.theme.border
        border.width: 1
        readonly property int pad: parent.width < 520 ? 20 : 26

        MouseArea { anchors.fill: parent }

        Loader {
            id: content
            anchors.fill: parent
            anchors.margins: panel.pad
            sourceComponent: root.kind === "add" ? addForm
                : root.kind === "login" ? loginView
                : root.kind === "result" ? resultView
                : root.kind === "confirm" ? confirmView
                : root.kind === "rename" ? renameForm
                : root.kind === "notice" ? noticeView : null
        }
    }

    Component { id: addForm; AddSheet {} }
    Component { id: loginView; LoginSheet {} }
    Component { id: resultView; ResultSheet {} }
    Component { id: confirmView; ConfirmSheet {} }
    Component { id: renameForm; RenameSheet {} }
    Component { id: noticeView; NoticeSheet {} }
}
