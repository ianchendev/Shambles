// A single-line text field in the window's style.
import QtQuick
import QtQuick.Templates as T

T.TextField {
    id: control
    property string label: ""
    implicitHeight: 36
    implicitWidth: 220
    leftPadding: 12
    rightPadding: 12
    verticalAlignment: TextInput.AlignVCenter
    color: ui.theme.text
    selectionColor: ui.theme.accent
    selectedTextColor: ui.theme.onAccent
    placeholderTextColor: ui.theme.muted
    font.pixelSize: 14
    selectByMouse: true
    Accessible.name: label

    Text {
        // Templates give a placeholder property but draw nothing for it.
        anchors.fill: parent
        anchors.leftMargin: control.leftPadding
        verticalAlignment: Text.AlignVCenter
        text: control.placeholderText
        color: control.placeholderTextColor
        font: control.font
        visible: control.text === "" && control.preeditText === ""
        elide: Text.ElideRight
    }

    background: Rectangle {
        radius: 10
        color: ui.theme.surface
        border.color: ui.theme.border
        border.width: 1
        // A text field shows where the caret is on any focus, not only
        // keyboard focus: typing goes there either way.
        FocusRing { radius: 10; shown: control.activeFocus }
    }
}
