"""Switching accounts by swapping the login, and nothing else.

``~/.claude`` stays exactly where it is. Only two things move:

* ``~/.claude/.credentials.json`` -- the OAuth tokens
* ``oauthAccount`` in ``~/.claude.json``; ``cachedUsageUtilization`` is
  cleared rather than carried, since it is a cache that goes stale

Everything else in ``~/.claude`` -- session history, plugins, file history,
todos, settings -- is machine-scoped and shared across accounts, which is how
Claude Code behaves on its own. An earlier design swapped the whole directory
and so partitioned session history per account; that was wrong.
"""

import os
import shutil
import time
from pathlib import Path

from . import configjson, profiles, retry, state
from .errors import (AlreadyManagedError, ProfileNotFoundError, ShamblesError,
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


def copy_secret(source: Path, dest: Path, *, sleep=time.sleep) -> None:
    """Copy a credentials file, atomically and readable only by its owner.

    Retried: a running Claude Code, an antivirus scan or the Windows indexer
    can hold either file for a moment, and a single refusal is not a reason to
    fail the whole switch. Exhausting the retries raises SwitchFailedError,
    which the GUI knows how to display -- a bare OSError would reach the user
    as a silent stderr traceback.
    """
    def once():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".shambles-tmp")
        shutil.copyfile(source, tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)

    retry.with_retry(once, f"write {dest.name}", sleep=sleep)


def stash_live_login(paths, name: str, *, now_ms_fn=now_ms, sleep=time.sleep) -> None:
    """Capture whatever is logged in right now into profile ``name``."""
    paths.ensure_profile(name)
    if paths.live_credentials.exists():
        copy_secret(paths.live_credentials, paths.credentials(name), sleep=sleep)
    config = configjson.load(paths.claude_json)
    account = configjson.extract_account_keys(config)
    # Kept for this profile's card only, under a key of our own so it can never
    # be mistaken for something to splice back. configjson.STALE_ON_SWITCH
    # explains why a cached figure must not return to ~/.claude.json.
    cached = config.get("cachedUsageUtilization")
    if isinstance(cached, dict):
        account["usage"] = cached
    configjson.write_sidecar(paths.account(name), account, now_ms_fn())


def sync_active_credentials(paths, active_name, *, sleep=time.sleep) -> bool:
    """Refresh the active profile's stored copy of its own login.

    Refresh tokens rotate: Claude Code replaces ``.credentials.json`` in place
    whenever it renews, so the copy stashed when the profile was switched *in*
    is superseded within hours. Left alone, switching away and back could
    restore a token that has already been rotated out.

    Returns True when it wrote. Called on every window refresh, so it compares
    first rather than rewriting a secret each time.
    """
    if not active_name:
        return False
    live = paths.live_credentials
    stored = paths.credentials(active_name)
    if not live.exists():
        return False
    try:
        if stored.exists() and stored.read_bytes() == live.read_bytes():
            return False
    except OSError:
        return False

    try:
        copy_secret(live, stored, sleep=sleep)
    except ShamblesError:
        # A locked file is not worth interrupting the window for; the next
        # refresh, or the next switch, will catch it.
        return False
    return True


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

    # Everything that touches the filesystem lives inside one guard, so no
    # path out of here raises a bare OSError. The GUI renders ShamblesError
    # only; anything else would reach the user as a stderr traceback and look
    # like the switch silently did nothing.
    incoming = paths.credentials(target_name)
    try:
        # Claude Code rewrites ~/.claude.json on its own schedule, so copying
        # it can collide with a write in progress. Retried like the rest.
        retry.with_retry(
            lambda: configjson.backup(paths.claude_json, paths.backup_dir, stamp),
            "back up ~/.claude.json", sleep=sleep)

        # Stash the outgoing login so switching away is never lossy. Skipped
        # when the marker points at a profile that is already gone.
        if current.profile and paths.profile_dir(current.profile).is_dir():
            stash_live_login(paths, current.profile, now_ms_fn=lambda: stamp,
                             sleep=sleep)

        paths.claude_dir.mkdir(parents=True, exist_ok=True)
        if incoming.exists():
            copy_secret(incoming, paths.live_credentials, sleep=sleep)
        else:
            # A profile that has never been signed into: clear the login so
            # Claude Code prompts for one rather than reusing the last account.
            paths.live_credentials.unlink(missing_ok=True)
    except OSError as exc:
        raise SwitchFailedError(
            f"Could not update the login in ~/.claude:\n{exc}\n\n"
            "Close any running Claude Code sessions and try again.") from exc

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
    stash_live_login(paths, name, now_ms_fn=now_ms_fn, sleep=sleep)
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
    paths.ensure_profile(name)
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


REMOVE_ACTIVE = (
    "'{name}' is the account you are signed in as.\n\n"
    "Switch to another profile first, then remove this one."
)


def remove_profile(paths, name: str) -> None:
    """Delete a profile directory and the login inside it.

    Irreversible in the sense that matters: the refresh token goes with it, so
    that account needs a fresh ``/login`` and its verification email to come
    back. Session history is untouched -- it does not live here.

    Refuses the active profile even though the UI hides the control for it.
    Hiding a button is not a safety property.
    """
    current = state.inspect(paths)
    if current.kind == state.LEGACY_LAYOUT:
        raise SwitchFailedError(MIGRATION_REQUIRED)
    if name == current.profile:
        raise AlreadyManagedError(REMOVE_ACTIVE.format(name=name))

    target = paths.profile_dir(name)
    # A name like ".." resolves outside the store. validate_profile_name blocks
    # separators on the way in, but this deletes a tree, so it re-checks rather
    # than trusting how the name arrived.
    try:
        resolved = target.resolve()
        store = paths.profiles_dir.resolve()
    except OSError as exc:
        raise SwitchFailedError(f"Could not resolve '{name}':\n{exc}") from exc
    if resolved.parent != store or resolved == store:
        raise ProfileNotFoundError(f"'{name}' is not a profile.")
    if not target.is_dir():
        raise ProfileNotFoundError(f"Profile '{name}' does not exist.")

    try:
        shutil.rmtree(target)
    except OSError as exc:
        raise SwitchFailedError(
            f"Could not remove '{name}':\n{exc}\n\n"
            "Close any running Claude Code sessions and try again.") from exc


def forget_active_marker(paths) -> None:
    """Clear a marker pointing at a profile that no longer exists."""
    state.write_active(paths, None)


def crosses_filesystem(paths) -> bool:
    """Kept for the GUI's warning. Nothing large is copied any more, so this
    is always false; the credentials file is half a kilobyte."""
    return False
