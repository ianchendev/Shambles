"""Drawn widgets.

Tk frame reliefs are square and there is no border-radius, so a rounded card
has to be a smoothed polygon on a Canvas with its content placed on top. The
geometry is a pure function and is tested without a display; the widgets
themselves need one.
"""

import time

import pytest

from shambles import widgets


# ---- rounded rectangle geometry -----------------------------------------

def _pairs(flat):
    return list(zip(flat[0::2], flat[1::2]))


def test_each_rounded_corner_is_sampled_as_a_real_arc():
    """Explicit arcs rather than Tk's own ``-smooth``.

    A smoothed polygon runs a single spline through every point, so the
    straight runs bow by a pixel or two -- which renders as visible steps
    along the bottom edge of a card. Sampling the corners and leaving the
    edges as straight segments draws what was actually asked for.
    """
    got = _pairs(widgets.rounded_rect_points(0, 0, 200, 80, 10))
    near_nw = [p for p in got if p[0] <= 10 and p[1] <= 10]
    assert len(near_nw) > 3, "the corner is a chamfer, not an arc"
    for x, y in near_nw:
        radius = ((x - 10) ** 2 + (y - 10) ** 2) ** 0.5
        assert radius == pytest.approx(10, abs=0.01), (x, y)


def test_the_corner_arcs_meet_the_edges_exactly():
    """Each arc has to start and end on the straight edge it joins, or the
    outline shows a notch where the two meet."""
    got = _pairs(widgets.rounded_rect_points(0, 0, 200, 80, 10))
    assert (0, 10) in [(round(x, 6), round(y, 6)) for x, y in got]
    assert (10, 0) in [(round(x, 6), round(y, 6)) for x, y in got]
    assert (200, 70) in [(round(x, 6), round(y, 6)) for x, y in got]


def test_every_point_stays_inside_the_rectangle():
    got = widgets.rounded_rect_points(10, 20, 110, 60, 9)
    for x, y in _pairs(got):
        assert 10 <= x <= 110, x
        assert 20 <= y <= 60, y


def test_a_zero_radius_collapses_to_the_four_corners():
    got = set(_pairs(widgets.rounded_rect_points(0, 0, 50, 30, 0)))
    assert got == {(0, 0), (50, 0), (50, 30), (0, 30)}


def test_an_oversized_radius_is_clamped_to_half_the_shorter_side():
    """A 9px radius on a 10px-tall spine would otherwise invert the curve."""
    got = widgets.rounded_rect_points(0, 0, 200, 10, 40)
    for _x, y in _pairs(got):
        assert 0 <= y <= 10, y
    xs = [x for x, _y in _pairs(got)]
    assert max(xs) == 200 and min(xs) == 0


def test_a_square_corner_is_a_single_point():
    """One shape can mix rounded and square corners: a corner left out of
    ``corners`` contributes its own point and nothing else."""
    got = _pairs(widgets.rounded_rect_points(0, 0, 60, 20, 6, corners=("ne", "se")))
    assert got.count((0, 0)) == 1, "north-west should be a single square corner"
    assert got.count((0, 20)) == 1, "south-west should be a single square corner"


def test_a_rounded_corner_never_reaches_the_corner_point():
    """An arc passes inside the corner; touching it would be a square one."""
    got = _pairs(widgets.rounded_rect_points(0, 0, 60, 20, 6, corners=("ne", "se")))
    assert (60, 0) not in got, "north-east touched the corner, so it is square"


def test_selecting_no_corners_gives_a_plain_rectangle():
    got = set(_pairs(widgets.rounded_rect_points(0, 0, 50, 30, 9, corners=())))
    assert got == {(0, 0), (50, 0), (50, 30), (0, 30)}


def test_a_degenerate_rectangle_still_returns_drawable_points():
    """A card is drawn before Tk has laid it out, when its width is 1."""
    got = widgets.rounded_rect_points(0, 0, 1, 1, 9)
    assert len(got) >= 8
    for x, y in _pairs(got):
        assert 0 <= x <= 1 and 0 <= y <= 1


def test_a_negative_radius_is_treated_as_square():
    got = set(_pairs(widgets.rounded_rect_points(0, 0, 40, 40, -5)))
    assert got == {(0, 0), (40, 0), (40, 40), (0, 40)}


# ---- the widgets ---------------------------------------------------------

@pytest.fixture
def root():
    """A mapped Tk root -- deliberately not withdrawn.

    A withdrawn window is never laid out, so a card's content never fires the
    ``<Configure>`` its height tracking hangs off, and Tk delivers no crossing
    events to it at all. Both would pass or fail for reasons that have nothing
    to do with the widget. The rest of the suite maps its windows too; CI runs
    the lot under xvfb.
    """
    tk = pytest.importorskip("tkinter")
    try:
        made = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    made.geometry("360x240")
    yield made
    made.destroy()


