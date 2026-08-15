"""Widgets Tk does not have: a rounded card and a pill chip.

There is no border-radius anywhere in the toolkit and frame reliefs are all
square, so anything with a curve has to be drawn. Both widgets here are a
Canvas that paints its own background as a polygon with sampled corner arcs.
The card then places an ordinary Frame on top through ``create_window``, so
Labels and ttk Buttons keep working inside it exactly as they did in the flat
version -- inset from the edge, because a window item is opaque and would
otherwise cover the corners it just went to the trouble of rounding.

The other thing Tk will not do is composite, which shapes two details: the
"shadow" is an opaque rectangle offset behind the card rather than anything
soft, and a hover "fade" is a colour blend rather than an opacity change.
"""

import math
import tkinter as tk

from . import motion
from .theme import ACCENT_BAR_WIDTH

#: Card corner radius. Large enough to read as deliberate at the current type
#: scale, small enough that the accent spine still looks like a bar.
CARD_RADIUS = 9

#: How far the fake shadow sits below the card, in pixels. Also the extra
#: height a card claims beyond its content.
SHADOW_DROP = 2

#: How far the content sits inside the card edge.
#:
#: Load-bearing, not cosmetic. A canvas window item is an opaque rectangle
#: painted over the canvas: flush with the edge it covers the very corners the
#: polygon rounded, and the card renders square no matter how carefully it was
#: drawn. Two thirds of the radius leaves the whole curve visible.
BODY_INSET = 6

#: Hover wash. Short: it confirms the pointer is somewhere, and anything
#: slower reads as the window lagging rather than as an effect.
HOVER_MS = 120

#: Card entry. refresh() rebuilds the whole list on every action, so this one
#: runs constantly and has to stay out of the way.
APPEAR_MS = 180

#: The switch confirmation, out and back. The one long animation in the app,
#: because it is the one moment worth drawing the eye to.
PULSE_MS = 850

#: Fraction of the pulse spent travelling to the flash colour. The rest is
#: the slower settle back, which is what makes it read as a pulse rather
#: than as a flicker.
PULSE_ATTACK = 0.25

PILL_PAD_X = 9
PILL_PAD_Y = 2

#: Sampled points per corner arc. Past eight another point is not
#: visible at a 9px radius, and the count matters -- every card
#: redraws all three of its polygons on each resize.
CORNER_STEPS = 8

#: Half-pixel offset that puts a 1px outline on a whole pixel rather than
#: straddling two.
EDGE = 0.5

#: The right edge needs a *whole* pixel of margin, not a half.
#:
#: Tk rounds a coordinate upward when it rasterises, so an outline at
#: ``width - 0.5`` lands on column ``width`` -- one past the last pixel the
#: canvas owns. It is silently clipped and the card renders with three sides.
#: The top and left get away with 0.5 because rounding up moves them *into*
#: the canvas.
RIGHT_EDGE = 1.5

CORNERS_ALL = ("nw", "ne", "se", "sw")


def rounded_rect_points(x1, y1, x2, y2, radius, corners=CORNERS_ALL):
    """Points for a rounded rectangle, to be drawn **unsmoothed**.

    Not Tk's ``-smooth``. That runs a single spline through every point, so
    the straight runs between the corners bow by a pixel or two -- on a card
    it shows as visible steps along the bottom edge, which is worse than
    having no radius at all. Sampling each corner as a real arc and leaving
    the edges as straight segments costs a few dozen coordinates and draws
    exactly the shape that was asked for.

    A corner not named in ``corners`` contributes its own point alone and
    stays sharp, so one shape can mix rounded and square corners.

    The radius is clamped to half the shorter side, so a 9px radius on a 10px
    spine curves rather than inverting.
    """
    span = min((x2 - x1) / 2, (y2 - y1) / 2)
    r = max(0.0, min(float(radius), span))
    wanted = set(corners)

    # Centre and sweep of each corner arc, clockwise in canvas coordinates
    # (y grows downward), starting where the left edge meets the top-left.
    arcs = (
        ("nw", x1 + r, y1 + r, 180, 270, (x1, y1)),
        ("ne", x2 - r, y1 + r, 270, 360, (x2, y1)),
        ("se", x2 - r, y2 - r, 0, 90, (x2, y2)),
        ("sw", x1 + r, y2 - r, 90, 180, (x1, y2)),
    )

    points = []
    for name, cx, cy, start, end, sharp in arcs:
        if r <= 0 or name not in wanted:
            points.extend(sharp)
            continue
        for step in range(CORNER_STEPS + 1):
            angle = math.radians(start + (end - start) * step / CORNER_STEPS)
            points.extend((cx + r * math.cos(angle), cy + r * math.sin(angle)))
    return points


