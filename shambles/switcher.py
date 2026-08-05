"""Switching accounts by swapping the login, and nothing else.

``~/.claude`` stays exactly where it is. Only two things move:

* ``~/.claude/.credentials.json`` -- the OAuth tokens
* ``oauthAccount`` and ``cachedUsageUtilization`` in ``~/.claude.json``

Everything else in ``~/.claude`` -- session history, plugins, file history,
todos, settings -- is machine-scoped and shared across accounts, which is how
Claude Code behaves on its own. An earlier design swapped the whole directory
and so partitioned session history per account; that was wrong.
"""

import os
import shutil
import time
from pathlib import Path

from . import configjson, profiles, state
from .errors import (AlreadyManagedError, ProfileNotFoundError,
                     SwitchFailedError)

NOTHING_TO_SAVE = (
    "There is no login to save — ~/.claude has no credentials file yet.\n\n"
    "Run 'claude' and sign in first, then save that account here."
)

SAVE_FIRST = (
    "Save your current account first.\n\n"
    "Otherwise the login in ~/.claude would be replaced with nothing and you "
    "would have to sign in again to get it back."
)


def now_ms() -> int:
    return int(time.time() * 1000)


def _copy_secret(source: Path, dest: Path) -> None:
    """Copy a credentials file, atomically and readable only by its owner."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".shambles-tmp")
    shutil.copyfile(source, tmp)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)


def stash_live_login(paths, name: str, *, now_ms_fn=now_ms) -> None:
    """Capture whatever is logged in right now into profile ``name``."""
    paths.profile_dir(name).mkdir(parents=True, exist_ok=True)
    if paths.live_credentials.exists():
        _copy_secret(paths.live_credentials, paths.credentials(name))
    account = configjson.extract_account_keys(
        configjson.load(paths.claude_json))
    configjson.write_sidecar(paths.account(name), account, now_ms_fn())


def switch(paths, target_name: str, *, now_ms_fn=now_ms, sleep=time.sleep):
    """Make ``target_name`` the logged-in account.

    Stashes the outgoing login, restores the incoming one, and splices the
    matching identity into ~/.claude.json. Session history is untouched: it
    never moves.
    """
    current = state.inspect(paths)
    if current.kind == state.LEGACY_LAYOUT:
        raise SwitchFailedError(MIGRATION_REQUIRED)

    if not paths.profile_dir(target_name).is_dir():
        raise ProfileNotFoundError(
            f"Profile '{target_name}' no longer exists on disk.")

    # Refuse before anything moves if the config cannot be parsed; writing
    # onto an unreadable config would replace the whole file.
    configjson.load_for_write(paths.claude_json)

    stamp = now_ms_fn()
    configjson.backup(paths.claude_json, paths.backup_dir, stamp)

    # Stash the outgoing login so switching away is never lossy. Skipped when
    # the marker points at a profile that is already gone.
    if current.profile and paths.profile_dir(current.profile).is_dir():
        stash_live_login(paths, current.profile, now_ms_fn=lambda: stamp)

    incoming = paths.credentials(target_name)
    paths.claude_dir.mkdir(parents=True, exist_ok=True)
    try:
        if incoming.exists():
            _copy_secret(incoming, paths.live_credentials)
        else:
            # A profile that has never been signed into: clear the login so
            # Claude Code prompts for one rather than reusing the last account.
            paths.live_credentials.unlink(missing_ok=True)
    except OSError as exc:
        raise SwitchFailedError(
            f"Could not update the login in ~/.claude:\n{exc}") from exc

    configjson.apply_account_keys(
        paths.claude_json, configjson.read_sidecar(paths.account(target_name)))
    state.write_active(paths, target_name)
    return state.inspect(paths)


MIGRATION_REQUIRED = (
    "~/.claude is still a symlink from an older version of Shambles.\n\n"
    "That layout gave every account its own copy of your session history. "
    "Run the migration to merge them back into one shared directory."
)


def save_current_account(paths, name, *, now_ms_fn=now_ms, sleep=time.sleep) -> str:
    """Record the account that is logged in right now as a profile."""
    current = state.inspect(paths)
    if current.kind == state.LEGACY_LAYOUT:
        raise SwitchFailedError(MIGRATION_REQUIRED)
    if current.kind == state.MANAGED:
        raise AlreadyManagedError(
            f"This login is already saved as '{current.profile}'.")
    if not paths.live_credentials.exists():
        raise AlreadyManagedError(NOTHING_TO_SAVE)

    name = profiles.validate_profile_name(name, state.profile_names(paths))
    stash_live_login(paths, name, now_ms_fn=now_ms_fn)
    state.write_active(paths, name)
    return name


def add_empty_account(paths, name, *, seed_settings: bool = True,
                      now_ms_fn=now_ms, sleep=time.sleep) -> str:
    """Create a profile with no login and make it current.

    ``seed_settings`` is accepted for compatibility and ignored: settings now
    live in the shared ~/.claude and are never per-account.
    """
    current = state.inspect(paths)
    if current.kind == state.LEGACY_LAYOUT:
        raise SwitchFailedError(MIGRATION_REQUIRED)
    if current.kind == state.UNMANAGED and paths.live_credentials.exists():
        raise AlreadyManagedError(SAVE_FIRST)

    name = profiles.validate_profile_name(name, state.profile_names(paths))
    paths.profile_dir(name).mkdir(parents=True, exist_ok=True)
    return switch(paths, name, now_ms_fn=now_ms_fn, sleep=sleep).profile or name


def rename_profile(paths, old_name: str, new_name: str, *, sleep=time.sleep) -> str:
    if not paths.profile_dir(old_name).is_dir():
        raise ProfileNotFoundError(f"Profile '{old_name}' does not exist.")

    existing = [n for n in state.profile_names(paths) if n != old_name]
    new_name = profiles.validate_profile_name(new_name, existing)
    if new_name == old_name:
        return old_name

    try:
        paths.profile_dir(old_name).rename(paths.profile_dir(new_name))
    except OSError as exc:
        raise SwitchFailedError(f"Could not rename the profile:\n{exc}") from exc

    if state.read_active(paths) == old_name:
        state.write_active(paths, new_name)
    return new_name


def forget_active_marker(paths) -> None:
    """Clear a marker pointing at a profile that no longer exists."""
    state.write_active(paths, None)


def crosses_filesystem(paths) -> bool:
    """Kept for the GUI's warning. Nothing large is copied any more, so this
    is always false; the credentials file is half a kilobyte."""
    return False
