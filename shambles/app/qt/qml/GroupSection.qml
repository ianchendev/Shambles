// One provider: its heading, anything that needs saying, its live account,
// then everyone else.
import QtQuick

Column {
    id: root
    property var group: ({})
    spacing: 10
    readonly property var others: group.others || []

    Item {
        width: parent.width
        height: 20
        Text {
            id: title
            text: root.group.title || ""
            color: ui.theme.text
            font.pixelSize: 13
            font.weight: Font.DemiBold
            anchors.baseline: parent.bottom
            anchors.baselineOffset: -5
        }
        Text {
            anchors.left: title.right
            anchors.leftMargin: 10
            anchors.baseline: title.baseline
            text: root.group.surfaces || ""
            color: ui.theme.muted
            font.pixelSize: 12
        }
        Text {
            anchors.right: parent.right
            anchors.baseline: title.baseline
            text: root.group.summary || ""
            color: ui.theme.muted
            font.pixelSize: 12
        }
    }

    Loader {
        width: parent.width
        active: !!root.group.save
        visible: active
        sourceComponent: Component { SaveCard { save: root.group.save || ({}) } }
    }

    Loader {
        width: parent.width
        active: !!root.group.settle
        visible: active
        sourceComponent: Component { SettleCard { settle: root.group.settle || ({}) } }
    }

    Repeater {
        model: root.group.notices || []
        NoticeBox {
            width: root.width
            notice: modelData
        }
    }

    Loader {
        width: parent.width
        active: !!root.group.live
        visible: active
        sourceComponent: Component { AccountCard { account: root.group.live || ({}) } }
    }

    Rectangle {
        visible: root.others.length > 0
        width: parent.width
        height: rows.height
        radius: 14
        color: ui.theme.surface
        border.color: ui.theme.border
        border.width: 1
        Column {
            id: rows
            width: parent.width
            Repeater {
                model: root.others
                Column {
                    width: rows.width
                    Rectangle {
                        visible: index > 0
                        x: 18
                        width: parent.width - 36
                        height: 1
                        color: ui.theme.hairline
                    }
                    AccountCard {
                        width: parent.width
                        account: modelData
                        embedded: true
                    }
                }
            }
        }
    }

    Loader {
        width: parent.width
        active: !!root.group.empty
        visible: active
        sourceComponent: Component {
            Item {
                id: slot
                readonly property var empty: root.group.empty || ({})
                implicitHeight: empty.kind === "add" ? 76 : note.implicitHeight + 32
                Rectangle {
                    // Dashes are not a Rectangle border style, so the slot is
                    // drawn solid and light: a place something goes.
                    anchors.fill: parent
                    radius: 14
                    color: "transparent"
                    border.color: ui.theme.faint
                    border.width: 1
                }
                Btn {
                    visible: slot.empty.kind === "add"
                    anchors.fill: parent
                    kind: "ghost"
                    glyph: "plus"
                    text: slot.empty.text || ""
                    font.pixelSize: 15
                    onClicked: ui.openAdd(root.group.provider)
                }
                Column {
                    id: note
                    visible: slot.empty.kind === "cli"
                    x: 18
                    y: 16
                    width: parent.width - 36
                    spacing: 4
                    Text {
                        width: parent.width
                        text: slot.empty.text || ""
                        color: ui.theme.text
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        width: parent.width
                        text: slot.empty.detail || ""
                        color: ui.theme.muted
                        font.pixelSize: 13
                        lineHeight: 1.25
                        wrapMode: Text.WordWrap
                    }
                }
            }
        }
    }
}
