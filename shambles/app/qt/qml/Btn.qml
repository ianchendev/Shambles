// The window's button. A real button, so Tab reaches it, Space and Enter
// press it, and a screen reader announces it.
import QtQuick
import QtQuick.Templates as T

T.Button {
    id: control
    // primary | soft | plain | danger | ghost
    property string kind: "plain"
    property string glyph: ""
    property string hint: ""
    readonly property bool iconOnly: text === ""

    implicitHeight: 38
    implicitWidth: iconOnly ? implicitHeight : row.implicitWidth + 30
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    opacity: enabled ? 1 : 0.5
    font.pixelSize: 14
    font.weight: Font.DemiBold

    Accessible.name: text !== "" ? text : hint
    Accessible.description: hint
    Keys.onReturnPressed: clicked()
    Keys.onEnterPressed: clicked()
    onActiveFocusChanged: {
        var w = control.Window.window
        if (activeFocus && w && w.reveal)
            w.reveal(control)
    }

    readonly property color fg: kind === "primary" ? ui.theme.onAccent
        : kind === "soft" ? ui.theme.accentText
        : kind === "danger" ? ui.theme.badText
        : kind === "ghost" ? ui.theme.muted : ui.theme.text
    readonly property color bg: kind === "primary" ? (hovered ? ui.theme.accentHover : ui.theme.accent)
        : kind === "soft" ? ui.theme.accentSoft
        : kind === "ghost" ? (hovered || down ? ui.theme.hairline : "transparent")
        : ui.theme.surface
    readonly property color edge: kind === "soft" ? ui.theme.accentSoftBorder
        : kind === "danger" ? ui.theme.badBorder
        : kind === "plain" ? ui.theme.border : "transparent"

    background: Rectangle {
        radius: 10
        color: control.bg
        border.color: control.edge
        border.width: control.kind === "primary" || control.kind === "ghost" ? 0 : 1
        opacity: control.down ? 0.8 : 1
        Rectangle {
            // The focus ring. Outside the button so it reads on any fill.
            anchors.fill: parent
            anchors.margins: -3
            radius: parent.radius + 3
            color: "transparent"
            border.color: ui.theme.focus
            border.width: 2
            visible: control.visualFocus
        }
    }

    contentItem: Item {
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 8
            Icon {
                visible: control.glyph !== ""
                name: control.glyph
                color: control.fg
                size: 17
                weight: 2.2
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                visible: !control.iconOnly
                text: control.text
                font: control.font
                color: control.fg
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
}
