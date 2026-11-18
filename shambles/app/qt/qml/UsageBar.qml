// One usage window: label, percentage, a bar, and when it resets.
// window.state is "current", "old" or "reset"; window.text is "85%" or
// "reset"; window.tip says the rest (the old figure, the exact date, its age).
import QtQuick

Column {
    id: root
    property var window: ({})
    property bool showResets: true
    spacing: 6

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
            text: root.window.text || ((root.window.percent || 0) + "%")
            color: root.window.tone === "dim" || root.window.state === "reset"
                   ? ui.theme.muted : ui.theme.text
            font.pixelSize: 13
            font.weight: Font.DemiBold
        }
    }
    BarFill {
        width: parent.width
        height: 6
        limit: root.window
    }
    Text {
        visible: root.showResets && text !== ""
        text: root.window.resets || ""
        color: ui.theme.muted
        font.pixelSize: 12
    }

    HoverHandler { id: hover }
    Tip {
        text: root.window.tip || ""
        visible: text !== "" && hover.hovered
    }
}
