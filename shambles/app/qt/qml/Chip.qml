// A small status word. Only ever shown when something needs the user.
import QtQuick

Rectangle {
    id: root
    property string text: ""
    // ok | warn | bad
    property string tone: "ok"
    property bool dot: false
    implicitHeight: 22
    implicitWidth: row.implicitWidth + 18
    radius: 11
    color: tone === "bad" ? ui.theme.badBg : tone === "warn" ? ui.theme.warnBg : ui.theme.okBg
    readonly property color ink: tone === "bad" ? ui.theme.badText
        : tone === "warn" ? ui.theme.warnText : ui.theme.okText

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        Rectangle {
            visible: root.dot
            width: 7
            height: 7
            radius: 3.5
            color: ui.theme.okDot
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            text: root.text
            color: root.ink
            font.pixelSize: 12
            font.weight: Font.DemiBold
        }
    }
}
