"""Typed exceptions carrying user-facing messages.

The GUI renders ``str(exc)`` straight into a dialog box, so every message here
must read well to someone who has never seen the source. Tracebacks never reach
the user.
"""

class ShamblesError(Exception):
    """Base for every error Shambles shows the user."""


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


class DriftedLoginError(ShamblesError):
    """The live login belongs to an account other than the marked profile.

    Raised instead of filing it under that profile: the copy-out step exists
    so switching away is never lossy, and against a login that is not this
    profile's it does the opposite -- it overwrites a saved refresh token
    with a stranger's, which costs a verification email to undo.
    """
