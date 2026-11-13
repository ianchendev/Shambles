// One account. The live one stands alone with its usage on show; the rest
// sit as rows in a shared card and open to show the same detail.
import QtQuick
import QtQuick.Layouts

Item {
    id: root
    property var account: ({})
    // Inside the shared list card, which draws the surface for every row.
    property bool embedded: false
    readonly property var win: Window.window
    readonly property bool live: !!account.live
    readonly property bool open: !!win && win.expandedId === account.id
    readonly property var usage: account.usage || []
    implicitHeight: body.implicitHeight

    function toggle() {
        if (win)
            win.expandedId = open ? "" : account.id
    }

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
        topPadding: root.live ? 18 : 11
        bottomPadding: root.live ? 18 : 11
        leftPadding: 18
        rightPadding: 12
        spacing: 14
        readonly property real inner: width - leftPadding - rightPadding

        RowLayout {
            width: body.inner
            spacing: 12

            Rectangle {
                readonly property real s: root.live ? 42 : 34
                Layout.preferredWidth: s
                Layout.preferredHeight: s
                Layout.alignment: Qt.AlignTop
                radius: s / 2
                color: root.live ? ui.theme.liveAvatar : ui.theme.avatar
                Text {
                    anchors.centerIn: parent
                    text: root.account.initial || ""
                    color: root.live ? ui.theme.accentText : ui.theme.avatarText
                    font.pixelSize: root.live ? 16 : 14
                    font.weight: Font.DemiBold
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                RowLayout {
                    spacing: 8
                    Text {
                        Layout.maximumWidth: body.inner * 0.45
                        text: root.account.name || ""
                        color: ui.theme.text
                        font.pixelSize: root.live ? 18 : 15
                        font.weight: Font.DemiBold
                        elide: Text.ElideRight
                    }
                    Chip {
                        visible: root.live
                        text: "Live"
                        tone: "ok"
                        dot: true
                    }
                    Chip {
                        visible: (root.account.chip || "") !== ""
                        text: root.account.chip || ""
                        tone: root.account.chipTone || "bad"
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: root.account.subtitle || ""
                    color: ui.theme.muted
                    font.pixelSize: 13
                    elide: Text.ElideRight
                }
                Text {
                    Layout.fillWidth: true
                    visible: text !== ""
                    text: root.account.actionReason || ""
                    color: ui.theme.muted
                    font.pixelSize: 12
                    wrapMode: Text.WordWrap
                }
            }

            Column {
                visible: !root.live && !root.open && root.width > 640
                         && (root.account.usageSummary || "") !== ""
                Layout.alignment: Qt.AlignVCenter
                spacing: 2
                Text {
                    anchors.right: parent.right
                    text: root.account.usageSummary || ""
                    color: ui.theme.muted
                    font.pixelSize: 12
                }
                Text {
                    anchors.right: parent.right
                    visible: text !== ""
                    text: root.account.usageNote || ""
                    color: ui.theme.muted
                    font.pixelSize: 12
                }
            }

            Rectangle {
                // The number key that switches to this account.
                visible: (root.account.key || "") !== ""
                Layout.preferredWidth: 22
                Layout.preferredHeight: 22
                radius: 6
                color: "transparent"
                border.color: ui.theme.border
                border.width: 1
                Text {
                    anchors.centerIn: parent
                    text: root.account.key || ""
                    color: ui.theme.muted
                    font.pixelSize: 12
                    font.weight: Font.DemiBold
                }
            }

            Btn {
                // A login that still works but only a new sign-in keeps past
                // its date: Sign in beside Switch, before the date.
                visible: !!root.account.signInExtra
                kind: "plain"
                text: "Sign in"
                enabled: !!root.account.signInEnabled && !ui.busy
                hint: "Sign in to " + root.account.name + " again"
                implicitHeight: 36
                onClicked: ui.signIn(root.account.provider, root.account.name)
            }

            Btn {
                visible: (root.account.action || "") !== ""
                kind: root.account.action === "signin" ? "primary" : "soft"
                text: root.account.actionLabel || ""
                enabled: !!root.account.actionEnabled && !ui.busy
                hint: root.account.action === "signin"
                      ? "Sign in to " + root.account.name
                      : "Switch to " + root.account.name
                implicitHeight: 36
                onClicked: root.account.action === "signin"
                           ? ui.signIn(root.account.provider, root.account.name)
                           : ui.switchTo(root.account.provider, root.account.name)
            }

            Btn {
                kind: "ghost"
                glyph: "chevron"
                hint: (root.open ? "Hide details for " : "Show details for ") + root.account.name
                implicitHeight: 36
                rotation: root.open ? 180 : 0
                onClicked: root.toggle()
            }

            Btn {
                id: more
                kind: "ghost"
                glyph: "more"
                hint: "More for " + root.account.name
                implicitHeight: 36
                onClicked: menu.open()
                MenuPop {
                    id: menu
                    x: more.width - width
                    y: more.height + 4
                    items: root.account.canRemove
                        ? [{"label": "Rename", "action": "rename"},
                           {"label": "Remove account", "action": "remove", "danger": true}]
                        : [{"label": "Rename", "action": "rename"}]
                    onPicked: (action) => {
                        if (action === "rename")
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
                model: root.usage
                UsageBar {
                    width: (bars.width - bars.spacing * (root.usage.length - 1)) / Math.max(1, root.usage.length)
                    window: modelData
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
            Text {
                visible: text !== ""
                text: root.account.usageNote ? "Usage " + root.account.usageNote
                      + ", while this account was last in use." : ""
                color: ui.theme.muted
                font.pixelSize: 12
            }
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
