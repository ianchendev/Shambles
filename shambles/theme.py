"""Fonts, colours and ttk styling.

Kept apart from the widget tree so the look can be adjusted without touching
layout logic. Tk gives no cascading stylesheet, so every value here has to be
applied per widget -- collecting them in one place is what keeps that bearable.
"""

import os
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

#: First of these that the system actually has wins. DejaVu Sans is Tk's
#: default on most Linux boxes and is the ugliest of the three.
FONT_STACK = ("Ubuntu", "Segoe UI", "Noto Sans", "DejaVu Sans")

# Type scale. Bumped well above Tk's 10pt default, which is unreadable on a
# high-resolution display.
# Type scale, in points. Tk converts points to pixels with the `tk scaling`
# factor, so the rendered size is `size * scaling`.
#
# 16px is the floor every current accessibility guideline lands on for body
# text -- WCAG itself sets no minimum, requiring instead that text survive a
# 200% resize, but 16px is the practical consensus. At BASE_SCALING that means
# a 12pt body. The previous 11pt rendered 14.9px, which is why the window read
# as cramped.
SIZE_TITLE = 20      # 27px
SIZE_NAME = 15       # 20px
SIZE_BODY = 12       # 16px -- the floor
SIZE_CHIP = 11       # 15px, secondary
SIZE_CAPTION = 10    # 13.5px, uppercase labels only

PALETTE = {
    "window": "#f4f5f7",
    "card": "#ffffff",
    "card_active": "#eef4ff",
    "border": "#dfe1e6",
    "border_active": "#2563eb",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "text": "#17181c",
    "muted": "#6b7280",
    "faint": "#9ca3af",
    # expiry chips: foreground / background pairs
    "chip_ok_fg": "#4b5563", "chip_ok_bg": "#eef0f3",
    "chip_soon_fg": "#92400e", "chip_soon_bg": "#fef3c7",
    "chip_gone_fg": "#991b1b", "chip_gone_bg": "#fee2e2",
    "warn": "#b45309",
}

# Spacing scale, so padding is consistent instead of ad hoc. These are pixels
# and Tk does not scale them, so they are sized alongside the type rather than
# left behind it -- larger text in unchanged padding is what makes a window
# feel tight.
GAP_XS, GAP_S, GAP_M, GAP_L = 6, 10, 16, 24

WINDOW_WIDTH = 680
ACCENT_BAR_WIDTH = 5


def pick_family(root) -> str:
    available = set(tkfont.families(root))
    for family in FONT_STACK:
        if family in available:
            return family
    return tkfont.nametofont("TkDefaultFont").actual()["family"]


class Theme:
    """Resolved fonts plus the palette, built once per window."""

    def __init__(self, root):
        self.colours = dict(PALETTE)
        family = pick_family(root)
        self.family = family
        self.title = tkfont.Font(root=root, family=family, size=SIZE_TITLE, weight="bold")
        self.name = tkfont.Font(root=root, family=family, size=SIZE_NAME, weight="bold")
        self.body = tkfont.Font(root=root, family=family, size=SIZE_BODY)
        self.chip = tkfont.Font(root=root, family=family, size=SIZE_CHIP, weight="bold")
        self.caption = tkfont.Font(root=root, family=family, size=SIZE_CAPTION, weight="bold")
        self.button = tkfont.Font(root=root, family=family, size=SIZE_BODY)
        self._apply_ttk(root)

    def __getitem__(self, key):
        return self.colours[key]

    def _apply_ttk(self, root):
        """Restyle ttk's buttons.

        'clam' is the only bundled theme that honours background colour on
        buttons; 'default' ignores most of what you set.
        """
        style = ttk.Style(root)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        c = self.colours

        style.configure(
            "Shambles.TButton", font=self.button, padding=(GAP_M, GAP_S),
            relief="flat", borderwidth=0,
            background=c["card"], foreground=c["text"],
        )
        style.map(
            "Shambles.TButton",
            background=[("disabled", c["window"]), ("pressed", c["border"]),
                        ("active", c["border"])],
            foreground=[("disabled", c["faint"])],
        )

        style.configure(
            "Accent.TButton", font=self.button, padding=(GAP_M, GAP_S),
            relief="flat", borderwidth=0,
            background=c["accent"], foreground="#ffffff",
        )
        style.map(
            "Accent.TButton",
            background=[("disabled", c["border"]), ("pressed", c["accent_hover"]),
                        ("active", c["accent_hover"])],
            foreground=[("disabled", c["faint"])],
        )

        style.configure(
            "Switch.TButton", font=self.button, padding=(GAP_M, GAP_XS + 2),
            relief="flat", borderwidth=0,
            background=c["window"], foreground=c["accent"],
        )
        style.map(
            "Switch.TButton",
            background=[("pressed", c["border"]), ("active", c["border"])],
        )

        # The ✕ on a profile card. Grey at rest so a destructive control does
        # not compete with Switch, which sits beside it and gets clicked
        # constantly; red once the pointer is on it, to say what it does before
        # the click rather than only in the dialog afterwards.
        style.configure(
            "Danger.TButton", font=self.button, padding=(GAP_S, GAP_XS + 2),
            relief="flat", borderwidth=0,
            background=c["window"], foreground=c["faint"],
        )
        style.map(
            "Danger.TButton",
            background=[("pressed", c["chip_gone_bg"]),
                        ("active", c["chip_gone_bg"])],
            foreground=[("pressed", c["chip_gone_fg"]),
                        ("active", c["chip_gone_fg"])],
        )


