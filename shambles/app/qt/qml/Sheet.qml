// Everything that used to be a separate dialog: adding, signing in, the
// result of a sign-in, confirmations, renaming, and one-off notices. Drawn
// inside the window, over a scrim, so nothing opens that the window manager
// can lose behind another window.
import QtQuick
import QtQuick.Templates as T

Item {
    id: root
    anchors.fill: parent
    visible: ui.sheetOpen
    readonly property var sheet: ui.sheet
    readonly property string kind: sheet.kind || ""

    Rectangle {
        anchors.fill: parent
        color: ui.theme.scrim
    }
    MouseArea {
        // Clicking outside closes a form, but never a running sign-in or a
        // confirmation: those end by a deliberate button.
        anchors.fill: parent
        hoverEnabled: true
        onWheel: (wheel) => { wheel.accepted = true }
        onClicked: {
            if (root.kind !== "login" && root.kind !== "confirm")
                ui.dismiss()
        }
    }

    Rectangle {
        id: panel
        width: Math.min(540, parent.width - 40)
        height: Math.min(content.implicitHeight + 52, parent.height - 40)
        anchors.centerIn: parent
        radius: 18
        color: ui.theme.sheet
        border.color: ui.theme.border
        border.width: 1

        MouseArea { anchors.fill: parent }

        Flickable {
            anchors.fill: parent
            anchors.margins: 26
            contentWidth: width
            contentHeight: content.implicitHeight
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            Loader {
                id: content
                width: parent.width
                sourceComponent: root.kind === "add" ? addForm
                    : root.kind === "login" ? loginView
                    : root.kind === "result" ? resultView
                    : root.kind === "confirm" ? confirmView
                    : root.kind === "rename" ? renameForm
                    : root.kind === "notice" ? noticeView : null
            }
        }
    }

    component Heading: Text {
        width: parent ? parent.width : 0
        color: ui.theme.text
        font.pixelSize: 20
        font.weight: Font.DemiBold
        wrapMode: Text.WordWrap
    }
    component Body: Text {
        width: parent ? parent.width : 0
        color: ui.theme.text
        lineHeight: 1.3
        wrapMode: Text.WordWrap
    }
    component Label: Text {
        color: ui.theme.muted
        font.pixelSize: 12
        font.weight: Font.DemiBold
    }
    component Callout: Rectangle {
        property alias text: calloutText.text
        width: parent ? parent.width : 0
        height: calloutText.implicitHeight + 28
        radius: 12
        color: ui.theme.sunken
        Text {
            id: calloutText
            x: 16
            y: 14
            width: parent.width - 32
            color: ui.theme.text
            lineHeight: 1.3
            wrapMode: Text.WordWrap
        }
    }
    component Badge: Rectangle {
        property string tone: "bad"
        width: 44
        height: 44
        radius: 22
        color: tone === "ok" ? ui.theme.okBg : tone === "warn" ? ui.theme.warnBg : ui.theme.badBg
        Icon {
            anchors.centerIn: parent
            name: parent.tone === "ok" ? "check" : "alert"
            size: 22
            color: parent.tone === "ok" ? ui.theme.okText
                : parent.tone === "warn" ? ui.theme.warnText : ui.theme.badText
        }
    }

    Component {
        id: addForm
        Column {
            id: form
            spacing: 14
            property string provider: root.sheet.provider || ""
            function submit() { ui.submitAdd(form.provider, nameField.text) }
            Component.onCompleted: nameField.forceActiveFocus()

            Heading { text: "Add an account" }
            Body {
                color: ui.theme.muted
                text: "Shambles creates the account, then runs the provider's own sign-in in your browser. The account you are on now stays saved."
            }
            Label { text: "Provider" }
            Column {
                width: parent.width
                spacing: 8
                Repeater {
                    model: root.sheet.options || []
                    T.AbstractButton {
                        id: option
                        width: parent.width
                        implicitHeight: 58
                        enabled: modelData.enabled
                        focusPolicy: Qt.StrongFocus
                        checkable: true
                        checked: form.provider === modelData.id
                        opacity: enabled ? 1 : 0.6
                        Accessible.role: Accessible.RadioButton
                        Accessible.name: modelData.title + ". " + modelData.detail
                        onClicked: form.provider = modelData.id
                        Keys.onReturnPressed: clicked()
                        background: Rectangle {
                            radius: 12
                            color: option.enabled ? ui.theme.surface : ui.theme.sunken
                            border.color: option.checked ? ui.theme.accent
                                : option.visualFocus ? ui.theme.focus : ui.theme.border
                            border.width: option.checked || option.visualFocus ? 2 : 1
                        }
                        contentItem: Column {
                            leftPadding: 14
                            topPadding: 10
                            spacing: 2
                            Text {
                                text: modelData.title
                                color: ui.theme.text
                                font.weight: Font.DemiBold
                            }
                            Text {
                                text: modelData.detail
                                color: ui.theme.muted
                                font.pixelSize: 13
                            }
                        }
                    }
                }
            }
            Label { text: "Account name" }
            Field {
                id: nameField
                width: parent.width
                label: "Account name"
                placeholderText: "Work"
                text: root.sheet.name || ""
                onAccepted: form.submit()
            }
            Text {
                visible: text !== ""
                width: parent.width
                text: root.sheet.error || ""
                color: ui.theme.badText
                font.pixelSize: 13
                wrapMode: Text.WordWrap
            }
            Row {
                anchors.right: parent.right
                spacing: 10
                Btn { text: "Cancel"; onClicked: ui.dismiss() }
                Btn {
                    kind: "primary"
                    text: "Continue to sign-in"
                    enabled: !!root.sheet.canSubmit && form.provider !== ""
                    onClicked: form.submit()
                }
            }
        }
    }

    Component {
        id: loginView
        Column {
            spacing: 16
            Component.onCompleted: cancelButton.forceActiveFocus()

            Column {
                width: parent.width
                spacing: 4
                Heading { text: root.sheet.title || "" }
                Body { color: ui.theme.muted; text: root.sheet.subtitle || "" }
            }
            Column {
                width: parent.width
                spacing: 11
                Repeater {
                    model: root.sheet.steps || []
                    Row {
                        spacing: 12
                        Item {
                            width: 22
                            height: 22
                            Rectangle {
                                anchors.fill: parent
                                radius: 11
                                visible: modelData.state === "done"
                                color: ui.theme.okBg
                                Icon { anchors.centerIn: parent; name: "check"; size: 13; weight: 3; color: ui.theme.okText }
                            }
                            Rectangle {
                                anchors.fill: parent
                                radius: 11
                                visible: modelData.state !== "done"
                                color: "transparent"
                                border.width: modelData.state === "active" ? 3 : 2
                                border.color: modelData.state === "active" ? ui.theme.accentSoftBorder : ui.theme.faint
                            }
                            Item {
                                // A dot travelling the ring: progress with no
                                // claim about how much is left.
                                anchors.fill: parent
                                visible: modelData.state === "active"
                                Rectangle {
                                    width: 7
                                    height: 7
                                    radius: 3.5
                                    color: ui.theme.accent
                                    x: 7.5
                                    y: -2
                                }
                                RotationAnimation on rotation {
                                    running: modelData.state === "active" && ui.motion && root.visible
                                    from: 0
                                    to: 360
                                    duration: 1100
                                    loops: Animation.Infinite
                                }
                            }
                        }
                        Text {
                            text: modelData.text
                            color: modelData.state === "todo" ? ui.theme.muted : ui.theme.text
                            font.weight: modelData.state === "active" ? Font.DemiBold : Font.Normal
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                }
            }
            Callout { text: root.sheet.who || "" }
            Column {
                width: parent.width
                spacing: 10
                Body {
                    color: ui.theme.muted
                    font.pixelSize: 13
                    text: root.sheet.url
                        ? "Browser did not open? That is normal under WSL and over SSH."
                        : "Your browser should open by itself. If it cannot, a link appears here."
                }
                Row {
                    visible: !!root.sheet.url
                    spacing: 10
                    Btn {
                        kind: "primary"
                        glyph: "external"
                        text: "Open sign-in page"
                        onClicked: ui.openUrl()
                    }
                    Btn {
                        glyph: "copy"
                        text: root.sheet.copied ? "Copied" : "Copy link"
                        onClicked: ui.copyUrl()
                    }
                }
            }
            Rectangle { width: parent.width; height: 1; color: ui.theme.hairline }
            Item {
                width: parent.width
                height: Math.max(cancelButton.height, cancelNote.implicitHeight)
                Text {
                    id: cancelNote
                    width: parent.width - cancelButton.width - 16
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.sheet.cancelNote || ""
                    color: ui.theme.muted
                    font.pixelSize: 13
                    wrapMode: Text.WordWrap
                }
                Btn {
                    id: cancelButton
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    enabled: !root.sheet.cancelling
                    text: root.sheet.cancelling ? "Cancelling" : "Cancel"
                    onClicked: ui.cancelLogin()
                }
            }
        }
    }

    Component {
        id: resultView
        Column {
            spacing: 16
            Component.onCompleted: (root.sheet.retry ? retryButton : closeButton).forceActiveFocus()
            Row {
                width: parent.width
                spacing: 14
                Badge { tone: root.sheet.tone || "bad" }
                Heading {
                    width: parent.width - 58
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.sheet.title || ""
                }
            }
            Body { text: root.sheet.message || "" }
            Callout { visible: text !== ""; text: root.sheet.remedy || "" }
            Row {
                anchors.right: parent.right
                spacing: 10
                Btn { id: closeButton; text: "Close"; onClicked: ui.dismiss() }
                Btn {
                    id: retryButton
                    visible: !!root.sheet.retry
                    kind: "primary"
                    text: root.sheet.retryLabel || "Try again"
                    onClicked: ui.retry()
                }
            }
        }
    }

    Component {
        id: confirmView
        Column {
            spacing: 16
            // Cancel holds the focus, so Enter on a destructive question
            // answers no.
            Component.onCompleted: keepButton.forceActiveFocus()
            Heading { text: root.sheet.title || "" }
            Body { text: root.sheet.message || "" }
            Row {
                anchors.right: parent.right
                spacing: 10
                Btn { id: keepButton; text: "Cancel"; onClicked: ui.dismiss() }
                Btn {
                    kind: "danger"
                    text: root.sheet.confirmLabel || "Continue"
                    onClicked: ui.confirm()
                }
            }
        }
    }

    Component {
        id: renameForm
        Column {
            spacing: 14
            Component.onCompleted: {
                renameField.forceActiveFocus()
                renameField.selectAll()
            }
            Heading { text: root.sheet.title || "" }
            Label { text: "New name" }
            Field {
                id: renameField
                width: parent.width
                label: "New name"
                text: root.sheet.name || ""
                onAccepted: ui.submitRename(text)
            }
            Text {
                visible: text !== ""
                width: parent.width
                text: root.sheet.error || ""
                color: ui.theme.badText
                font.pixelSize: 13
                wrapMode: Text.WordWrap
            }
            Row {
                anchors.right: parent.right
                spacing: 10
                Btn { text: "Cancel"; onClicked: ui.dismiss() }
                Btn { kind: "primary"; text: "Rename"; onClicked: ui.submitRename(renameField.text) }
            }
        }
    }

    Component {
        id: noticeView
        Column {
            spacing: 16
            Component.onCompleted: okButton.forceActiveFocus()
            Row {
                width: parent.width
                spacing: 14
                Badge { tone: root.sheet.tone || "ok" }
                Heading {
                    width: parent.width - 58
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.sheet.title || ""
                }
            }
            Repeater {
                model: root.sheet.messages || []
                Body { text: modelData }
            }
            Btn {
                id: okButton
                anchors.right: parent.right
                kind: "primary"
                text: "OK"
                onClicked: ui.dismiss()
            }
        }
    }
}
