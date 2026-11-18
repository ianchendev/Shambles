// A sheet's one piece of advice, set apart on a tinted panel.
import QtQuick

Rectangle {
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
