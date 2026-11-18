// A usage bar's track and fill. Solid for a current figure; striped for an
// old one on an account not in use, so age reads as a pattern rather than
// a paler grey that barely shows on the track (D12); hatched across the
// whole track for a limit that has reset since it was read.
import QtQuick

Item {
    id: root
    objectName: "barFill"
    property var limit: ({})
    readonly property bool reset: limit.state === "reset"
    readonly property bool old: limit.tone === "dim"
    readonly property string meaning: old ? (limit.severity || "") : (limit.tone || "")
    readonly property color ink: meaning === "gone" ? ui.theme.barGone
        : meaning === "soon" ? ui.theme.barSoon : ui.theme.barOk
    readonly property real fraction: reset ? 0 : (limit.fill || 0)
    clip: true

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: ui.theme.track
        visible: !root.reset
    }
    Item {
        id: filled
        height: parent.height
        width: Math.max(root.fraction > 0 ? Math.max(3, parent.height) : 0,
                        parent.width * root.fraction)
        clip: true
        Behavior on width {
            enabled: ui.motion
            NumberAnimation { duration: 420; easing.type: Easing.OutCubic }
        }
        Rectangle {
            anchors.fill: parent
            radius: height / 2
            color: root.ink
            visible: !root.old
        }
        Row {
            objectName: "oldStripes"
            visible: root.old
            spacing: 2
            Repeater {
                model: root.old ? Math.max(0, Math.ceil(filled.width / 5) + 1) : 0
                Rectangle { width: 3; height: root.height; color: root.ink }
            }
        }
    }
    Row {
        objectName: "resetHatch"
        visible: root.reset
        spacing: 3
        Repeater {
            model: root.reset ? Math.max(0, Math.ceil(root.width / 6) + 1) : 0
            Rectangle { width: 3; height: root.height; radius: 1; color: ui.theme.okDot; opacity: 0.6 }
        }
    }
}
