// The Shambles window: every provider, its live account, everyone else.
import QtQuick
import QtQuick.Controls.Basic

ApplicationWindow {
    id: win
    width: 760
    height: 720
    minimumWidth: 520
    minimumHeight: 420
    visible: true
    title: "Shambles"
    color: ui.theme.ground

    // Which account's details are open, and which card should pulse. Kept
    // here because the cards are rebuilt whenever the accounts are re-read.
    property string expandedId: ""
    property string pulseId: ""
    readonly property bool typing: activeFocusItem instanceof TextInput
    readonly property var groups: ui.view.groups || []

    // Bring a control the keyboard just reached into the scrolled view.
    function reveal(item) {
        if (!item)
            return
        // Only things inside the scrolled list; the header never scrolls.
        var probe = item
        while (probe && probe !== column)
            probe = probe.parent
        if (probe !== column)
            return
        var top = item.mapToItem(column, 0, 0).y + column.y
        var bottom = top + item.height
        if (top < scroller.contentY + 8)
            scroller.contentY = Math.max(0, top - 60)
        else if (bottom > scroller.contentY + scroller.height - 8)
            scroller.contentY = Math.min(Math.max(0, scroller.contentHeight - scroller.height),
                                         bottom - scroller.height + 24)
    }

    Connections {
        target: ui
        function onConfirmed(id) {
            win.pulseId = ""
            win.pulseId = id
        }
    }

    Shortcut { sequences: ["Ctrl+R", "F5"]; onActivated: ui.refresh() }
    Shortcut { sequence: "Ctrl+N"; enabled: !ui.sheetOpen; onActivated: ui.openAdd("") }
    Shortcut {
        sequence: "/"
        enabled: !ui.sheetOpen && !win.typing && !!ui.view.showFilter
        onActivated: filterField.forceActiveFocus()
    }
    Shortcut {
        sequence: "Escape"
        onActivated: {
            if (ui.sheetOpen)
                ui.dismiss()
            else if (ui.filter !== "") {
                filterField.text = ""
                ui.setFilter("")
            }
        }
    }
    Repeater {
        model: 9
        Item {
            Shortcut {
                sequence: String(index + 1)
                enabled: !ui.sheetOpen && !win.typing
                onActivated: ui.pressKey(String(index + 1))
            }
        }
    }

    Item {
        id: chrome
        anchors.fill: parent
        // With a sheet up, Tab must stay inside it.
        enabled: !ui.sheetOpen

        Rectangle {
            // Opaque, and above the list: the software renderer does not
            // clip drawn shapes to the scrolled area, so anything scrolled
            // under the header has to be covered by it.
            id: header
            z: 2
            width: parent.width
            height: 68
            color: ui.theme.ground

            Text {
                id: wordmark
                x: 20
                anchors.verticalCenter: parent.verticalCenter
                text: "Shambles"
                color: ui.theme.text
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }

            Row {
                id: tools
                anchors.right: parent.right
                anchors.rightMargin: 20
                anchors.verticalCenter: parent.verticalCenter
                spacing: 10
                Btn {
                    glyph: "refresh"
                    hint: "Refresh. Re-reads local files only."
                    implicitHeight: 40
                    onClicked: ui.refresh()
                }
                Btn {
                    id: moreButton
                    glyph: "more"
                    hint: "Theme and more"
                    implicitHeight: 40
                    onClicked: mainMenu.open()
                    MenuPop {
                        id: mainMenu
                        x: moreButton.width - width
                        y: moreButton.height + 6
                        items: [
                            {"label": "Theme: follow system", "action": "system", "checked": ui.themeChoice === "system"},
                            {"label": "Theme: light", "action": "light", "checked": ui.themeChoice === "light"},
                            {"label": "Theme: dark", "action": "dark", "checked": ui.themeChoice === "dark"},
                            {"label": "Eject Shambles", "action": "eject", "danger": true}
                        ]
                        onPicked: (action) => {
                            if (action === "eject")
                                ui.askEject()
                            else
                                ui.setTheme(action)
                        }
                    }
                }
                Btn {
                    kind: "primary"
                    glyph: "plus"
                    text: "Add account"
                    implicitHeight: 40
                    onClicked: ui.openAdd("")
                }
            }

            Field {
                id: filterField
                visible: !!ui.view.showFilter
                anchors.left: wordmark.right
                anchors.leftMargin: 20
                anchors.right: tools.left
                anchors.rightMargin: 20
                anchors.verticalCenter: parent.verticalCenter
                label: "Filter accounts"
                placeholderText: "Filter " + (ui.view.count || 0) + " accounts  ( / )"
                onTextChanged: ui.setFilter(text)
            }
        }

        Flickable {
            id: scroller
            objectName: "scroller"
            anchors.top: header.bottom
            anchors.bottom: footer.top
            width: parent.width
            contentWidth: width
            contentHeight: column.height + 24
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

            Column {
                id: column
                x: 20
                y: 4
                width: scroller.width - 40
                spacing: 24

                Repeater {
                    id: sections
                    model: win.groups
                    GroupSection {
                        width: column.width
                        group: modelData
                        visible: !modelData.hidden
                    }
                }

                Text {
                    visible: !!ui.view.filtering && (ui.view.matches || 0) === 0
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    topPadding: 40
                    text: "No account matches “" + ui.filter + "”. Press Esc to clear the filter."
                    color: ui.theme.muted
                    wrapMode: Text.WordWrap
                }
            }
        }

        Rectangle {
            // The heading of whichever provider is scrolled under the top
            // edge, so a long list never loses track of whose accounts
            // these are.
            id: pinned
            readonly property var current: {
                var y = scroller.contentY
                for (var i = sections.count - 1; i >= 0; i--) {
                    var item = sections.itemAt(i)
                    if (item && item.visible && item.y + column.y + 26 <= y)
                        return win.groups[i]
                }
                return null
            }
            visible: current !== null
            z: 2
            anchors.top: header.bottom
            width: parent.width
            height: 34
            color: ui.theme.ground
            Text {
                x: 20
                anchors.verticalCenter: parent.verticalCenter
                text: pinned.current ? pinned.current.title : ""
                color: ui.theme.text
                font.pixelSize: 13
                font.weight: Font.DemiBold
            }
            Text {
                anchors.right: parent.right
                anchors.rightMargin: 20
                anchors.verticalCenter: parent.verticalCenter
                text: pinned.current ? pinned.current.summary : ""
                color: ui.theme.muted
                font.pixelSize: 12
            }
            Rectangle { anchors.bottom: parent.bottom; width: parent.width; height: 1; color: ui.theme.hairline }
        }

        Rectangle {
            id: footer
            z: 2
            anchors.bottom: parent.bottom
            width: parent.width
            height: 38
            color: ui.theme.ground
            Text {
                x: 20
                anchors.verticalCenter: parent.verticalCenter
                text: "Reads local files only, never the network."
                color: ui.theme.muted
                font.pixelSize: 12
            }
            Text {
                anchors.right: parent.right
                anchors.rightMargin: 20
                anchors.verticalCenter: parent.verticalCenter
                text: "Shambles " + ui.version
                color: ui.theme.muted
                font.pixelSize: 12
            }
        }
    }

    Toast {}
    Sheet {}
}
