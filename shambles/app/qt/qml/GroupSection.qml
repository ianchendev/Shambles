// One provider: its heading, anything that needs saying, its live account,
// then everyone else.
//
// Rows, notices and the live card are each keyed (KeyedList), so working
// the window out again keeps every card that is still there: an open menu
// stays open, focus stays where it was, a tooltip stays up.
import QtQuick

Column {
    id: root
    property var group: ({})
    spacing: 10
    readonly property var others: group.others || []
    readonly property var notices: group.notices || []
    readonly property var byId: {
        var found = {}
        for (var i = 0; i < others.length; i++)
            found[others[i].id] = others[i]
        return found
    }
    readonly property var noticeByKey: {
        var found = {}
        for (var i = 0; i < notices.length; i++)
            found[notices[i].code + "/" + notices[i].account] = notices[i]
        return found
    }
    // From ``group`` itself: when it changes, the properties worked out
    // from it may not have caught up yet.
    function syncAll() {
        rowKeys.sync((group.others || []).map(function (a) { return a.id }))
        noticeKeys.sync((group.notices || []).map(function (n) {
            return n.code + "/" + n.account
        }))
        liveKeys.sync(group.live ? [group.live.id] : [])
    }
    onGroupChanged: syncAll()
    Component.onCompleted: syncAll()

    KeyedList { id: rowKeys }
    KeyedList { id: noticeKeys }
    KeyedList { id: liveKeys }

    Item {
        width: parent.width
        height: 22
        Row {
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Text {
                text: root.group.title || ""
                color: ui.theme.text
                font.pixelSize: 13
                font.weight: Font.DemiBold
                anchors.verticalCenter: parent.verticalCenter
            }
            Info {
                // Where a switch here reaches: said once, on hover (D1).
                visible: tip !== ""
                tip: root.group.surfacesTip || ""
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        Row {
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: 6
            Text {
                text: root.group.summary || ""
                color: ui.theme.muted
                font.pixelSize: 12
                anchors.verticalCenter: parent.verticalCenter
            }
            Info {
                // D6: a tool that is not installed is this line, not a card.
                objectName: "missingInfo"
                visible: !!root.group.missing
                tip: root.group.missingTip || ""
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    DeadlineStrip {
        width: parent.width
        visible: !!root.group.deadline
        deadline: root.group.deadline || ({})
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
        model: noticeKeys
        NoticeBox {
            width: root.width
            notice: root.noticeByKey[model.key] || ({})
        }
    }

    Repeater {
        model: liveKeys
        AccountCard {
            width: root.width
            account: root.group.live || ({})
        }
    }

    Text {
        // A reason every row below shares, said once (D1).
        objectName: "hold"
        visible: text !== "" && root.others.length > 0
        width: parent.width
        text: root.group.hold || ""
        color: ui.theme.muted
        font.pixelSize: 12
        wrapMode: Text.WordWrap
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
                model: rowKeys
                Column {
                    width: rows.width
                    Rectangle {
                        visible: index > 0
                        x: 16
                        width: parent.width - 32
                        height: 1
                        color: ui.theme.hairline
                    }
                    AccountCard {
                        width: parent.width
                        account: root.byId[model.key] || ({})
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
                implicitHeight: 64
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
                    anchors.fill: parent
                    kind: "ghost"
                    glyph: "plus"
                    text: (root.group.empty || {}).text || ""
                    font.pixelSize: 15
                    onClicked: ui.openAdd(root.group.provider)
                }
            }
        }
    }
}
