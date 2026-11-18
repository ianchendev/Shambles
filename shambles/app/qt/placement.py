"""Where the window opens: where it was left, unless no screen shows it.

No Qt in here, so the rule is tested on every CI job. Rectangles are
``(x, y, width, height)`` tuples in the toolkit's own units; the bridge turns
Qt's screens into them.
"""

#: What the window opens at with nothing stored.
DEFAULT = (760, 720)
#: The smallest the layout is drawn for (D5). Main.qml says the same.
MINIMUM = (420, 360)
#: The header is what moves the window, so a stored place counts only if
#: some screen shows enough of it to grab: this much of the top strip.
HEADER_PX = 68
REACH = (120, 32)
#: Where to centre when the platform reports no screen at all.
NO_SCREEN = (0, 0, 0, 0)


def _overlap(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    width = min(ax + aw, bx + bw) - max(ax, bx)
    height = min(ay + ah, by + bh) - max(ay, by)
    return max(0, width), max(0, height)


def _reachable(x, y, width, screens):
    header = (x, y, width, HEADER_PX)
    for screen in screens:
        across, down = _overlap(header, screen)
        if across >= REACH[0] and down >= REACH[1]:
            return screen
    return None


def _fit(width, height, screen):
    """At least the minimum; no larger than the screen, where there is one."""
    _sx, _sy, sw, sh = screen
    if sw > 0:
        width = min(width, sw)
    if sh > 0:
        height = min(height, sh)
    return max(width, MINIMUM[0]), max(height, MINIMUM[1])


def opening_place(stored, screens, primary) -> dict:
    """``{"x", "y", "width", "height", "maximized"}`` to open the window at.

    ``stored`` is :func:`shambles.settings.window_place`'s answer (or None),
    ``screens`` every screen's available area, ``primary`` the primary's.
    """
    width, height = DEFAULT
    maximized = False
    if stored is not None:
        width, height = stored["width"], stored["height"]
        maximized = bool(stored.get("maximized"))
        screen = _reachable(stored["x"], stored["y"], width, screens)
        if screen is not None:
            width, height = _fit(width, height, screen)
            return {"x": stored["x"], "y": stored["y"], "width": width,
                    "height": height, "maximized": maximized}
    # Nothing stored, or a monitor that has gone since: the centre of the
    # primary screen, which is where most window managers would put it.
    screen = primary or (screens[0] if screens else NO_SCREEN)
    width, height = _fit(width, height, screen)
    sx, sy, sw, sh = screen
    x = sx + max(0, (sw - width) // 2)
    y = sy + max(0, (sh - height) // 2)
    return {"x": x, "y": y, "width": width, "height": height,
            "maximized": maximized}