class Card(tk.Canvas):
    """A rounded card with an accent spine down its left edge.

    Three stacked polygons: a shadow, then the spine as a full rounded
    rectangle, then the card face over it, inset from the left by the spine's
    width and rounded at the same radius. The sliver of spine left showing is
    the accent bar; because both outlines share a radius the two stay
    parallel, so the bar keeps an even width all the way round the corner.

    Height tracks the content, which is not optional -- a card is taller when
    it drew usage bars than when it drew a chip, and the scroll region has to
    know.
    """

    def __init__(self, parent, *, fill, edge, spine, hover, shadow, pad=0,
                 radius=CARD_RADIUS, spine_width=ACCENT_BAR_WIDTH):
        super().__init__(parent, highlightthickness=0, bd=0,
                         bg=parent.cget("bg"))
        self._fill = fill
        self._hover = hover
        self._radius = radius
        self._spine_width = spine_width
        self._resting_spine = spine
        #: Total padding between the card edge and its content. Part of it is
        #: spent insetting the window item off the corners; the body carries
        #: whatever is left, so the visible gap is `pad` either way.
        self._inset = min(BODY_INSET, pad) if pad else BODY_INSET

        #: What the face is painted right now. Tracked rather than read back
        #: from the canvas: a wash interrupted mid-blend has to hand over
        #: from the shade it reached, and cget would return that shade only
        #: by luck.
        self._shade = fill
        self._wash = None
        self._pulse = None
        self._painted = ()
        #: Whether the pointer is over the card, per the crossing events we
        #: have actually been delivered.
        self._inside = False
        self._drawn = None
        self._height = SHADOW_DROP + 1

        blank = (0, 0, 0, 0, 0, 0)
        self._shadow = self.create_polygon(blank, fill=shadow, outline="")
        self.spine = self.create_polygon(blank, fill=spine, outline="")
        self.surface = self.create_polygon(blank, fill=fill, outline=edge)

        rest = max(0, pad - self._inset)
        self.body = tk.Frame(self, bg=fill, padx=rest, pady=rest)
        self.content = self.create_window(spine_width + self._inset,
                                          self._inset, window=self.body,
                                          anchor="nw")

        self.body.bind("<Configure>", self._follow_content)
        self.bind("<Configure>", lambda _e: self._paint())

    # -- geometry ---------------------------------------------------------

    def _follow_content(self, _event=None):
        wanted = (max(1, self.body.winfo_reqheight())
                  + 2 * self._inset + SHADOW_DROP)
        if wanted == self._height:
            return
        self._height = wanted
        self.configure(height=wanted)
        self._paint()

    def _paint(self):
        """Redraw the three shapes at the current size.

        Width comes from the realised widget because the card fills its row;
        height comes from the content, because asking Tk for a height it has
        not applied yet returns the previous one and the card lags a frame
        behind its own contents.
        """
        width = self.winfo_width()
        if width <= 1:
            return
        if self._drawn == (width, self._height):
            return
        self._drawn = (width, self._height)

        face = self._height - SHADOW_DROP
        r = self._radius

        self.coords(self._shadow, *rounded_rect_points(
            1, SHADOW_DROP, width - 1, face + SHADOW_DROP, r))
        self.coords(self.spine, *rounded_rect_points(
            EDGE, EDGE, width - RIGHT_EDGE, face - EDGE, r))
        # Rounded on every corner, including the two that meet the spine.
        # Squaring those made the white face poke out through the spine's
        # curve, which read as a square card with a stripe down it. Rounded
        # at the same radius, the two outlines stay parallel and the spine
        # is an even band that follows the corner.
        self.coords(self.surface, *rounded_rect_points(
            self._spine_width, EDGE, width - RIGHT_EDGE, face - EDGE, r))
        self.itemconfigure(
            self.content,
            width=max(1, width - self._spine_width - 2 * self._inset))

    # -- reacting to the pointer -------------------------------------------

    def watch_pointer(self):
        """Start washing on hover. Call once the content is fully built.

        Both halves of this need the finished tree. The crossing bindings
        have to reach every descendant, because Tk delivers ``<Leave>`` to a
        parent when the pointer merely moves into one of its own children --
        a card watching only itself would flicker as the pointer crossed a
        label. And the repaint list is decided by colour: a widget already
        sharing the card's background is part of the surface and washes with
        it, while a chip carrying its own meaning-bearing background is left
        alone.
        """
        self._painted = (self.body,) + tuple(self._sharing_our_colour(self.body))
        self._bind_crossing(self)

    def _sharing_our_colour(self, widget):
        for child in widget.winfo_children():
            try:
                if child.cget("bg") == self._fill:
                    yield child
            except tk.TclError:
                pass  # a ttk widget has no -bg to read
            yield from self._sharing_our_colour(child)

    def _bind_crossing(self, widget):
        widget.bind("<Enter>", self._entered, add="+")
        widget.bind("<Leave>", self._left, add="+")
        for child in widget.winfo_children():
            self._bind_crossing(child)

    def _entered(self, _event=None):
        self._inside = True
        self._wash_to(self._hover)

    def _left(self, event):
        if self._holds(self._under(event)):
            return  # into one of our own children, which is not leaving
        self._inside = False
        self._wash_to(self._fill)

    def _settled(self):
        """The colour this card belongs at right now.

        Consulted at the end of the entry fade rather than assumed, because
        after a switch the pointer is usually still sitting over the card that
        was just rebuilt. Two ways to be under it, and both have to count: an
        ``<Enter>`` may have been delivered since the fade started, or the
        pointer may never have moved at all -- in which case no crossing event
        is coming, since the crossing happened before this card existed.
        """
        if self._inside or self._pointer_is_over():
            return self._hover
        return self._fill

    def _pointer_is_over(self) -> bool:
        try:
            return self._holds(self.winfo_containing(
                self.winfo_pointerx(), self.winfo_pointery()))
        except tk.TclError:
            return False

    def _under(self, event):
        try:
            return self.winfo_containing(event.x_root, event.y_root)
        except (tk.TclError, AttributeError):
            return None

    def _holds(self, widget) -> bool:
        while widget is not None:
            if widget is self:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _wash_to(self, target, duration_ms=HOVER_MS):
        if self._shade == target:
            return
        if self._wash is not None:
            self._wash.cancel()
        start = self._shade
        self._wash = motion.animate(
            self, duration_ms,
            lambda p: self._repaint(motion.lerp_hex(start, target, p)))

    def _repaint(self, shade):
        self._shade = shade
        try:
            self.itemconfigure(self.surface, fill=shade)
        except tk.TclError:
            return  # the card went away mid-wash
        for widget in self._painted:
            try:
                widget.configure(bg=shade)
            except tk.TclError:
                pass  # destroyed between frames

    # -- arriving -----------------------------------------------------------

    def appear(self, ground, delay_ms=0):
        """Fade the card up from the colour of the window behind it.

        ``refresh()`` destroys and rebuilds every row on every switch, rename
        and remove, which without this reads as a flicker. Staggered across
        the list, the identical work reads as the list assembling itself.
        """
        if not motion.wants_motion():
            return
        self._repaint(ground)
        if delay_ms <= 0:
            self._wash_to(self._settled(), APPEAR_MS)
            return
        self.after(delay_ms, lambda: self._wash_to(self._settled(), APPEAR_MS))

    # -- the switch confirmation -------------------------------------------

    def pulse(self, flash):
        """Flash the spine and settle back to its resting colour.

        Switching is the one thing this window exists to do and today it
        reports success by silently redrawing the list. This puts the eye on
        the row that changed.
        """
        if self._pulse is not None:
            self._pulse.cancel()
        resting = self._resting_spine

        def paint(p):
            if p < PULSE_ATTACK:
                shade = motion.lerp_hex(resting, flash, p / PULSE_ATTACK)
            else:
                shade = motion.lerp_hex(flash, resting,
                                        (p - PULSE_ATTACK) / (1 - PULSE_ATTACK))
            self.itemconfigure(self.spine, fill=shade)

        # Linear: the out-and-back shape is in `paint`, and easing it as well
        # would compress the attack into a frame or two.
        self._pulse = motion.animate(self, PULSE_MS, paint, ease=lambda t: t)


class Pill(tk.Canvas):
    """A fully rounded chip.

    Same content as the Label it replaces -- text on a coloured ground -- but
    the ground is drawn, so it can be a capsule. ``behind`` is the colour of
    whatever the chip sits on, which is what shows through its corners.
    """

    def __init__(self, parent, *, text, font, fg, bg, behind,
                 pad_x=PILL_PAD_X, pad_y=PILL_PAD_Y):
        width = font.measure(text) + 2 * pad_x
        height = font.metrics("linespace") + 2 * pad_y
        super().__init__(parent, width=width, height=height,
                         highlightthickness=0, bd=0, bg=behind)

        #: Half the height, so the ends stay semicircular at any type size.
        self.radius = height / 2
        self.create_polygon(
            rounded_rect_points(0, 0, width, height, self.radius),
            fill=bg, outline="")
        self.create_text(width / 2, height / 2, text=text, font=font, fill=fg)