#: Point-to-pixel ratio assumed when the display reports nothing useful.
#: 1.35 is a hair above the 96dpi default of 1.333, which is what makes a 12pt
#: body land on the 16px floor.
BASE_SCALING = 1.35

#: Above this framebuffer width, a 96dpi report is not credible.
WIDE_PANEL_PX = 2560
WIDE_PANEL_SCALING = 1.6

#: Manual escape hatch, e.g. SHAMBLES_SCALE=1.9 for a very dense panel.
SCALE_ENV = "SHAMBLES_SCALE"

#: Refuse anything outside this: a typo should not produce an unusable window.
SCALING_LIMITS = (1.0, 4.0)


def scaling_for(current: float, screen_width: int, override=None) -> float:
    """Decide Tk's point-to-pixel ratio.

    ``current`` is what the X server reported. Under WSLg, and on plenty of
    bare Linux setups, that is a flat 96dpi -- 1.333 -- no matter how dense the
    panel actually is, so a wide framebuffer reporting it is evidence the
    report is wrong rather than that the display is coarse.

    A desktop already doing fractional scaling reports a higher figure, and
    that is left alone: raising it again would double-scale.
    """
    if override:
        try:
            wanted = float(override)
        except (TypeError, ValueError):
            wanted = 0.0
        if SCALING_LIMITS[0] <= wanted <= SCALING_LIMITS[1]:
            return wanted

    floor = WIDE_PANEL_SCALING if screen_width >= WIDE_PANEL_PX else BASE_SCALING
    return max(current, floor)


def scale_for_display(root, minimum: float | None = None) -> float:
    """Apply :func:`scaling_for` to a live root window."""
    current = float(root.tk.call("tk", "scaling"))
    wanted = scaling_for(current, root.winfo_screenwidth(),
                         os.environ.get(SCALE_ENV))
    if minimum is not None:
        wanted = max(wanted, minimum)
    root.tk.call("tk", "scaling", wanted)
    return wanted


#: Never let the window exceed this share of the screen. Beyond it the footer
#: runs off the bottom and, since the window is not resizable, its buttons
#: become unreachable.
MAX_HEIGHT_FRACTION = 0.8

#: Width a profile name may occupy before it is elided, in pixels. The window
#: is fixed-width and Tk labels do not truncate, so an over-long name stretches
#: the whole window instead of being clipped. Measured against the card's own
#: geometry: total width less the accent spine, padding and the two controls.
NAME_MAX_PX = WINDOW_WIDTH - 260


def elide(text: str, font, max_px: int) -> str:
    """Shorten ``text`` until it measures under ``max_px``, ending in an
    ellipsis.

    Preferred over rejecting long names outright: a character limit has to be
    re-guessed every time the type scale moves, and it refuses names that would
    have rendered perfectly well in a wider window.
    """
    if not text or font.measure(text) <= max_px:
        return text
    ellipsis = "…"
    budget = max_px - font.measure(ellipsis)
    if budget <= 0:
        return ellipsis
    cut = text
    while cut and font.measure(cut) > budget:
        cut = cut[:-1]
    return (cut + ellipsis) if cut else ellipsis