@pytest.fixture
def palette(root):
    from shambles.theme import Theme
    return Theme(root)


def _card(root, theme, **kw):
    opts = dict(fill=theme["card"], edge=theme["border"],
                spine=theme["border"], hover=theme["card_hover"],
                shadow=theme["shadow"])
    opts.update(kw)
    made = widgets.Card(root, **opts)
    made.pack(fill="x")
    return made


def test_a_card_grows_to_fit_its_content(root, palette):
    import tkinter as tk

    card = _card(root, palette)
    tk.Label(card.body, text="one line", bg=palette["card"]).pack()
    root.update()
    short = card.winfo_reqheight()

    for _ in range(4):
        tk.Label(card.body, text="another", bg=palette["card"]).pack()
    root.update()

    assert card.winfo_reqheight() > short, "the card did not follow its content"


def test_the_content_is_inset_so_the_rounded_corners_survive(root, palette):
    """A canvas window item is an opaque rectangle drawn over the canvas.

    Placed flush with the card edge it covers the very corners the polygon
    just rounded, and the card renders perfectly square however carefully it
    was drawn -- which is exactly what happened the first time.
    """
    import tkinter as tk

    card = _card(root, palette)
    tk.Label(card.body, text="Personal", bg=palette["card"]).pack()
    root.update()

    x, y = card.coords(card.content)
    assert y >= widgets.CARD_RADIUS / 2, (
        f"content starts {y}px down; the top corners are covered")
    assert x - widgets.ACCENT_BAR_WIDTH >= widgets.CARD_RADIUS / 2, (
        f"content starts {x}px in; the left corners are covered")

    # ...and the card must still be tall enough to hold it plus both insets.
    assert card.winfo_reqheight() >= card.body.winfo_reqheight() + 2 * y


def test_the_card_face_is_rounded_on_every_corner(root, palette):
    """Rounding only the outer spine leaves the white face poking square
    through it at the left, which reads as a square card with a stripe."""
    import tkinter as tk

    card = _card(root, palette, spine=palette["accent"])
    # Real content, or the card stays 1px tall, the radius clamps to nothing
    # and the assertion below passes without touching a rounded corner.
    for _ in range(3):
        tk.Label(card.body, text="Personal", bg=palette["card"]).pack()
    root.update()

    face = list(zip(*[iter(card.coords(card.surface))] * 2))
    assert len(face) > 8, "the face was never drawn at a real size"

    x1 = min(x for x, _y in face)
    y1 = min(y for _x, y in face)
    # A square corner would put a point exactly on the bounding-box corner.
    assert (x1, y1) not in face, "the top-left of the card face is still square"


def test_the_right_edge_is_drawn_inside_the_canvas(root, palette):
    """Tk rounds a half-pixel coordinate upward when it rasterises.

    An outline at ``width - 0.5`` therefore lands on column ``width``, which
    is one past the last pixel the canvas owns -- so it is silently clipped
    and the card renders with three sides. The top and left survive because
    rounding 0.5 upward moves them *into* the canvas.
    """
    import tkinter as tk

    card = _card(root, palette)
    for _ in range(3):
        tk.Label(card.body, text="Personal", bg=palette["card"]).pack()
    root.update()

    width = card.winfo_width()
    for name, item in (("surface", card.surface), ("spine", card.spine)):
        right = max(card.coords(item)[0::2])
        assert right <= width - 1, (
            f"{name} right edge at {right} on a {width}px canvas -- clipped")


def test_the_card_polygons_are_not_smoothed(root, palette):
    """Tk's own smoothing bows the straight runs, which shows up as steps
    along the bottom edge of a card. The corners carry their own arcs."""
    card = _card(root, palette)
    root.update()
    for item in (card.surface, card.spine):
        assert card.itemcget(item, "smooth") == "0"


def test_a_card_draws_its_surface_and_its_spine(root, palette):
    card = _card(root, palette, spine=palette["accent"])
    root.update()

    fills = {card.itemcget(item, "fill") for item in card.find_all()
             if card.type(item) == "polygon"}
    assert palette["accent"] in fills, "no spine drawn"
    assert palette["card"] in fills, "no card surface drawn"


def test_an_active_card_spine_uses_the_accent(root, palette):
    card = _card(root, palette, spine=palette["border_active"])
    root.update()
    assert card.itemcget(card.spine, "fill") == palette["border_active"]


