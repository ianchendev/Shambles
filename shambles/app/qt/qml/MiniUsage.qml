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
                BarFill {
                    width: 58
                    height: 4
                    anchors.verticalCenter: parent.verticalCenter
                    limit: parent.limit
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
