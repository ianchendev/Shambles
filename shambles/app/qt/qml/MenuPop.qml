// A small menu of actions under a button.
import QtQuick
import QtQuick.Controls.Basic

Popup {
    id: root
    // [{label, action, danger, checked}]
    property var items: []
    signal picked(string action)
    // What is drawn. Replaced only when the items really differ: the card
    // that owns the menu hands it a new array every time the window is
    // worked out again, and a new array would make every entry again under
    // the pointer and the keyboard focus.
    property var shown: []
    property string drawn: ""
    onItemsChanged: {
        var text = JSON.stringify(items)
        if (text !== drawn) {
            drawn = text
            shown = items
        }
    }
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
            model: root.shown
            Btn {
                objectName: "menu " + modelData.action
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
