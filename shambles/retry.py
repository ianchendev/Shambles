"""Retrying filesystem work that a running Claude Code may briefly block."""

import time

from .errors import WINDOWS_SYMLINK_HELP, SwitchFailedError, SymlinkPermissionError

RETRIES = 3
DELAY = 0.5

WINDOWS_SYMLINK_DENIED = 1314


def with_retry(action, what: str, *, retries: int = RETRIES,
               delay: float = DELAY, sleep=time.sleep):
    """Call ``action`` until it succeeds, ``retries`` times.

    ``what`` is a verb phrase spliced into the failure message, e.g.
    ``"update ~/.claude"``. ``sleep`` is injected so tests never wait.

    A Windows privilege error is raised immediately -- no amount of waiting
    grants the account the right to create symlinks.
    """
    last = None
    for attempt in range(retries):
        try:
            return action()
        except OSError as exc:
            if getattr(exc, "winerror", None) == WINDOWS_SYMLINK_DENIED:
                raise SymlinkPermissionError(WINDOWS_SYMLINK_HELP) from exc
            last = exc
            if attempt < retries - 1:
                sleep(delay)
    raise SwitchFailedError(
        f"Could not {what} after {retries} attempts:\n{last}\n\n"
        "Close any running Claude Code sessions and try again."
    ) from last
