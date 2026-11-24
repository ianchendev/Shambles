// A live login nobody has saved yet, and the one field needed to keep it.
import QtQuick

Rectangle {
    id: root
    property var save: ({})
    implicitHeight: col.implicitHeight + 36
    radius: 12
    color: ui.theme.warnSurface
    border.color: ui.theme.warnBorder
    border.width: 1

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
        TipText {
            // "Not saved yet", with why that matters behind its i.
            objectName: "saveBody"
            text: root.save.body || ""
            tip: root.save.tip || ""
            color: ui.theme.muted
            font.pixelSize: 13
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
                onAccepted: saveButton.clicked()
                // Filled in when the suggestion changes, not every time the
                // window is worked out again, which would overwrite a name
                // being typed.
                readonly property string suggested: root.save.suggested || ""
                onSuggestedChanged: text = suggested
                Component.onCompleted: text = suggested
            }
            Btn {
                id: saveButton
                kind: "primary"
                text: "Save login"
                enabled: !ui.busy
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
