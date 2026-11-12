// One usage window: label, percentage, a bar, and when it resets.
import QtQuick

Column {
    id: root
    property var window: ({})
    property bool showResets: true
    spacing: 6

    readonly property color fill: window.tone === "gone" ? ui.theme.barGone
        : window.tone === "soon" ? ui.theme.barSoon
        : window.tone === "dim" ? ui.theme.barDim : ui.theme.barOk

    Item {
        width: parent.width
        height: 18
        Text {
            text: root.window.label || ""
            color: ui.theme.muted
            font.pixelSize: 13
        }
        Text {
            anchors.right: parent.right
            text: (root.window.percent || 0) + "%"
            color: root.window.tone === "dim" ? ui.theme.muted : ui.theme.text
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }
    }
    Rectangle {
        width: parent.width
        height: 6
        radius: 3
        color: ui.theme.track
        Rectangle {
            height: 6
            radius: 3
            color: root.fill
            width: Math.max(root.window.fill > 0 ? 6 : 0, parent.width * (root.window.fill || 0))
            Behavior on width {
                enabled: ui.motion
                NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
            }
        }
    }
    Text {
        visible: root.showResets && text !== ""
        text: root.window.resets || ""
        color: ui.theme.muted
        font.pixelSize: 12
    }
}
