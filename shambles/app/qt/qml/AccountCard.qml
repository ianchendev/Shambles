// One account. The live one stands alone with its usage on show; the rest
// sit as rows in a shared card. Every row reads the same way across: who,
// how much is used, one badge, one button, and the menu, always last
// (D1, D2). Clicking a row, or Details in its menu, opens the rest.
import QtQuick
import QtQuick.Layouts

Item {
    id: root
    objectName: "card " + (account.id || "")
    property var account: ({})
    // Inside the shared list card, which draws the surface for every row.
    property bool embedded: false
    readonly property var win: Window.window
    readonly property bool live: !!account.live
    readonly property bool open: !!win && win.expandedId === account.id
    readonly property var usage: account.usage || []
    readonly property var badge: account.badge || ({})
    readonly property bool narrow: !!win && win.narrow
    // Rows line up in columns, with the small bars, where there is room
    // for them beside a name; a narrower card drops the bars instead of
    // squeezing the name to nothing.
    readonly property bool columns: !live && body.inner >= 476
    readonly property string shortcut: (account.key || "") === "" ? ""
        : (Qt.platform.os === "osx" ? "⌘" : "Ctrl+") + account.key
    implicitHeight: body.implicitHeight

    function toggle() {
        if (win)
            win.expandedId = open ? "" : account.id
    }
    // Opened near the bottom, the details would land below the footer.
    onOpenChanged: if (open && win && win.revealSoon) win.revealSoon(root)

    Rectangle {
        anchors.fill: parent
        visible: !root.embedded
        radius: 14
        color: ui.theme.surface
        border.color: root.live ? ui.theme.liveBorder : ui.theme.border
        border.width: root.live ? 2 : 1
    }
    Rectangle {
        // Confirms a switch: the card that just became live flashes once.
        id: flash
        anchors.fill: parent
        radius: 14
        color: ui.theme.accent
        opacity: 0
    }
    SequentialAnimation {
        id: pulse
        NumberAnimation { target: flash; property: "opacity"; to: 0.16; duration: 140 }
        NumberAnimation { target: flash; property: "opacity"; to: 0; duration: 720; easing.type: Easing.OutCubic }
    }
    Connections {
        target: root.win
        enabled: !!root.win
        function onPulseIdChanged() {
            if (ui.motion && root.win.pulseId === root.account.id)
                pulse.restart()
        }
    }

    MouseArea {
        anchors.fill: parent
        onClicked: root.toggle()
    }

    Column {
        id: body
        width: parent.width
        topPadding: root.live ? 16 : 10
        bottomPadding: root.live ? 16 : 10
        leftPadding: root.live ? 18 : 16
        rightPadding: 10
        spacing: 12
        readonly property real inner: width - leftPadding - rightPadding

        RowLayout {
            id: line
            width: body.inner
            spacing: 10

            Rectangle {
                // The initial; the account's number while Ctrl is held (D8).
                readonly property real s: root.live ? 40 : 34
                readonly property bool numbered: ui.ctrlHeld && root.shortcut !== ""
                Layout.preferredWidth: s
                Layout.preferredHeight: s
                Layout.alignment: Qt.AlignVCenter
                radius: s / 2
                color: numbered ? ui.theme.accent
                    : root.live ? ui.theme.liveAvatar : ui.theme.avatar
                Text {
                    anchors.centerIn: parent
                    text: parent.numbered ? root.account.key : (root.account.initial || "")
                    color: parent.numbered ? ui.theme.onAccent
                        : root.live ? ui.theme.accentText : ui.theme.avatarText
                    font.pixelSize: root.live ? 16 : 14
                    font.weight: Font.DemiBold
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                Layout.alignment: Qt.AlignVCenter
                spacing: 1
                Item {
                    // The name, then its tags. The name gives way first, and
                    // only as far as the tags need.
                    id: nameLine
                    Layout.fillWidth: true
                    implicitHeight: nameRow.implicitHeight
                    Row {
                        id: nameRow
                        spacing: 7
                        Text {
                            id: nameText
                            objectName: "name"
                            width: Math.min(implicitWidth, nameLine.width - tags.width
                                            - (tags.width > 0 ? nameRow.spacing : 0))
                            anchors.verticalCenter: parent.verticalCenter
                            text: root.account.name || ""
                            color: ui.theme.text
                            font.pixelSize: root.live ? 17 : 15
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Row {
                            id: tags
                            spacing: 7
                            anchors.verticalCenter: parent.verticalCenter
                            Chip {
                                visible: root.live
                                text: "In use"
                                tone: "ok"
                                dot: true
                            }
                            Rectangle {
                                // The plan, as a quiet tag beside the name.
                                visible: (root.account.plan || "") !== "" && !root.narrow
                                width: planText.implicitWidth + 12
                                height: 20
                                radius: 6
                                color: "transparent"
                                border.color: ui.theme.border
                                border.width: 1
                                Text {
                                    id: planText
                                    anchors.centerIn: parent
                                    text: root.account.plan || ""
                                    color: ui.theme.muted
                                    font.pixelSize: 11
                                    font.weight: Font.Medium
                                }
                            }
                        }
                    }
                }
                Text {
                    objectName: "address"
                    Layout.fillWidth: true
                    // Once: not when the name is the address, and not on a
                    // row of a narrow window, which keeps to its name.
                    visible: !!root.account.showAddress
                             && !(root.embedded && root.narrow)
                    text: root.account.email || ""
                    color: ui.theme.muted
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }
            }

            Item {
                // The two small bars, or a dash that says why there are none.
                visible: root.columns
                Layout.preferredWidth: 96
                Layout.preferredHeight: 22
                Layout.alignment: Qt.AlignVCenter
                MiniUsage {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: root.usage.length > 0 && !root.open
                    usage: root.usage
                    tip: root.account.usageTip || ""
                }
                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    visible: root.usage.length === 0
                    text: "–"
                    color: ui.theme.faint
                    HoverHandler { id: noUsage }
                    Tip {
                        text: root.account.usageHint || ""
                        visible: text !== "" && noUsage.hovered
                    }
                }
            }

            Item {
                // The badge's place. In columns it keeps its width when
                // empty, so every row's button and menu line up.
                visible: root.columns || badgeItem.visible
                Layout.preferredWidth: root.columns ? 76 : badgeItem.implicitWidth
                Layout.preferredHeight: 24
                Layout.alignment: Qt.AlignVCenter
                Badge {
                    id: badgeItem
                    anchors.verticalCenter: parent.verticalCenter
                    badge: root.badge
                    onAct: ui.signIn(root.account.provider, root.account.name)
                }
            }

            Item {
                // The one button. Its tooltip says where it goes and its
                // key, or, when it is off, why.
                id: actionSlot
                visible: root.columns || actionButton.visible
                Layout.preferredWidth: root.columns ? 80 : actionButton.implicitWidth
                Layout.preferredHeight: 32
                Layout.alignment: Qt.AlignVCenter
                HoverHandler { id: actionHover }
                Btn {
                    id: actionButton
                    objectName: "action"
                    visible: (root.account.action || "") !== ""
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    kind: root.account.action === "signin" ? "primary" : "soft"
                    text: root.account.actionLabel || ""
                    hint: root.account.actionTip || ""
                    enabled: !!root.account.actionEnabled && !ui.busy
                    implicitHeight: 32
                    font.pixelSize: 14
                    onClicked: root.account.action === "signin"
                               ? ui.signIn(root.account.provider, root.account.name)
                               : ui.switchTo(root.account.provider, root.account.name)
                }
                Tip {
                    text: !root.account.actionEnabled && root.account.actionReason
                          ? root.account.actionReason
                          : (root.account.actionTip || "")
                            + (root.shortcut !== "" ? " · " + root.shortcut : "")
                    visible: actionButton.visible && text !== ""
                             && (actionHover.hovered || actionButton.visualFocus)
                }
            }

            Btn {
                id: more
                objectName: "more"
                kind: "ghost"
                glyph: "more"
                hint: "More for " + (root.account.name || "")
                tip: "Details, rename, remove"
                implicitHeight: 32
                Layout.alignment: Qt.AlignVCenter
                onClicked: menu.open()
                MenuPop {
                    id: menu
                    objectName: "menu"
                    x: more.width - width
                    y: more.height + 4
                    items: [
                        {"label": root.open ? "Hide details" : "Details", "action": "details"},
                        {"label": "Rename", "action": "rename"}
                    ].concat(root.account.canRemove
                             ? [{"label": "Remove account", "action": "remove", "danger": true}]
                             : [])
                    onPicked: (action) => {
                        if (action === "details")
                            root.toggle()
                        else if (action === "rename")
                            ui.askRename(root.account.provider, root.account.name)
                        else
                            ui.askRemove(root.account.provider, root.account.name)
                    }
                }
            }
        }

        Row {
            id: bars
            visible: (root.live || root.open) && root.usage.length > 0
            width: body.inner - 6
            spacing: 24
            Repeater {
                // A count, not the array, so the bars stay while the
                // figures in them change.
                model: root.usage.length
                UsageBar {
                    width: (bars.width - bars.spacing * (root.usage.length - 1)) / Math.max(1, root.usage.length)
                    window: root.usage[index] || ({})
                    showResets: true
                }
            }
        }

        Text {
            visible: (root.live || root.open) && text !== ""
            text: root.account.usageHint || ""
            color: ui.theme.muted
            font.pixelSize: 12
        }

        Column {
            visible: root.open
            width: body.inner - 6
            spacing: 6
            Rectangle { width: parent.width; height: 1; color: ui.theme.hairline }
            Text {
                text: "Saved login"
                color: ui.theme.muted
                font.pixelSize: 12
                font.weight: Font.DemiBold
                topPadding: 4
            }
            Text {
                width: parent.width
                text: root.account.login || ""
                color: ui.theme.text
                font.pixelSize: 13
                lineHeight: 1.25
                wrapMode: Text.WordWrap
            }
        }
    }
}
