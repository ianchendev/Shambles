"""Sizing decisions, kept as pure functions so they can be checked without a
display.

The reference point is that 16px is the widely accepted minimum for body text
(WCAG sets no minimum but requires 200% resize; 16px is the practical floor
every modern guideline lands on). Tk sizes fonts in points and converts with
the `tk scaling` factor, so 12pt only reaches 16px when scaling is at least
1.333.
"""

import pytest

from shambles import theme


def test_body_text_meets_the_sixteen_pixel_floor():
    px = theme.SIZE_BODY * theme.BASE_SCALING
    assert px >= 16, f"body renders {px:.1f}px, under the 16px minimum"


def test_the_type_scale_keeps_its_hierarchy():
    sizes = [theme.SIZE_CAPTION, theme.SIZE_CHIP, theme.SIZE_BODY,
             theme.SIZE_NAME, theme.SIZE_TITLE]
    assert sizes == sorted(sizes), "type scale is not monotonic"
    assert len(set(sizes)) == len(sizes), "two steps collapsed to one size"


def test_secondary_text_stays_legible():
    """Captions and chips may sit under the body floor, but not far under."""
    for size in (theme.SIZE_CHIP, theme.SIZE_CAPTION):
        assert size * theme.BASE_SCALING >= 13, f"{size}pt is too small"


# ---- choosing a scaling factor ------------------------------------------

def test_a_wide_panel_reporting_96dpi_is_scaled_up():
    """WSLg and many Linux setups report a flat 96 dpi whatever the panel. A
    3840px framebuffer at 96 dpi means the report is wrong, not that the
    display is coarse."""
    assert theme.scaling_for(current=1.333, screen_width=3840) > 1.333


def test_a_normal_panel_keeps_the_base_factor():
    assert theme.scaling_for(current=1.333, screen_width=1920) == theme.BASE_SCALING


def test_an_already_scaled_desktop_is_left_alone():
    """A desktop that already applies fractional scaling reports a higher
    factor; raising it again would double-scale."""
    assert theme.scaling_for(current=2.0, screen_width=3840) == 2.0


def test_an_explicit_override_wins():
    assert theme.scaling_for(current=1.333, screen_width=1920,
                             override="1.8") == 1.8


def test_a_junk_override_is_ignored_rather_than_crashing():
    for junk in ("", "big", "-1", "0", "99"):
        got = theme.scaling_for(current=1.333, screen_width=1920, override=junk)
        assert theme.BASE_SCALING <= got <= 4.0, junk


def test_the_window_is_wide_enough_for_the_larger_type():
    assert theme.WINDOW_WIDTH >= 640


# ---- eliding text that would stretch a fixed-width window ---------------

class _FakeFont:
    """8px per character, so expectations are arithmetic rather than fonts."""
    def measure(self, text):
        return len(text) * 8


def test_text_that_fits_is_returned_unchanged():
    assert theme.elide("short", _FakeFont(), 400) == "short"


def test_text_that_does_not_fit_is_cut_with_an_ellipsis():
    got = theme.elide("A" * 100, _FakeFont(), 160)
    assert got.endswith("…")
    assert len(got) * 8 <= 160


def test_eliding_never_returns_more_than_it_was_given():
    long = "B" * 200
    assert len(theme.elide(long, _FakeFont(), 80)) < len(long)


def test_a_hopeless_width_still_returns_something_renderable():
    got = theme.elide("something", _FakeFont(), 4)
    assert got and len(got) <= 2


def test_empty_text_is_safe():
    assert theme.elide("", _FakeFont(), 100) == ""


# ---- picking glyphs the font can actually draw ---------------------------

class _PartialFont:
    """Renders everything except the codepoints in ``missing``.

    Missing glyphs measure the same as Tk's fallback box, which is how a
    missing glyph is detectable at all.
    """
    TOFU = 7

    def __init__(self, missing=()):
        self.missing = set(missing)

    def measure(self, text):
        if text == theme.MISSING_PROBE or text in self.missing:
            return self.TOFU
        return 4 + len(text)


def test_the_first_drawable_candidate_wins():
    font = _PartialFont(missing={"ⓘ"})
    assert theme.glyph(font, "ⓘ", "ℹ", fallback="i") == "ℹ"


def test_a_font_with_everything_keeps_the_preferred_glyph():
    assert theme.glyph(_PartialFont(), "ⓘ", "ℹ", fallback="i") == "ⓘ"


def test_the_ascii_fallback_is_used_when_nothing_renders():
    font = _PartialFont(missing={"ⓘ", "ℹ"})
    assert theme.glyph(font, "ⓘ", "ℹ", fallback="i") == "i"


def test_the_fallback_is_never_itself_a_box():
    """Whatever comes back has to be drawable, or the fix achieves nothing."""
    font = _PartialFont(missing={"ⓘ", "ℹ"})
    got = theme.glyph(font, "ⓘ", "ℹ", fallback="i")
    assert font.measure(got) != _PartialFont.TOFU


def test_no_candidates_still_returns_the_fallback():
    assert theme.glyph(_PartialFont(), fallback="i") == "i"


def test_a_font_that_raises_does_not_break_the_window():
    class Hostile:
        def measure(self, text):
            raise RuntimeError("no font here")
    assert theme.glyph(Hostile(), "ⓘ", fallback="i") == "i"


def test_the_probe_is_a_single_codepoint():
    """A two-character probe measures the width of two glyphs and can never
    equal a single missing glyph, so detection silently never fires."""
    assert len(theme.MISSING_PROBE) == 1


def test_detection_works_against_a_real_font(): 
    """End to end, with the font actually in use rather than a stub."""
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.withdraw()
    try:
        font = theme.Theme(root).chip
        # U+24D8 is absent from several common UI fonts; whatever comes back
        # must at least not be the box.
        chosen = theme.glyph(font, "ⓘ", "ℹ", fallback="i")
        assert font.measure(chosen) != font.measure(theme.MISSING_PROBE)
    finally:
        root.destroy()
