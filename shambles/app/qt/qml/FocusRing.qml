// Where the keyboard is (D12): a violet ring, apart from the blue of
// buttons, the live card and anything selected, with a gap inside it so it
// reads on any fill. Drawn just outside its control.
import QtQuick

Item {
    id: root
    objectName: "focusRing"
    // The control's own corner radius.
    property real radius: 10
    property bool shown: false
    anchors.fill: parent
    anchors.margins: -4
    visible: shown
    Rectangle {
        anchors.fill: parent
        radius: root.radius + 4
        color: "transparent"
        border.color: ui.theme.focus
        border.width: 2
    }
    Rectangle {
        anchors.fill: parent
        anchors.margins: 2
        radius: root.radius + 2
        color: "transparent"
        border.color: ui.theme.focusGap
        border.width: 2
    }
}