def test_hovering_a_card_washes_its_surface(root, palette, monkeypatch):
    """Motion off so the end state is reached at once -- the tweening itself
    is covered in test_motion."""
    import tkinter as tk

    from shambles import motion
    monkeypatch.setenv(motion.MOTION_ENV, "off")

    card = _card(root, palette)
    tk.Label(card.body, text="Personal", bg=palette["card"]).pack()
    card.watch_pointer()
    root.update()

    card.event_generate("<Enter>")
    root.update()
    assert card.itemcget(card.surface, "fill") == palette["card_hover"]


def test_leaving_a_card_restores_its_resting_colour(root, palette, monkeypatch):
    import tkinter as tk

    from shambles import motion
    monkeypatch.setenv(motion.MOTION_ENV, "off")

    card = _card(root, palette)
    tk.Label(card.body, text="Personal", bg=palette["card"]).pack()
    card.watch_pointer()
    root.update()

    card.event_generate("<Enter>")
    root.update()
    card.event_generate("<Leave>", x=-40, y=-40)
    root.update()

    assert card.itemcget(card.surface, "fill") == palette["card"]


def test_a_wash_repaints_the_labels_sharing_the_card_colour(root, palette,
                                                            monkeypatch):
    """Every label on a card sets its own bg -- Tk has no inheritance -- so a
    surface that washes alone leaves white rectangles behind the text."""
    import tkinter as tk

    from shambles import motion
    monkeypatch.setenv(motion.MOTION_ENV, "off")

    card = _card(root, palette)
    name = tk.Label(card.body, text="Personal", bg=palette["card"])
    name.pack()
    card.watch_pointer()
    root.update()

    card.event_generate("<Enter>")
    root.update()
    assert name.cget("bg") == palette["card_hover"]


def test_a_wash_leaves_a_chip_its_own_colour(root, palette, monkeypatch):
    """A chip carries meaning in its background; washing it would erase the
    difference between 'closing soon' and 'fine'."""
    import tkinter as tk

    from shambles import motion
    monkeypatch.setenv(motion.MOTION_ENV, "off")

    card = _card(root, palette)
    chip = tk.Label(card.body, text="4d", bg=palette["chip_soon_bg"])
    chip.pack()
    card.watch_pointer()
    root.update()

    card.event_generate("<Enter>")
    root.update()
    assert chip.cget("bg") == palette["chip_soon_bg"]


def test_a_card_arriving_under_the_pointer_keeps_its_hover(root, palette):
    """After a switch the pointer is usually still sitting over the card that
    was just rebuilt.

    The entry fade finishes by washing to the resting colour, so unless it
    checks, it wipes out the hover state the card is already in and the row
    under the cursor goes flat until you move the mouse.
    """
    import tkinter as tk

    card = _card(root, palette)
    tk.Label(card.body, text="Personal", bg=palette["card"]).pack()
    card.watch_pointer()
    root.update()

    card.appear(palette["window"], delay_ms=40)
    card.event_generate("<Enter>")

    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
        if card.itemcget(card.surface, "fill") == palette["card_hover"]:
            break

    assert card.itemcget(card.surface, "fill") == palette["card_hover"], (
        "the entry fade washed the hover away")


def test_a_card_can_pulse_its_spine(root, palette, monkeypatch):
    """The switch confirmation. It must end on the resting colour, or the
    card is left mid-flash."""
    from shambles import motion
    monkeypatch.setenv(motion.MOTION_ENV, "off")

    card = _card(root, palette, spine=palette["border_active"])
    root.update()
    card.pulse(palette["accent_hover"])
    root.update()

    assert card.itemcget(card.spine, "fill") == palette["border_active"]


# ---- the pill chip -------------------------------------------------------

def test_a_pill_renders_its_text(root, palette):
    pill = widgets.Pill(root, text="4d", font=palette.chip,
                        fg=palette["chip_soon_fg"], bg=palette["chip_soon_bg"],
                        behind=palette["card"])
    pill.pack()
    root.update()

    drawn = [pill.itemcget(i, "text") for i in pill.find_all()
             if pill.type(i) == "text"]
    assert drawn == ["4d"]


def test_a_pill_is_wider_than_its_text(root, palette):
    """Padding is what makes it read as a chip rather than as loose words."""
    pill = widgets.Pill(root, text="expired 12d ago", font=palette.chip,
                        fg=palette["chip_gone_fg"], bg=palette["chip_gone_bg"],
                        behind=palette["card"])
    pill.pack()
    root.update()

    assert pill.winfo_reqwidth() > palette.chip.measure("expired 12d ago")


def test_a_pill_is_fully_rounded(root, palette):
    """Half its height, so the ends are semicircles at any type size."""
    pill = widgets.Pill(root, text="4d", font=palette.chip,
                        fg=palette["chip_soon_fg"], bg=palette["chip_soon_bg"],
                        behind=palette["card"])
    pill.pack()
    root.update()

    assert pill.radius == pytest.approx(pill.winfo_reqheight() / 2, abs=1)
