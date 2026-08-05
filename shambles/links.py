"""The state of ~/.claude, and the atomic swap that re-points it."""

import os
import time
from dataclasses import dataclass
from pathlib import Path

from . import retry

MISSING = "missing"      # ~/.claude does not exist
UNMANAGED = "unmanaged"  # a real directory; not yet saved into a profile
MANAGED = "managed"      # a symlink into ~/.claude-profiles/
DANGLING = "dangling"    # a symlink into ~/.claude-profiles/, target gone
FOREIGN = "foreign"      # a symlink somewhere else entirely


@dataclass(frozen=True)
class LinkState:
    kind: str
    target: Path | None = None
    profile: str | None = None


def inspect(paths) -> LinkState:
    """Classify ~/.claude. This is the only source of truth for what is active."""
    link = paths.claude_dir
    if link.is_symlink():
        target = Path(os.readlink(link))
        if not target.is_absolute():
            target = link.parent / target
        name = _profile_name_for(paths, target)
        if name is None:
            return LinkState(FOREIGN, target)
        if not target.is_dir():
            return LinkState(DANGLING, target, name)
        return LinkState(MANAGED, target, name)
    if link.is_dir():
        return LinkState(UNMANAGED, link)
    return LinkState(MISSING)


def _profile_name_for(paths, target: Path) -> str | None:
    """The profile name if ``target`` is a direct child of the profiles dir.

    Compared through ``realpath`` so a hand-made link survives symlinked home
    directories. ``realpath`` does not fail on a missing path, which is what
    lets a dangling link still report which profile it was pointing at.
    """
    try:
        root = os.path.realpath(paths.profiles_dir)
        relative = os.path.relpath(os.path.realpath(target), root)
    except (OSError, ValueError):
        return None
    parts = Path(relative).parts
    if len(parts) != 1 or parts[0] in (".", ".."):
        return None
    return parts[0]


def point_to(paths, profile_dir, *, sleep=time.sleep) -> None:
    """Atomically re-point ~/.claude at ``profile_dir``.

    Creates a temporary link beside it and renames that over the top, so there
    is never an instant where ~/.claude does not exist. Unlink-then-symlink
    would leave a window in which a crash costs the user their config path.
    """
    target = str(Path(profile_dir).absolute())
    retry.with_retry(
        lambda: _swap(paths, target), "update ~/.claude", sleep=sleep
    )


def _swap(paths, target: str) -> None:
    tmp = paths.tmp_link
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()
    os.symlink(target, tmp, target_is_directory=True)
    os.replace(tmp, paths.claude_dir)
