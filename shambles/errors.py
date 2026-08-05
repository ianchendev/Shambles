"""Typed exceptions carrying user-facing messages.

The GUI renders ``str(exc)`` straight into a dialog box, so every message here
must read well to someone who has never seen the source. Tracebacks never reach
the user.
"""

WINDOWS_SYMLINK_HELP = (
    "Windows blocked symlink creation.\n\n"
    "Enable Developer Mode (Settings → System → For developers), "
    "or run Shambles as Administrator."
)


class ShamblesError(Exception):
    """Base for every error Shambles shows the user."""


class SymlinkPermissionError(ShamblesError):
    """The OS refused to create a symlink. On Windows this is WinError 1314."""


class ProfileNameError(ShamblesError):
    """A profile name failed validation."""


class ProfileNotFoundError(ShamblesError):
    """A named profile does not exist on disk."""


class ForeignLinkError(ShamblesError):
    """~/.claude is a symlink pointing outside ~/.claude-profiles/."""


class AlreadyManagedError(ShamblesError):
    """~/.claude is already a symlink, so there is nothing to save."""


class SwitchFailedError(ShamblesError):
    """A filesystem step failed after exhausting its retries."""


class ConfigUnreadableError(ShamblesError):
    """~/.claude.json exists but could not be parsed, so it must not be
    written over. Claude Code rewrites that file on its own schedule, and a
    read landing mid-write sees truncated JSON."""
