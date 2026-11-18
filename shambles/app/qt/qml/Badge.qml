// A row's one status word (D2): a sign-in that is due, a login that has
// ended, or the account with the most room. What it means is in its
// tooltip; it is a button only when it does something.
import QtQuick
import QtQuick.Templates as T

T.AbstractButton {
    id: control
    objectName: "badge"
    property var badge: ({})
    readonly property bool acts: (badge.action || "") !== ""
    readonly property string tone: badge.tone || ""
    signal act()
    visible: (badge.kind || "") !== ""
    implicitHeight: 22
    implicitWidth: row.implicitWidth + 16
    hoverEnabled: true
    focusPolicy: acts ? Qt.StrongFocus : Qt.NoFocus
    Accessible.role: acts ? Accessible.Button : Accessible.StaticText
    Accessible.name: (badge.text || "") + ". " + (badge.tip || "")
    onClicked: if (acts && !ui.busy) act()
    Keys.onReturnPressed: clicked()

    readonly property color ink: tone === "bad" ? ui.theme.badText
        : tone === "warn" ? ui.theme.warnText : ui.theme.accentText

    background: Rectangle {
        radius: height / 2
        color: control.tone === "bad" ? ui.theme.badBg
            : control.tone === "warn" ? ui.theme.warnBg : ui.theme.accentSoft
        border.width: control.acts && control.hovered ? 1 : 0
        border.color: control.ink
        FocusRing { radius: 11; shown: control.visualFocus }
    }
    contentItem: Item {
        Row {
            id: row
            anchors.centerIn: parent
            spacing: 4
            Icon {
                visible: (control.badge.icon || "") !== ""
                name: control.badge.icon || ""
                size: 13
                weight: 2.2
                color: control.ink
                anchors.verticalCenter: parent.verticalCenter
            }
            Text {
                text: control.badge.text || ""
                color: control.ink
                font.pixelSize: 12
                font.weight: Font.DemiBold
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }
    Tip {
        text: control.badge.tip || ""
        visible: text !== "" && (control.hovered || control.visualFocus)
    }
}
