// The add-account form: which provider, and a name.
import QtQuick
import QtQuick.Templates as T

Pane {
    id: form
    spacing: 14
    property string provider: ui.sheet.provider || ""
    function submit() { ui.submitAdd(form.provider, nameField.text) }
    Component.onCompleted: nameField.forceActiveFocus()

    SheetHeading { text: "Add an account" }
    SheetText {
        color: ui.theme.muted
        text: "Shambles creates the account, then runs the provider's own sign-in in your browser. The account you are on now stays saved."
    }
    SheetLabel { text: "Provider" }
    Column {
        width: parent.width
        spacing: 8
        Repeater {
            model: ui.sheet.options || []
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
    SheetLabel { text: "Account name" }
    Field {
        id: nameField
        width: parent.width
        label: "Account name"
        placeholderText: "Work"
        text: ui.sheet.name || ""
        onAccepted: form.submit()
    }
    Text {
        visible: text !== ""
        width: parent.width
        text: ui.sheet.error || ""
        color: ui.theme.badText
        font.pixelSize: 13
        wrapMode: Text.WordWrap
    }
    footer: Row {
        anchors.right: parent.right
        spacing: 10
        Btn { text: "Cancel"; onClicked: ui.dismiss() }
        Btn {
            kind: "primary"
            text: "Continue to sign-in"
            enabled: !!ui.sheet.canSubmit && form.provider !== ""
            onClicked: form.submit()
        }
    }
}
