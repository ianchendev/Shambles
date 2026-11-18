"""The two colour schemes agree with each other, and text stays readable."""

import pytest

from shambles.app.qt import theme


def luminance(colour: str) -> float:
    def channel(value):
        value /= 255
        return value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4

    red, green, blue = (int(colour[i:i + 2], 16) for i in (1, 3, 5))
    return (0.2126 * channel(red) + 0.7152 * channel(green)
            + 0.0722 * channel(blue))


def contrast(a: str, b: str) -> float:
    lighter, darker = sorted((luminance(a), luminance(b)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_both_schemes_define_exactly_the_same_colours():
    """A key missing from one scheme draws as nothing in that scheme only."""
    assert set(theme.LIGHT) == set(theme.DARK)


#: Text colour, then the surface it is drawn on.
PAIRS = [
    ("text", "ground"), ("text", "surface"), ("text", "sunken"),
    ("text", "sheet"), ("muted", "ground"), ("muted", "surface"),
    ("muted", "sunken"), ("muted", "sheet"), ("accentText", "accentSoft"),
    ("onAccent", "accent"), ("onAccent", "accentHover"),
    ("okText", "okBg"), ("warnText", "warnBg"), ("badText", "badBg"),
    ("badText", "surface"), ("text", "warnSurface"), ("muted", "warnSurface"),
    ("text", "badSurface"), ("text", "infoSurface"), ("onToast", "toast"),
    ("accentText", "liveAvatar"), ("avatarText", "avatar"),
]


@pytest.mark.parametrize("scheme", ["LIGHT", "DARK"])
@pytest.mark.parametrize("ink,paper", PAIRS)
def test_text_meets_4_5_to_1_on_what_it_sits_on(scheme, ink, paper):
    colours = getattr(theme, scheme)
    ratio = contrast(colours[ink], colours[paper])
    assert ratio >= 4.5, f"{ink} on {paper} in {scheme} is {ratio:.2f}:1"


def test_an_unknown_system_scheme_reads_as_light():
    assert theme.is_dark("system", None) is False
    assert theme.is_dark("system", True) is True
    assert theme.is_dark("light", True) is False
    assert theme.is_dark("dark", False) is True


#: D12: an outline that marks where a control or card ends, then what it is
#: drawn against. 3:1 is the usual floor for parts of a control.
OUTLINES = [
    ("border", "ground"), ("border", "surface"), ("border", "sheet"),
    ("accentSoftBorder", "surface"), ("accentSoftBorder", "accentSoft"),
    ("accentSoftBorder", "ground"), ("badBorder", "sheet"),
    ("badBorder", "badSurface"), ("warnBorder", "warnSurface"),
    ("warnBorder", "ground"), ("focus", "ground"), ("focus", "surface"),
    ("focus", "sheet"), ("focus", "focusGap"),
]


@pytest.mark.parametrize("scheme", ["LIGHT", "DARK"])
@pytest.mark.parametrize("line,paper", OUTLINES)
def test_outlines_meet_3_to_1_on_what_they_sit_on(scheme, line, paper):
    colours = getattr(theme, scheme)
    ratio = contrast(colours[line], colours[paper])
    assert ratio >= 3.0, f"{line} on {paper} in {scheme} is {ratio:.2f}:1"


@pytest.mark.parametrize("scheme", ["LIGHT", "DARK"])
def test_the_focus_ring_is_not_the_blue_of_buttons_and_the_live_card(scheme):
    """D12: where the keyboard is must not look like a button, a selection
    or the live card."""
    colours = getattr(theme, scheme)
    taken = {colours[key] for key in ("accent", "accentHover", "accentText",
                                      "liveBorder", "accentSoftBorder")}

    assert colours["focus"] not in taken
