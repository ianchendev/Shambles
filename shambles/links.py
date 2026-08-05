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


#: Windows returns directory links in extended-length form. See _strip_extended.
_EXTENDED_PREFIX = "\\\\?\\"
_EXTENDED_UNC_PREFIX = "\\\\?\\UNC\\"


def _strip_extended(path) -> str:
    r"""Drop Windows' extended-length prefix from a path.

    ``os.readlink`` on Windows hands back the raw reparse target, which for a
    directory link is the extended-length form ``\\?\C:\...``. Compared against
    an ordinary ``C:\...`` root that looks like a different volume entirely, so
    every managed profile was misread as a foreign link and Shambles refused to
    operate at all. POSIX paths pass through untouched.
    """
    text = os.fspath(path)
    if text.startswith(_EXTENDED_UNC_PREFIX):
        return "\\\\" + text[len(_EXTENDED_UNC_PREFIX):]
    if text.startswith(_EXTENDED_PREFIX):
        return text[len(_EXTENDED_PREFIX):]
    return text


def _real(path) -> str:
    """Absolute, prefix-free path for comparison.

    ``realpath`` does not fail on a missing path, which is what lets a dangling
    link still report which profile it was pointing at.
    """
    return _strip_extended(os.path.realpath(_strip_extended(path)))


def _profile_name_for(paths, target: Path) -> str | None:
    """The profile name if ``target`` is a direct child of the profiles dir.

    Compared through ``realpath`` so a hand-made link survives symlinked home
    directories.
    """
    try:
        relative = os.path.relpath(_real(target), _real(paths.profiles_dir))
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
