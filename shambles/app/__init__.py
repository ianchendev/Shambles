"""The presentation layer: what a native shell shows, and how it asks.

Kept apart from :mod:`shambles.providers` and :mod:`shambles.stores` because it
answers a different question. Those describe credentials; this decides what a
person sees. A macOS menu bar app or a Windows tray consumes
:mod:`shambles.app.snapshot` through the CLI and renders it, holding no rules
of its own.
"""

from .snapshot import (CONTRACT_VERSION, Account, Group, Snapshot, Surface,
                       Window)

__all__ = ["CONTRACT_VERSION", "Snapshot", "Group", "Account", "Surface",
           "Window"]
