// The round mark beside a sheet's title: a tick, or a warning.
import QtQuick

Rectangle {
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
