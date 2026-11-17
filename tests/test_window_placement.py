"""Where the window opens: the stored place, unless no screen can show it.

Pure arithmetic on rectangles, so it runs on every CI job, Qt or not.
"""

from shambles.app.qt import placement

LAPTOP = (0, 0, 1920, 1040)
#: A second monitor to the right of the first.
RIGHT = (1920, 0, 2560, 1400)


def stored(x, y, width=700, height=600, maximized=False):
    return {"x": x, "y": y, "width": width, "height": height,
            "maximized": maximized}


def test_with_nothing_stored_it_opens_at_the_default_size_centred():
    place = placement.opening_place(None, [LAPTOP], LAPTOP)

    assert place == {"x": (1920 - 760) // 2, "y": (1040 - 720) // 2,
                     "width": 760, "height": 720, "maximized": False}


def test_a_stored_place_on_a_screen_is_used_as_it_is():
    place = placement.opening_place(stored(2100, 150, maximized=True),
                                    [LAPTOP, RIGHT], LAPTOP)

    assert place == stored(2100, 150, maximized=True)


def test_a_place_on_a_monitor_that_is_gone_resets_to_the_centre():
    """The second monitor was unplugged since the window was last closed
    there. Opening off every screen would look like Shambles never started."""
    place = placement.opening_place(stored(2100, 150), [LAPTOP], LAPTOP)

    assert (place["x"], place["y"]) == ((1920 - 700) // 2, (1040 - 600) // 2)
    assert (place["width"], place["height"]) == (700, 600)


def test_a_window_partly_off_screen_is_kept_while_its_header_can_be_grabbed():
    assert placement.opening_place(stored(-500, 300), [LAPTOP],
                                   LAPTOP)["x"] == -500
    assert placement.opening_place(stored(1800, 300), [LAPTOP],
                                   LAPTOP)["x"] == 1800


def test_a_window_whose_header_cannot_be_reached_is_centred():
    """Only the header moves the window, so a place where the header is off
    every screen is as good as lost, however much of the rest shows."""
    for x, y in ((-650, 300), (1860, 300), (300, -60), (300, 1030)):
        place = placement.opening_place(stored(x, y), [LAPTOP], LAPTOP)
        assert (place["x"], place["y"]) == ((1920 - 700) // 2,
                                            (1040 - 600) // 2), (x, y)


def test_a_stored_size_is_never_smaller_than_the_window_allows():
    place = placement.opening_place(stored(100, 100, 200, 100), [LAPTOP],
                                    LAPTOP)

    assert (place["width"], place["height"]) == placement.MINIMUM


def test_a_stored_size_larger_than_its_screen_is_cut_to_fit():
    """From a bigger monitor to a laptop: the window fits on what is left."""
    place = placement.opening_place(stored(0, 0, 2400, 1300), [LAPTOP],
                                    LAPTOP)

    assert (place["width"], place["height"]) == (1920, 1040)


def test_with_no_screen_reported_it_still_opens_somewhere_sensible():
    place = placement.opening_place(stored(5000, 5000), [], None)

    assert (place["width"], place["height"]) == (700, 600)
    assert (place["x"], place["y"]) == (0, 0)


def test_the_minimum_is_what_the_layout_was_drawn_for():
    """D5: small enough to sit beside an editor; the window's QML sets the
    same numbers, and tests/qt/test_qt_frame.py holds it to them."""
    assert placement.MINIMUM == (420, 360)
    assert placement.DEFAULT == (760, 720)
