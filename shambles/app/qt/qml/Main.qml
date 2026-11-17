// The Shambles window: every provider, its live account, everyone else.
import QtQuick
import QtQuick.Controls.Basic

ApplicationWindow {
    id: win
    // Where it was left last time, unless no screen shows that any more.
    x: ui.place.x
    y: ui.place.y
    width: ui.place.width
    height: ui.place.height
    // Small enough to sit beside an editor. placement.MINIMUM says the same.
    minimumWidth: 420
    minimumHeight: 360
    visible: true
    title: "Shambles"
    color: ui.theme.ground

    // Rows drop their address line below this width.
    readonly property bool narrow: width < 520

    // Which account's details are open, and which card should pulse. Kept
    // here because the cards are rebuilt whenever the accounts are re-read.
    property string expandedId: ""
    property string pulseId: ""
    readonly property bool typing: activeFocusItem instanceof TextInput
    readonly property var groups: ui.view.groups || []
    // Keyed by provider, so working the window out again keeps each
    // section, and everything in it, rather than making it all again.
    readonly property var groupById: {
        var found = {}
        for (var i = 0; i < groups.length; i++)
            found[groups[i].provider] = groups[i]
        return found
    }
    onGroupsChanged: groupKeys.sync(groups.map(function (g) { return g.provider }))
    KeyedList { id: groupKeys }

    // Bring a control the keyboard just reached into the scrolled view. With
    // ``whole``, all of it where it fits (an account that was just opened),
    // and never at the cost of its top.
    function reveal(item, whole) {
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
        var last = Math.max(0, scroller.contentHeight - scroller.height)
        if (top < scroller.contentY + 8) {
            scroller.contentY = Math.max(0, top - (whole ? 8 : 60))
        } else if (bottom > scroller.contentY + scroller.height - 8) {
            var target = bottom - scroller.height + (whole ? 8 : 24)
            if (whole)
                target = Math.min(target, top - 8)
            scroller.contentY = Math.min(last, Math.max(0, target))
        }
    }

    // An opened account grows downwards, possibly below the footer, where
    // the click that opened it would seem to have done nothing. Wait for the
    // list to lay itself out, then bring all of it into view.
    property var revealTarget: null
    function revealSoon(item) {
        revealTarget = item
        revealTimer.restart()
    }
    Timer {
        id: revealTimer
        interval: 60
        onTriggered: {
            var item = win.revealTarget
            win.revealTarget = null
            if (item)
                win.reveal(item, true)
        }
    }

    // Where the window is, kept for the next time it opens. Read after the
    // window settles rather than on every step of a drag, and only its
    // ordinary size: maximised is kept as a flag on top of that.
    property rect normalPlace: Qt.rect(0, 0, 0, 0)
    function savePlace() {
        if (visibility === Window.Windowed)
            normalPlace = Qt.rect(x, y, width, height)
        else if (visibility !== Window.Maximized)
            return
        if (normalPlace.width <= 0)
            return
        ui.rememberPlace(normalPlace.x, normalPlace.y, normalPlace.width,
                         normalPlace.height, visibility === Window.Maximized)
    }
    Timer {
        id: placeTimer
        interval: 800
        onTriggered: win.savePlace()
    }
    onXChanged: placeTimer.restart()
    onYChanged: placeTimer.restart()
    onWidthChanged: placeTimer.restart()
    onHeightChanged: placeTimer.restart()
    onVisibilityChanged: placeTimer.restart()
    Component.onCompleted: {
        groupKeys.sync(groups.map(function (g) { return g.provider }))
        normalPlace = Qt.rect(ui.place.x, ui.place.y, ui.place.width, ui.place.height)
        if (ui.place.maximized)
            showMaximized()
    }

    Connections {
        target: ui
        function onConfirmed(id) {
            win.pulseId = ""
            win.pulseId = id
        }
        function onQuitRequested() {
            Qt.quit()
        }
    }

    // Never close under a switch: stopped between replacing the live login
    // and moving the marker, it is the one thing that could lose a login.
    // The bridge closes the window itself once the switch has finished.
    onClosing: (close) => {
        savePlace()
        if (!ui.closeRequested())
            close.accepted = false
    }

    // U2: coming back to the window re-reads files (never the Keychain).
    onActiveChanged: if (active) ui.windowFocused()

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
    // Ctrl+1 to Ctrl+9 (Command on macOS): the Nth account's button
    // (D8). Never a bare digit, which switched accounts at a stray key.
    Repeater {
        model: 9
        Item {
            Shortcut {
                sequence: "Ctrl+" + (index + 1)
                enabled: !ui.sheetOpen
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
            objectName: "header"
            z: 2
            width: parent.width
            height: 68
            color: ui.theme.ground

            WindowMover {
                // Everything in the header that is not a button or the
                // filter moves the window. Below them, so they keep their
                // own clicks.
                objectName: "dragArea"
                anchors.fill: parent
            }

            Text {
                id: wordmark
                x: 20
                anchors.verticalCenter: parent.verticalCenter
                text: "Shambles"
                color: ui.theme.text
                font.pixelSize: 16
                font.weight: Font.DemiBold
            }

            Text {
                // U2: "Updated just now". Its tooltip says what is re-read.
                id: updated
                anchors.left: wordmark.right
                anchors.leftMargin: 10
                anchors.baseline: wordmark.baseline
                visible: text !== "" && win.width > 560
                text: ui.updatedText
                color: ui.theme.muted
                font.pixelSize: 12
                HoverHandler { id: updatedHover }
                ToolTip.visible: updatedHover.hovered
                ToolTip.text: ui.updatedTip
                ToolTip.delay: 500
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
                    enabled: !ui.busy
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
                    objectName: "addButton"
                    kind: "primary"
                    glyph: "plus"
                    text: win.narrow ? "Add" : "Add account"
                    hint: "Add account"
                    enabled: !ui.busy
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

        Rectangle {
            // What just happened, and what is happening: under the header,
            // pushing the list down rather than covering its last row.
            // Opaque and above the list for the same reason as the header.
            id: messages
            objectName: "messages"
            z: 2
            anchors.top: header.bottom
            width: parent.width
            height: stack.height
            color: ui.theme.ground
            Column {
                id: stack
                x: 20
                width: parent.width - 40
                spacing: 8
                bottomPadding: busy.visible || toast.visible ? 12 : 0
                BusyBar { id: busy }
                Toast { id: toast }
            }
        }

        Flickable {
            id: scroller
            objectName: "scroller"
            anchors.top: messages.bottom
            anchors.bottom: footer.top
            width: parent.width
            contentWidth: width
            contentHeight: column.height + 24
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            // Always shown while there is more to scroll to, not only while
            // scrolling, so a list cut off by a short window says so.
            ScrollBar.vertical: ScrollBar {
                policy: scroller.contentHeight > scroller.height + 1
                        ? ScrollBar.AlwaysOn : ScrollBar.AlwaysOff
            }

            Column {
                id: column
                x: 20
                y: 4
                width: scroller.width - 40
                spacing: 24

                Repeater {
                    id: sections
                    model: groupKeys
                    GroupSection {
                        width: column.width
                        group: win.groupById[model.key] || ({})
                        visible: !group.hidden
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
            anchors.top: scroller.top
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
            Row {
                // What the window reads, said on hover (D1).
                x: 20
                anchors.verticalCenter: parent.verticalCenter
                spacing: 5
                Icon {
                    name: "lock"
                    size: 13
                    weight: 2
                    color: ui.theme.muted
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: "Local only"
                    color: ui.theme.muted
                    font.pixelSize: 12
                    anchors.verticalCenter: parent.verticalCenter
                }
                HoverHandler { id: localHover }
                Tip {
                    text: "Shambles reads what Claude Code and Codex keep on "
                          + "this computer. Switching accounts never goes online."
                    visible: localHover.hovered
                }
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

    Sheet {}
    // Above the sheet, so a window too small for one can still be made
    // bigger with it open.
    ResizeGrip { z: 10 }
}
