// Something true about a provider that its accounts cannot show.
import QtQuick

Rectangle {
    id: root
    property var notice: ({})
    property bool open: !notice.collapsed
    implicitHeight: col.implicitHeight + 28
    radius: 14
    color: notice.tone === "bad" ? ui.theme.badSurface
        : notice.tone === "warn" ? ui.theme.warnSurface : ui.theme.infoSurface
    border.width: 1
    border.color: notice.tone === "bad" ? ui.theme.badBorder
        : notice.tone === "warn" ? ui.theme.warnBorder : ui.theme.accentSoftBorder
    readonly property color ink: notice.tone === "bad" ? ui.theme.badText
        : notice.tone === "warn" ? ui.theme.warnText : ui.theme.infoText

    Icon {
        id: mark
        x: 16
        y: 15
        name: notice.tone === "info" ? "info" : "alert"
        color: root.ink
        size: 18
    }
    Column {
        id: col
        x: 46
        y: 14
        width: parent.width - 62 - (toggle.visible ? toggle.width + 8 : 0)
        spacing: 6
        Text {
            width: parent.width
            text: root.notice.message || ""
            color: ui.theme.text
            font.weight: Font.DemiBold
            wrapMode: Text.WordWrap
            maximumLineCount: root.open ? 20 : 1
            elide: Text.ElideRight
        }
        Text {
            visible: root.open && text !== ""
            width: parent.width
            text: root.notice.remedy || ""
            color: ui.theme.muted
            font.pixelSize: 13
            lineHeight: 1.25
            wrapMode: Text.WordWrap
        }
        Btn {
            visible: root.open && (root.notice.action || "") !== ""
            text: root.notice.actionLabel || ""
            implicitHeight: 34
            onClicked: ui.forgetMarker(root.notice.provider)
        }
    }
    Btn {
        id: toggle
        visible: !!root.notice.collapsed
        anchors.right: parent.right
        anchors.rightMargin: 10
        y: 8
        kind: "ghost"
        implicitHeight: 32
        text: root.open ? "Hide" : "Details"
        onClicked: root.open = !root.open
    }
}
