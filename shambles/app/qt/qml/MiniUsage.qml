// A parked account's two limits as small bars (D3): the 5-hour on top, the
// week below. The figures sit beside them; the dates and ages are in the
// tooltip. A limit that has reset since it was read is hatched.
import QtQuick

Item {
    id: root
    objectName: "miniUsage"
    property var usage: []
    property string tip: ""
    implicitWidth: 96
    implicitHeight: bars.implicitHeight

    Column {
        id: bars
        spacing: 3
        Repeater {
            // A count, not the array: the bars stay put when the figures
            // change, and so does a tooltip being read.
            model: Math.min(2, root.usage.length)
            Row {
                readonly property var limit: root.usage[index] || ({})
                readonly property bool reset: limit.state === "reset"
                spacing: 6
                Item {
                    width: 58
                    height: 4
                    anchors.verticalCenter: parent.verticalCenter
                    clip: true
                    Rectangle {
                        anchors.fill: parent
                        radius: 2
                        color: ui.theme.track
                        visible: !parent.parent.reset
                    }
                    Rectangle {
                        visible: !parent.parent.reset
                        height: parent.height
                        radius: 2
                        width: Math.max((parent.parent.limit.fill || 0) > 0 ? 3 : 0,
                                        parent.width * (parent.parent.limit.fill || 0))
                        color: parent.parent.limit.tone === "gone" ? ui.theme.barGone
                            : parent.parent.limit.tone === "soon" ? ui.theme.barSoon
                            : parent.parent.limit.tone === "dim" ? ui.theme.barDim
                            : ui.theme.barOk
                    }
                    Row {
                        // Hatched: the bar has emptied since the figure.
                        visible: parent.parent.reset
                        spacing: 3
                        Repeater {
                            model: 10
                            Rectangle { width: 3; height: 4; radius: 1; color: ui.theme.okDot; opacity: 0.6 }
                        }
                    }
                }
                Text {
                    width: 32
                    text: parent.limit.text || ""
                    color: parent.reset ? ui.theme.okText
                        : parent.limit.tone === "dim" ? ui.theme.muted : ui.theme.text
                    font.pixelSize: 11
                    font.weight: parent.reset ? Font.DemiBold : Font.Normal
                }
            }
        }
    }
    HoverHandler { id: hover }
    Tip {
        text: root.tip
        visible: text !== "" && hover.hovered
    }
}
