// A folder's path on a line of its own (D7). Wrapped anywhere, not between
// words, so a long path stays one block instead of breaking a sentence
// over three lines.
import QtQuick

Rectangle {
    id: root
    objectName: "folderPath"
    property alias text: label.text
    width: parent ? parent.width : 0
    implicitHeight: label.implicitHeight + 14
    radius: 8
    color: ui.theme.sunken
    border.color: ui.theme.hairline
    border.width: 1
    Text {
        id: label
        x: 10
        y: 7
        width: parent.width - 20
        wrapMode: Text.WrapAnywhere
        color: ui.theme.text
        font.pixelSize: 13
    }
}
