// One stroked icon, drawn from a path so it takes the theme's colour.
// An image file would need one copy per colour; a font would need a font.
//
// A Canvas, not a Shape: the software renderer, which is what the window
// uses under WSL, does not clip a Shape to a scrolled area, so icons in rows
// scrolled under the header were drawn on top of it.
import QtQuick

Canvas {
    id: root
    property string name: ""
    property color color: ui.theme.text
    property real size: 18
    property real weight: 2
    implicitWidth: size
    implicitHeight: size
    width: size
    height: size
    antialiasing: true

    readonly property var paths: ({
        "refresh": "M20 11a8 8 0 1 0-2.3 5.7 M20 4v7h-7",
        "plus": "M12 5v14 M5 12h14",
        "check": "M5 12.5l4.5 4.5L19 7.5",
        "alert": "M12 4l9 16H3z M12 10v4 M12 17v.5",
        "info": "M21 12a9 9 0 1 1-18 0a9 9 0 0 1 18 0z M12 8v5 M12 16.5v.5",
        "external": "M14 5h5v5 M19 5l-8 8 M11 7H6v11h11v-5",
        "copy": "M11 9h7a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-7a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2z M5 15V6a2 2 0 0 1 2-2h8",
        "chevron": "M6 9l6 6 6-6",
        "search": "M18 11a7 7 0 1 1-14 0a7 7 0 0 1 14 0z M20 20l-3.5-3.5",
        "user": "M16 8a4 4 0 1 1-8 0a4 4 0 0 1 8 0z M4 21a8 8 0 0 1 16 0",
        "close": "M6 6l12 12 M18 6L6 18",
        "more": "M5 12h.01 M12 12h.01 M19 12h.01"
    })

    onNameChanged: requestPaint()
    onColorChanged: requestPaint()
    onSizeChanged: requestPaint()
    onWeightChanged: requestPaint()

    onPaint: {
        var ctx = getContext("2d")
        ctx.reset()
        ctx.scale(size / 24, size / 24)
        ctx.lineWidth = name === "more" ? 3.2 : weight
        ctx.lineCap = "round"
        ctx.lineJoin = "round"
        ctx.strokeStyle = color
        ctx.path = paths[name] || ""
        ctx.stroke()
    }
}
