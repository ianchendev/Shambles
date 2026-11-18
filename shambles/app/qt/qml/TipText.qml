// A sentence with the rest of its explanation behind an i at its end.
import QtQuick

Item {
    id: root
    property alias text: label.text
    property string tip: ""
    property color color: ui.theme.text
    width: parent ? parent.width : 0
    implicitHeight: label.implicitHeight

    Text {
        id: label
        width: Math.min(implicitWidth, root.width - (why.visible ? why.width + 8 : 0))
        color: root.color
        lineHeight: 1.3
        wrapMode: Text.WordWrap
    }
    Info {
        id: why
        anchors.left: label.right
        anchors.leftMargin: 6
        y: 2
        visible: root.tip !== ""
        tip: root.tip
    }
}
