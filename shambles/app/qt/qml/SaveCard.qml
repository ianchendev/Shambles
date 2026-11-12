// A live login nobody has saved yet, and the one field needed to keep it.
import QtQuick

Rectangle {
    id: root
    property var save: ({})
    implicitHeight: col.implicitHeight + 36
    radius: 14
    color: ui.theme.warnSurface
    border.color: ui.theme.warnBorder
    border.width: 2

    Rectangle {
        id: badge
        x: 18
        y: 18
        width: 42
        height: 42
        radius: 21
        color: ui.theme.warnBg
        Icon { anchors.centerIn: parent; name: "user"; color: ui.theme.warnText; size: 20 }
    }
    Column {
        id: col
        x: 74
        y: 18
        width: parent.width - 92
        spacing: 8
        Text {
            width: parent.width
            text: root.save.title || ""
            color: ui.theme.text
            font.pixelSize: 16
            font.weight: Font.DemiBold
            wrapMode: Text.WordWrap
        }
        Text {
            width: parent.width
            text: root.save.body || ""
            color: ui.theme.muted
            font.pixelSize: 13
            lineHeight: 1.25
            wrapMode: Text.WordWrap
        }
        Text {
            text: "Name for this account"
            color: ui.theme.muted
            font.pixelSize: 12
            font.weight: Font.DemiBold
            topPadding: 4
        }
        Row {
            width: parent.width
            spacing: 10
            Field {
                id: nameField
                label: "Name for this account"
                width: parent.width - saveButton.width - 10
                text: root.save.suggested || ""
                onAccepted: saveButton.clicked()
            }
            Btn {
                id: saveButton
                kind: "primary"
                text: "Save login"
                implicitHeight: 40
                onClicked: ui.saveCurrent(root.save.provider, nameField.text)
            }
        }
        Text {
            visible: text !== ""
            width: parent.width
            text: root.save.error || ""
            color: ui.theme.badText
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }
    }
}
