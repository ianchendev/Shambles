// A small menu of actions under a button.
import QtQuick
import QtQuick.Controls.Basic

Popup {
    id: root
    // [{label, action, danger, checked}]
    property var items: []
    signal picked(string action)
    padding: 6
    modal: false
    focus: true
    closePolicy: Popup.CloseOnEscape | Popup.CloseOnPressOutside

    background: Rectangle {
        radius: 12
        color: ui.theme.sheet
        border.color: ui.theme.border
        border.width: 1
    }

    contentItem: Column {
        spacing: 2
        Repeater {
            model: root.items
            Btn {
                kind: "ghost"
                width: Math.max(180, implicitWidth)
                implicitHeight: 36
                text: (modelData.checked ? "✓  " : "") + modelData.label
                contentItem: Text {
                    leftPadding: 10
                    text: parent.text
                    font.pixelSize: 14
                    color: modelData.danger ? ui.theme.badText : ui.theme.text
                    verticalAlignment: Text.AlignVCenter
                }
                onClicked: {
                    root.close()
                    root.picked(modelData.action)
                }
            }
        }
    }
}
