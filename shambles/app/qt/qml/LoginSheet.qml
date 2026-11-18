// The sheet shown while the vendor's own sign-in runs.
import QtQuick

Pane {
    rule: true
    Component.onCompleted: cancelButton.forceActiveFocus()

    Column {
        width: parent.width
        spacing: 4
        SheetHeading { text: ui.sheet.title || "" }
        SheetText { color: ui.theme.muted; text: ui.sheet.subtitle || "" }
    }
    Column {
        width: parent.width
        spacing: 11
        Repeater {
            model: ui.sheet.steps || []
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
                            running: modelData.state === "active" && ui.motion && ui.sheetOpen
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
    SheetCallout { text: ui.sheet.who || "" }
    Column {
        width: parent.width
        spacing: 10
        SheetText {
            color: ui.theme.muted
            font.pixelSize: 13
            text: ui.sheet.url
                ? "Browser did not open? That is normal under WSL and over SSH."
                : "Your browser should open by itself. If it cannot, a link appears here."
        }
        Row {
            visible: !!ui.sheet.url
            spacing: 10
            Btn {
                kind: "primary"
                glyph: "external"
                text: "Open sign-in page"
                onClicked: ui.openUrl()
            }
            Btn {
                glyph: "copy"
                text: ui.sheet.copied ? "Copied" : "Copy link"
                onClicked: ui.copyUrl()
            }
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
