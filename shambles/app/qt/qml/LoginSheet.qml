// The sheet shown while the vendor's own sign-in runs.
//
// D7: a labelled progress line instead of four sentences, each sentence on
// hover. S1: a field for the code Claude's page shows when the browser
// cannot reach this machine. S2: for Codex, "Another device", which shows a
// one-time code to enter elsewhere. Everything it says comes from the
// presenter; this file only lays it out.
import QtQuick
import QtQuick.Templates as T

Pane {
    id: sheet
    rule: true
    readonly property bool device: ui.sheet.method === "device"
    readonly property var methods: ui.sheet.methods || []
    readonly property var code: ui.sheet.device || ({})
    Component.onCompleted: cancelButton.forceActiveFocus()

    Column {
        width: parent.width
        spacing: 4
        SheetHeading { text: ui.sheet.title || "" }
        SheetText { color: ui.theme.muted; text: ui.sheet.subtitle || "" }
    }

    // S2: this browser or another device. Only where both exist.
    Rectangle {
        objectName: "methodChoice"
        visible: sheet.methods.length > 0
        width: parent.width
        height: visible ? 36 : 0
        radius: 10
        color: ui.theme.sunken
        Row {
            anchors.fill: parent
            anchors.margins: 3
            Repeater {
                model: sheet.methods
                T.AbstractButton {
                    id: choice
                    width: (parent.width) / Math.max(1, sheet.methods.length)
                    height: parent.height
                    checkable: true
                    checked: ui.sheet.method === modelData.id
                    enabled: !ui.sheet.restarting && !ui.sheet.cancelling
                    focusPolicy: Qt.StrongFocus
                    hoverEnabled: true
                    Accessible.role: Accessible.RadioButton
                    Accessible.name: modelData.label
                    onClicked: ui.chooseMethod(modelData.id)
                    Keys.onReturnPressed: clicked()
                    background: Rectangle {
                        radius: 8
                        color: choice.checked ? ui.theme.surface : "transparent"
                        FocusRing { radius: 8; shown: choice.visualFocus }
                    }
                    contentItem: Text {
                        text: modelData.label
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        color: choice.checked ? ui.theme.text : ui.theme.muted
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                        opacity: choice.enabled ? 1 : 0.6
                    }
                }
            }
        }
    }

    // D7: the progress line. The full sentence for each step is its tip.
    // Not on the device sheet, which has the code to show instead (S2).
    Flow {
        id: progress
        objectName: "progressLine"
        visible: !sheet.device
        // Narrow, the joining lines go so the four steps stay on one line.
        readonly property bool narrow: width < 400
        width: parent.width
        spacing: narrow ? 12 : 8
        Repeater {
            model: ui.sheet.steps || []
            Row {
                id: step
                spacing: 6
                Accessible.role: Accessible.StaticText
                Accessible.name: modelData.label + ". " + modelData.tip
                HoverHandler { id: stepHover }
                Tip {
                    text: modelData.tip
                    visible: stepHover.hovered
                }
                Rectangle {
                    // The line joining this step to the one before.
                    visible: index > 0 && !progress.narrow
                    width: 14
                    height: 2
                    radius: 1
                    color: modelData.state === "todo" ? ui.theme.faint : ui.theme.okText
                    opacity: modelData.state === "todo" ? 1 : 0.5
                    anchors.verticalCenter: parent.verticalCenter
                }
                Item {
                    width: 18
                    height: 18
                    anchors.verticalCenter: parent.verticalCenter
                    Rectangle {
                        anchors.fill: parent
                        radius: 9
                        visible: modelData.state === "done"
                        color: ui.theme.okBg
                        Icon { anchors.centerIn: parent; name: "check"; size: 11; weight: 3; color: ui.theme.okText }
                    }
                    Rectangle {
                        anchors.fill: parent
                        radius: 9
                        visible: modelData.state !== "done"
                        color: "transparent"
                        border.width: modelData.state === "active" ? 3 : 2
                        border.color: modelData.state === "active" ? ui.theme.accentSoftBorder : ui.theme.faint
                    }
                    Item {
                        // A dot travelling the ring: progress with no claim
                        // about how much is left.
                        anchors.fill: parent
                        visible: modelData.state === "active"
                        Rectangle {
                            width: 6
                            height: 6
                            radius: 3
                            color: ui.theme.accent
                            x: 6
                            y: -2
                        }
                        RotationAnimation on rotation {
                            running: modelData.state === "active" && ui.motion && ui.sheetOpen
                            from: 0
                            to: 360
                            duration: 1100
                            loops: Animation.Infinite
                        }
                    }
                }
                Text {
                    text: modelData.label
                    color: modelData.state === "todo" ? ui.theme.muted : ui.theme.text
                    font.pixelSize: 13
                    font.weight: modelData.state === "active" ? Font.DemiBold : Font.Normal
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }

    // This browser: the link when it did not open, and the code field.
    Column {
        visible: !sheet.device
        width: parent.width
        spacing: 10
        TipText {
            // The i follows the sentence's last line, as on every sheet.
            text: ui.sheet.linkHint || ""
            tip: ui.sheet.url ? (ui.sheet.linkTip || "") : ""
            color: ui.theme.muted
            font.pixelSize: 13
        }
        Rectangle {
            objectName: "signInLink"
            visible: !!ui.sheet.url
            width: parent.width
            height: visible ? 48 : 0
            radius: 10
            color: ui.theme.sunken
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 12
                anchors.right: linkButtons.left
                anchors.rightMargin: 10
                anchors.verticalCenter: parent.verticalCenter
                text: ui.sheet.url || ""
                color: ui.theme.text
                font.pixelSize: 13
                elide: Text.ElideRight
            }
            Row {
                id: linkButtons
                anchors.right: parent.right
                anchors.rightMargin: 6
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                Btn {
                    kind: "soft"
                    text: ui.sheet.copied ? "Copied" : "Copy"
                    tip: "Copy the sign-in link"
                    onClicked: ui.copyUrl()
                }
                Btn {
                    text: "Open"
                    tip: "Open the sign-in link in your browser. It is copied too."
                    onClicked: ui.openUrl()
                }
            }
        }

        // S1: the code Claude's page shows when the browser cannot reach
        // this machine. Masked, as Claude Code's own prompt masks it.
        Row {
            objectName: "codeRow"
            visible: !!ui.sheet.acceptsCode
            width: parent.width
            spacing: 8
            Field {
                id: codeField
                objectName: "codeField"
                width: parent.width - continueButton.width - codeInfo.width - 16
                label: "Code from the browser page"
                placeholderText: "Paste the code from the browser page"
                echoMode: TextInput.Password
                enabled: !ui.sheet.codeSent
                onAccepted: continueButton.clicked()
            }
            Btn {
                id: continueButton
                kind: "primary"
                text: "Continue"
                enabled: codeField.text !== "" && !ui.sheet.codeSent
                onClicked: {
                    ui.submitCode(codeField.text)
                    // The window keeps no copy of it, sent or not.
                    codeField.text = ""
                }
            }
            Info {
                id: codeInfo
                tip: ui.sheet.codeTip || ""
                anchors.verticalCenter: parent.verticalCenter
            }
        }
        Text {
            visible: !!ui.sheet.acceptsCode && (ui.sheet.codeSent || ui.sheet.codeError !== "")
            width: parent.width
            text: ui.sheet.codeSent ? "Code sent." : (ui.sheet.codeError || "")
            color: ui.sheet.codeSent ? ui.theme.muted : ui.theme.badText
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }
    }

    // S2: another device. The code, large enough to read across a room.
    Column {
        visible: sheet.device
        width: parent.width
        spacing: 10
        TipText {
            text: ui.sheet.deviceHint || ""
            tip: ui.sheet.deviceTip || ""
            font.pixelSize: 13
        }
        TextEdit {
            objectName: "deviceCode"
            visible: !!sheet.code.code
            readOnly: true
            selectByMouse: true
            text: sheet.code.code || ""
            color: ui.theme.text
            font.pixelSize: 30
            font.weight: Font.DemiBold
            font.letterSpacing: 3
            Accessible.role: Accessible.StaticText
            Accessible.name: "One-time code " + (sheet.code.code || "")
        }
        Flow {
            visible: !!sheet.code.code
            width: parent.width
            spacing: 8
            Btn {
                kind: "primary"
                glyph: "copy"
                text: ui.sheet.codeCopied ? "Copied" : "Copy code"
                onClicked: ui.copyCode()
            }
            Btn {
                text: ui.sheet.copied ? "Copied" : "Copy link"
                onClicked: ui.copyUrl()
            }
            Text {
                // As tall as the buttons beside it (D9: 36 on sheets).
                height: 36
                verticalAlignment: Text.AlignVCenter
                text: ui.sheet.expiresIn || ""
                color: ui.sheet.expiresIn === "expired" ? ui.theme.badText : ui.theme.muted
                font.pixelSize: 13
            }
        }
        TextEdit {
            // The link spelled out, for typing on a phone.
            visible: !!sheet.code.url
            width: parent.width
            readOnly: true
            selectByMouse: true
            text: sheet.code.url || ""
            color: ui.theme.muted
            font.pixelSize: 13
            wrapMode: TextEdit.WrapAnywhere
        }
    }

    footer: Item {
        width: parent.width
        height: Math.max(cancelButton.height, cancelNote.implicitHeight)
        Text {
            id: cancelNote
            width: parent.width - cancelButton.width - 16
            anchors.verticalCenter: parent.verticalCenter
            text: ui.sheet.cancelNote || ""
            color: ui.theme.muted
            font.pixelSize: 13
            wrapMode: Text.WordWrap
        }
        Btn {
            id: cancelButton
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            enabled: !ui.sheet.cancelling
            text: ui.sheet.cancelling ? "Cancelling" : "Cancel"
            onClicked: ui.cancelLogin()
        }
    }
}
