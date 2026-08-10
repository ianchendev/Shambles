"""The presentation layer: what to show, and the commands that change it.

Kept apart from ``shambles.providers`` and ``shambles.stores`` because it
answers a different question. Those two describe credentials; this one decides
what a person sees. Native shells -- a macOS menu bar app, a Windows tray --
consume :mod:`shambles.app.snapshot` through the CLI and render it, holding no
rules of their own.
"""

from .snapshot import CONTRACT_VERSION, Account, Group, Snapshot, Surface
from .usage import Usage, UsageSource, UsageWindow

__all__ = [
    "CONTRACT_VERSION",
    "Snapshot", "Group", "Account", "Surface",
    "Usage", "UsageWindow", "UsageSource",
]
