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
