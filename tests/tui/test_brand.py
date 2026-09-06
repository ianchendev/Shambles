"""Responsive terminal branding stays legible at every supported width."""

import pytest
from rich.cells import cell_len

from shambles.app.tui.brand import BrandVariant, brand_text, variant_for


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


@pytest.mark.parametrize("variant", list(BrandVariant))
def test_ascii_fallback_is_strict_ascii_and_has_no_ansi(variant):
    rendered = brand_text(variant, unicode=False)
    assert rendered.isascii()
    assert "\x1b" not in rendered


@pytest.mark.parametrize("variant", list(BrandVariant))
def test_brand_art_has_no_embedded_ansi_sequences(variant):
    assert "\x1b" not in brand_text(variant)
