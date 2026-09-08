"""Responsive terminal branding stays legible at every supported width."""

import pytest
from rich.cells import cell_len

from shambles.app.tui.brand import (
    BrandVariant,
    brand_text,
    header_kind,
    header_text,
    lockup_text,
    variant_for,
)


README_WORDMARK = (
    "███████╗██╗  ██╗ █████╗ ███╗   ███╗██████╗ ██╗     ███████╗███████╗",
    "██╔════╝██║  ██║██╔══██╗████╗ ████║██╔══██╗██║     ██╔════╝██╔════╝",
    "███████╗███████║███████║██╔████╔██║██████╔╝██║     █████╗  ███████╗",
    "╚════██║██╔══██║██╔══██║██║╚██╔╝██║██╔══██╗██║     ██╔══╝  ╚════██║",
    "███████║██║  ██║██║  ██║██║ ╚═╝ ██║██████╔╝███████╗███████╗███████║",
    "╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═════╝ ╚══════╝╚══════╝╚══════╝",
)


@pytest.mark.parametrize(
    ("width", "expected"),
    [
        (100, BrandVariant.WIDE),
        (78, BrandVariant.WIDE),
        (77, BrandVariant.MEDIUM),
        (48, BrandVariant.MEDIUM),
        (47, BrandVariant.COMPACT),
    ],
)
def test_brand_variant_uses_cell_breakpoints(width, expected):
    assert variant_for(width) is expected


def test_ascii_brand_has_no_non_ascii_character():
    assert brand_text(BrandVariant.COMPACT, unicode=False).isascii()
    assert brand_text(BrandVariant.COMPACT, unicode=False) == ">_ <-> SHAMBLES"


def test_wide_brand_preserves_the_readme_wordmark_without_its_frame():
    assert tuple(brand_text(BrandVariant.WIDE).splitlines()) == README_WORDMARK


@pytest.mark.parametrize(
    ("variant", "maximum_width"),
    [
        (BrandVariant.WIDE, 78),
        (BrandVariant.MEDIUM, 48),
        (BrandVariant.COMPACT, 47),
    ],
)
@pytest.mark.parametrize("unicode", [True, False])
def test_fixed_brand_rows_fit_their_variant(variant, maximum_width, unicode):
    rows = brand_text(variant, unicode=unicode).splitlines()
    assert rows
    assert max(map(cell_len, rows)) <= maximum_width
    for lockup_unicode in (True, False):
        lockup_rows = lockup_text(unicode=lockup_unicode).splitlines()
        assert max(map(cell_len, lockup_rows)) <= 78


@pytest.mark.parametrize("variant", list(BrandVariant))
def test_ascii_fallback_is_strict_ascii_and_has_no_ansi(variant):
    rendered = brand_text(variant, unicode=False)
    assert rendered.isascii()
    assert "\x1b" not in rendered


@pytest.mark.parametrize("variant", list(BrandVariant))
def test_brand_art_has_no_embedded_ansi_sequences(variant):
    assert "\x1b" not in brand_text(variant)


README_LOCKUP_START = "╔═[ >_ ⇄ ]"
README_TAGLINE = "Switch Claude and Codex accounts safely."
OFFLINE_CHIP = "OFFLINE"


def test_lockup_contains_readme_wordmark_frame_and_tagline():
    text = lockup_text(unicode=True)
    assert README_LOCKUP_START in text.splitlines()[0]
    assert OFFLINE_CHIP in text
    assert README_TAGLINE in text
    for row in README_WORDMARK:
        assert row in text
    assert "\x1b" not in text


def test_ascii_lockup_is_strict_ascii_and_names_shambles():
    text = lockup_text(unicode=False)
    assert text.isascii()
    assert ">_ <->" in text
    assert "OFFLINE" in text
    assert "SHAMBLES" in text
    assert "\x1b" not in text


@pytest.mark.parametrize(
    ("width", "height", "kind"),
    [
        (100, 32, "lockup"),
        (78, 24, "lockup"),
        (78, 23, "compact"),
        (77, 32, "compact"),
        (40, 24, "compact"),
    ],
)
def test_header_kind_requires_wide_and_tall(width, height, kind):
    assert header_kind(width, height) == kind


def test_header_text_lockup_vs_compact():
    assert "OFFLINE" in header_text(80, 32, unicode=True)
    assert header_text(80, 16, unicode=True) == ">_ ⇄ SHAMBLES"
    assert header_text(80, 16, unicode=False) == ">_ <-> SHAMBLES"
