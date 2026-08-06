"""Fonts, colours and ttk styling.

Kept apart from the widget tree so the look can be adjusted without touching
layout logic. Tk gives no cascading stylesheet, so every value here has to be
applied per widget -- collecting them in one place is what keeps that bearable.
"""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

#: First of these that the system actually has wins. DejaVu Sans is Tk's
#: default on most Linux boxes and is the ugliest of the three.
FONT_STACK = ("Ubuntu", "Segoe UI", "Noto Sans", "DejaVu Sans")

# Type scale. Bumped well above Tk's 10pt default, which is unreadable on a
# high-resolution display.
SIZE_TITLE = 18
SIZE_NAME = 13
SIZE_BODY = 11
SIZE_CHIP = 10
SIZE_CAPTION = 9

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

# Spacing scale, so padding is consistent instead of ad hoc.
GAP_XS, GAP_S, GAP_M, GAP_L = 4, 8, 14, 20

WINDOW_WIDTH = 600
ACCENT_BAR_WIDTH = 4


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


def scale_for_display(root, minimum: float = 1.35) -> float:
    """Nudge Tk's point-to-pixel ratio up on dense displays.

    Tk reads this from the X server, which under WSLg reports a conservative
    96 dpi regardless of the real panel. Left alone, every font comes out too
    small to read comfortably.
    """
    current = float(root.tk.call("tk", "scaling"))
    wanted = max(current, minimum)
    root.tk.call("tk", "scaling", wanted)
    return wanted
