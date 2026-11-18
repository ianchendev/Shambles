// An i that explains the thing beside it, on hover or on keyboard focus.
// Clicking it keeps the explanation open, for anyone who cannot hover.
import QtQuick
import QtQuick.Templates as T

T.AbstractButton {
    id: control
    property string tip: ""
    property color tint: ui.theme.muted
    implicitWidth: 18
    implicitHeight: 18
    focusPolicy: Qt.StrongFocus
    hoverEnabled: true
    checkable: true
    Accessible.role: Accessible.Button
    Accessible.name: tip
    onActiveFocusChanged: if (!activeFocus) checked = false

    contentItem: Item {
        Icon {
            anchors.centerIn: parent
            name: "info"
            size: 16
            weight: 1.8
            color: control.tint
        }
    }
    background: Item {
        FocusRing { radius: 9; shown: control.visualFocus }
    }
    Tip {
        objectName: "infoTip"
        text: control.tip
        visible: control.tip !== ""
                 && (control.hovered || control.visualFocus || control.checked)
    }
}
