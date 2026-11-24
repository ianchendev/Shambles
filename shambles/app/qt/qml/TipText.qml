// A sentence with the rest of its explanation behind an i at its end.
import QtQuick

Item {
    id: root
    property alias text: label.text
    property string tip: ""
    property color color: ui.theme.text
    property alias font: label.font
    width: parent ? parent.width : 0
    implicitHeight: label.implicitHeight
    // Where the text's last line ends, so the i follows it rather than the
    // first line of a sentence that wrapped.
    property real lastEnd: label.implicitWidth
    property real lastTop: 0
    property real lastHeight: label.implicitHeight

    Text {
        id: label
        width: Math.min(implicitWidth, root.width - (why.visible ? why.width + 8 : 0))
        color: root.color
        lineHeight: 1.3
        wrapMode: Text.WordWrap
        onLineLaidOut: (line) => {
            if (line.isLast) {
                root.lastEnd = line.x + line.implicitWidth
                root.lastTop = line.y
                root.lastHeight = line.height
            }
        }
    }
    Info {
        id: why
        objectName: "tipTextInfo"
        x: root.lastEnd + 6
        y: root.lastTop + Math.max(0, (root.lastHeight - height) / 2)
        visible: root.tip !== ""
        tip: root.tip
    }
}
