"""Fixed, terminal-native Shambles brand compositions.

The artwork contains no colour escapes.  Textual owns presentation styling,
which keeps these strings suitable for ``NO_COLOR`` terminals and makes their
cell widths deterministic.
"""

from enum import Enum
from typing import Dict, Tuple


class BrandVariant(Enum):
    """Brand composition selected for the available terminal width."""

    WIDE = "wide"
    MEDIUM = "medium"
    COMPACT = "compact"


# This is the wordmark inside README.md's ANSI-art frame, unchanged.  The TUI
# composes its frame separately so onboarding motion never alters the artwork.
WIDE_UNICODE_ROWS: Tuple[str, ...] = (
    "███████╗██╗  ██╗ █████╗ ███╗   ███╗██████╗ ██╗     ███████╗███████╗",
    "██╔════╝██║  ██║██╔══██╗████╗ ████║██╔══██╗██║     ██╔════╝██╔════╝",
    "███████╗███████║███████║██╔████╔██║██████╔╝██║     █████╗  ███████╗",
    "╚════██║██╔══██║██╔══██║██║╚██╔╝██║██╔══██╗██║     ██╔══╝  ╚════██║",
    "███████║██║  ██║██║  ██║██║ ╚═╝ ██║██████╔╝███████╗███████╗███████║",
    "╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═════╝ ╚══════╝╚══════╝╚══════╝",
)

MEDIUM_UNICODE_ROWS: Tuple[str, ...] = (
    ">_ ⇄",
    "SHAMBLES",
    "Switch Claude and Codex accounts safely.",
)

WIDE_ASCII_ROWS: Tuple[str, ...] = (
    "SHAMBLES",
    "Claude + Codex account switcher",
)

MEDIUM_ASCII_ROWS: Tuple[str, ...] = (
    ">_ <->",
    "SHAMBLES",
    "Switch Claude and Codex accounts safely.",
)

UNICODE_ART: Dict[BrandVariant, str] = {
    BrandVariant.WIDE: "\n".join(WIDE_UNICODE_ROWS),
    BrandVariant.MEDIUM: "\n".join(MEDIUM_UNICODE_ROWS),
}

ASCII_ART: Dict[BrandVariant, str] = {
    BrandVariant.WIDE: "\n".join(WIDE_ASCII_ROWS),
    BrandVariant.MEDIUM: "\n".join(MEDIUM_ASCII_ROWS),
}


def variant_for(width: int) -> BrandVariant:
    """Select the fixed composition for a terminal width in cells."""

    if width >= 78:
        return BrandVariant.WIDE
    if width >= 48:
        return BrandVariant.MEDIUM
    return BrandVariant.COMPACT


def brand_text(variant: BrandVariant, *, unicode: bool = True) -> str:
    """Render *variant* without colour or cursor-control escape sequences."""

    if variant is BrandVariant.COMPACT:
        return ">_ ⇄ SHAMBLES" if unicode else ">_ <-> SHAMBLES"
    return UNICODE_ART[variant] if unicode else ASCII_ART[variant]
