"""The window's colours, light and dark. Data only; no Qt in here.

One flat mapping per scheme with the same keys in both, so the QML reads
``ui.theme.surface`` and never asks which scheme it is in. A key missing
from one scheme would draw as transparent in that scheme only, which is the
kind of fault nobody sees until a user in the other mode reports it --
``tests/qt/test_theme.py`` holds the two key sets equal, and holds body text
to a 4.5:1 contrast against the surfaces it sits on.
"""

LIGHT = {
    "ground": "#f4f5f7",
    "surface": "#ffffff",
    "sunken": "#f4f5f7",
    "border": "#dfe2e8",
    "hairline": "#eceef2",
    "text": "#15171c",
    "muted": "#5b6270",
    "faint": "#c9ced6",
    "accent": "#2563eb",
    "accentHover": "#1d4fd0",
    "accentText": "#1d4fc4",
    "accentSoft": "#f2f6ff",
    "accentSoftBorder": "#c9d6f5",
    "onAccent": "#ffffff",
    "liveBorder": "#2563eb",
    "liveAvatar": "#e6efff",
    "avatar": "#eef0f3",
    "avatarText": "#3d4350",
    "okBg": "#e3f5ea",
    "okText": "#14633a",
    "okDot": "#1c8a52",
    "warnBg": "#fff1cc",
    "warnText": "#7a4a00",
    "warnBorder": "#e2b23c",
    "warnSurface": "#fff8e6",
    "badBg": "#fde8e6",
    "badText": "#9b1c16",
    "badBorder": "#e3b5b1",
    "badSurface": "#fff5f4",
    "infoSurface": "#f2f6ff",
    "infoText": "#1c2a4a",
    "track": "#e7eaef",
    "barOk": "#2563eb",
    "barSoon": "#c98a1b",
    "barGone": "#d0342c",
    "barDim": "#b6bcc7",
    "scrim": "#6b15171c",
    "sheet": "#ffffff",
    "toast": "#1b1e25",
    "onToast": "#f4f5f7",
    "focus": "#2563eb",
}

DARK = {
    "ground": "#0f1218",
    "surface": "#181c24",
    "sunken": "#12151c",
    "border": "#2a303b",
    "hairline": "#262b35",
    "text": "#eef0f4",
    "muted": "#a3abb8",
    "faint": "#4a5261",
    "accent": "#2b62dc",
    "accentHover": "#356ce4",
    "accentText": "#a9c4ff",
    "accentSoft": "#18233f",
    "accentSoftBorder": "#2f4374",
    "onAccent": "#ffffff",
    "liveBorder": "#5b8dff",
    "liveAvatar": "#1b2a4d",
    "avatar": "#262b35",
    "avatarText": "#c7cdd8",
    "okBg": "#143524",
    "okText": "#7fe0a8",
    "okDot": "#4fcf87",
    "warnBg": "#3a2c0e",
    "warnText": "#f2c166",
    "warnBorder": "#a37a23",
    "warnSurface": "#2a2210",
    "badBg": "#421c1c",
    "badText": "#ffa69e",
    "badBorder": "#6b2a2c",
    "badSurface": "#2b161c",
    "infoSurface": "#18233f",
    "infoText": "#d6e2ff",
    "track": "#2a303b",
    "barOk": "#5b8dff",
    "barSoon": "#f2c166",
    "barGone": "#ff7b6e",
    "barDim": "#4a5261",
    "scrim": "#99000000",
    "sheet": "#1b202a",
    "toast": "#eef0f4",
    "onToast": "#15171c",
    "focus": "#7aa7ff",
}


def is_dark(choice: str, system_dark) -> bool:
    """Whether to draw dark, from the stored choice and what the OS says.

    ``system_dark`` is True, False, or None when the toolkit cannot tell --
    which is every time under WSLg. Unknown reads as light, because a light
    window on a dark desktop is legible and the reverse guess is no better.
    """
    if choice == "dark":
        return True
    if choice == "light":
        return False
    return bool(system_dark)


def tokens(dark: bool) -> dict:
    return dict(DARK if dark else LIGHT)
