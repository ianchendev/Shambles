// A sheet's layout: what it says, which scrolls when the window is too
// short for it, and its buttons, which never scroll out of reach (F7).
import QtQuick
import QtQuick.Controls.Basic as C

Item {
    id: pane
    default property alias body: bodyColumn.data
    property alias footer: footerSlot.data
    property alias spacing: bodyColumn.spacing
    // A rule above the buttons even when nothing scrolls.
    property bool rule: false
    // From the height the sheet wants against the height it was given, not
    // from the scrolling area: the rule drawn when it scrolls takes room
    // from that area, and measured there a sheet that scrolled once, while
    // its text was still being laid out, kept scrolling for good.
    readonly property bool scrolls: implicitHeight > height + 1
    readonly property int gap: 16
    implicitHeight: bodyColumn.implicitHeight + gap + footerSlot.height
                    + (rule ? gap + 1 : 0)

    Flickable {
        id: scroll
        objectName: "sheetBody"
        // Wider and taller than the text by a few pixels, so focus
        // rings, drawn outside their control, are not cut off; and wide
        // enough on the right to hold the scroll bar clear of the text.
        x: -4
        width: pane.width + 18
        anchors.top: parent.top
        anchors.topMargin: -4
        anchors.bottom: divider.top
        anchors.bottomMargin: pane.gap - 4
        contentWidth: width
        contentHeight: bodyColumn.implicitHeight + 8
        clip: true
        boundsBehavior: Flickable.StopAtBounds
        C.ScrollBar.vertical: C.ScrollBar {
            objectName: "sheetScrollBar"
            policy: pane.scrolls ? C.ScrollBar.AlwaysOn : C.ScrollBar.AlwaysOff
        }
        Column {
            id: bodyColumn
            x: 4
            y: 4
            width: pane.width
            spacing: 16
        }
    }
    Rectangle {
        // Says there is a bottom to the text above when it scrolls.
        id: divider
        anchors.bottom: footerSlot.top
        anchors.bottomMargin: pane.rule || pane.scrolls ? pane.gap : 0
        width: pane.width
        height: pane.rule || pane.scrolls ? 1 : 0
        color: ui.theme.hairline
    }
    Item {
        id: footerSlot
        objectName: "sheetFooter"
        anchors.bottom: parent.bottom
        width: pane.width
        height: childrenRect.height
    }

    // Tab into the text of a scrolled sheet brings what it reached into
    // view, the way the list does.
    Connections {
        target: pane.Window.window
        function onActiveFocusItemChanged() {
            var item = pane.Window.window ? pane.Window.window.activeFocusItem : null
            var probe = item
            while (probe && probe !== bodyColumn)
                probe = probe.parent
            if (!item || probe !== bodyColumn)
                return
            // Only where the keyboard took it. The focus a sheet gives its
            // first field as it opens would otherwise open it scrolled past
            // its own title.
            var reason = item.focusReason
            if (reason !== undefined && reason !== Qt.TabFocusReason
                    && reason !== Qt.BacktabFocusReason)
                return
            var top = item.mapToItem(bodyColumn, 0, 0).y
            var bottom = top + item.height
            if (top < scroll.contentY)
                scroll.contentY = Math.max(0, top - 4)
            else if (bottom + 8 > scroll.contentY + scroll.height)
                scroll.contentY = Math.min(scroll.contentHeight - scroll.height,
                                           bottom + 8 - scroll.height)
        }
    }
}
