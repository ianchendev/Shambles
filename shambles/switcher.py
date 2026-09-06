"""Switching accounts by swapping one credential, and nothing else.

Nothing but the login is account-scoped. Session history, plugins, settings
and project trust are machine-scoped and shared across every account, which is
how both vendors behave on their own.

Every function takes a provider. The *flow* below is identical for all of
them -- verify, back up, stash outgoing, restore incoming, splice, record --
and only its steps differ, which is exactly the split DD-4 describes.
"""

import shutil
import sys
import time

from . import configjson, profiles, retry, state
from .errors import (AlreadyManagedError, DriftedLoginError,
                     ProfileNotFoundError, ShamblesError, SwitchFailedError)
from .stores.base import StoreUnavailableError

NOTHING_TO_SAVE = (
    "There is no login to save — {store} has no credentials yet.\n\n"
    "Sign in with {provider} first, then save that account here."
)

SAVE_FIRST = (
    "Save your current account first.\n\n"
    "Otherwise the live login would be replaced with nothing and you would "
    "have to sign in again to get it back."
)

REMOVE_ACTIVE = (
    "'{name}' is the account you are signed in as.\n\n"
    "Switch to another profile first, then remove this one."
)

MIGRATION_REQUIRED = (
    "~/.claude is still a symlink from an older version of Shambles.\n\n"
    "That layout gave every account its own copy of your session history. "
    "Run the migration to merge them back into one shared directory."
)


def _refuse_legacy_layout(paths) -> None:
    """Stop before touching a pre-1.0 layout.

    ``~/.claude`` being a symlink means it points *into* a profile directory,
    so writing the live credential would write through the link and corrupt
    the very profile the switch is trying to leave. The GUI migrates on
    startup, so this should be unreachable there -- it is here because a
    half-applied switch on that layout is unrecoverable and the check is one
    ``is_symlink`` call.

    Claude-only: the pre-1.0 layout predates every other provider.
    """
    if paths.claude_dir.is_symlink():
        raise SwitchFailedError(MIGRATION_REQUIRED)


def now_ms() -> int:
    return int(time.time() * 1000)


def _store(paths, provider, platform):
    return provider.store(home=paths.home, platform=platform)


DRIFT_REFUSAL = (
    "Signed in as {live}, but '{name}' holds {expected}.\n\n"
    "Filing this login under '{name}' would overwrite the token saved there, "
    "and that account would need a new verification email to come back. Save "
    "this login as its own account, or switch to the profile it belongs to."
)


def belongs_to(paths, provider, name, *, platform) -> bool:
    """Whether the live login is provably somebody else's than ``name``'s.

    Returns True when the two agree *or* when either side has no identity to
    compare -- a brand new profile has no expectation to violate, and a
    credential we cannot attribute is not evidence of a mismatch.
    """
    expected = state.profile_email(paths, provider, name)
    live = state.live_email(paths, provider, platform=platform)
    return not (expected and live and expected != live)


def stash_live_login(paths, provider, name, *, platform=sys.platform,
                     now_ms_fn=now_ms, sleep=time.sleep) -> None:
    """Capture whatever is logged in right now into profile ``name``.

    Refuses when the live login demonstrably belongs to a different account.
    The guard sits here rather than only in ``switch`` so that every caller
    inherits it -- this write is the one that costs a refresh token.
    """
    if not belongs_to(paths, provider, name, platform=platform):
        raise DriftedLoginError(DRIFT_REFUSAL.format(
            live=state.live_email(paths, provider, platform=platform),
            name=name,
            expected=state.profile_email(paths, provider, name)))
    paths.ensure_profile(provider.id, name)
    store = _store(paths, provider, platform)

    blob = retry.with_retry(store.read, f"read {store.describe()}", sleep=sleep)
    if blob is not None:
        _write_credential(paths, provider, name, blob, sleep=sleep)

    companion = provider.companion_read(home=paths.home)
    if companion:
        configjson.write_sidecar(paths.account(provider.id, name), companion,
                                 now_ms_fn())


def _write_credential(paths, provider, name, blob: bytes, *, sleep) -> None:
    """Write a credential into a profile, 0600, atomically.

    Retried: a running session, an antivirus scan or the Windows indexer can
    hold the file for a moment, and a single refusal is not a reason to fail
    the whole switch.
    """
    from .stores import FileStore
    destination = FileStore(paths.credentials(provider.id, name), 0o600)
    retry.with_retry(lambda: destination.write(blob),
                     f"write {paths.credentials(provider.id, name).name}",
                     sleep=sleep)


def switch(paths, provider, target_name: str, *, platform=sys.platform,
           now_ms_fn=now_ms, sleep=time.sleep):
    """Make ``target_name`` the logged-in account for one provider.

    Stashes the outgoing login, restores the incoming one, and writes the
    matching identity into the provider's companion file if it has one.
    Nothing outside the credential moves.
    """
    if provider.id == "claude":
        _refuse_legacy_layout(paths)

    current = state.inspect(paths, provider, platform=platform)

    if not paths.profile_dir(provider.id, target_name).is_dir():
        raise ProfileNotFoundError(
            f"Profile '{target_name}' no longer exists on disk.")

    # Refuse before anything moves. The copy-out below files the live login
    # under current.profile, so switching while signed in as somebody else
    # destroys that profile's token -- and the card offers the button that
    # does it, with only a warning line to say otherwise.
    if current.kind == state.DRIFTED:
        raise DriftedLoginError(DRIFT_REFUSAL.format(
            live=current.live_email, name=current.profile,
            expected=current.expected_email))

    # Refuse before anything moves if the companion cannot be parsed. Writing
    # onto an unreadable config would replace the whole file with two keys.
    # A provider with no companion has nothing to check.
    companion_path = _companion_path(provider, paths)
    if companion_path is not None:
        configjson.load_for_write(companion_path)

    stamp = now_ms_fn()
    store = _store(paths, provider, platform)

    # Everything touching the filesystem lives inside one guard, so no path
    # out of here raises a bare OSError. The GUI renders ShamblesError only;
    # anything else reaches the user as a stderr traceback and looks like the
    # switch silently did nothing.
    try:
        if companion_path is not None:
            retry.with_retry(
                lambda: configjson.backup(companion_path, paths.backup_dir, stamp),
                f"back up {companion_path.name}", sleep=sleep)

        # Stash the outgoing login so switching away is never lossy. Skipped
        # when the marker points at a profile that is already gone.
        if current.profile and paths.profile_dir(provider.id, current.profile).is_dir():
            stash_live_login(paths, provider, current.profile, platform=platform,
                             now_ms_fn=lambda: stamp, sleep=sleep)

        incoming = paths.credentials(provider.id, target_name)
        if incoming.exists():
            blob = incoming.read_bytes()
            retry.with_retry(lambda: store.write(blob),
                             f"write {store.describe()}", sleep=sleep)
        else:
            # A profile never signed into: clear the login so the vendor
            # prompts for one rather than reusing the last account.
            retry.with_retry(store.delete, f"clear {store.describe()}", sleep=sleep)

        # The marker moves with the login, not after the identity write.
        # Anything that fails below leaves the two still agreeing, so the
        # window reads the result as DRIFTED -- an identity that lags -- rather
        # than as a marker naming a profile whose login has already been
        # replaced. That second reading is the dangerous one: restash_active
        # would copy the incoming login into the outgoing profile's store and
        # destroy the account just switched away from.
        state.write_active(paths, provider.id, target_name)
    except StoreUnavailableError:
        raise
    except OSError as exc:
        raise SwitchFailedError(
            f"Could not update the login in {store.describe()}:\n{exc}\n\n"
            "Close any running sessions and try again.") from exc

    provider.companion_write(
        configjson.read_sidecar(paths.account(provider.id, target_name)),
        home=paths.home)
    return state.inspect(paths, provider, platform=platform)


def _companion_path(provider, paths):
    """Where this provider's companion file lives, or ``None`` if it has none."""
    from .providers import spec as specmod
    block = provider.spec.get("companion")
    if not block:
        return None
    return specmod.expand(block["path"], home=paths.home)


def save_current_account(paths, provider, name, *, platform=sys.platform,
                         now_ms_fn=now_ms, sleep=time.sleep) -> str:
    """Record the account that is logged in right now as a profile."""
    current = state.inspect(paths, provider, platform=platform)
    if current.kind == state.MANAGED:
        raise AlreadyManagedError(
            f"This login is already saved as '{current.profile}'.")

    store = _store(paths, provider, platform)
    if store.read() is None:
        raise AlreadyManagedError(NOTHING_TO_SAVE.format(
            store=store.describe(), provider=provider.display_name))

    name = profiles.validate_profile_name(
        name, state.profile_names(paths, provider.id))
    stash_live_login(paths, provider, name, platform=platform,
                     now_ms_fn=now_ms_fn, sleep=sleep)
    state.write_active(paths, provider.id, name)
    return name


def add_empty_account(paths, provider, name, *, platform=sys.platform,
                      now_ms_fn=now_ms, sleep=time.sleep) -> str:
    """Create a profile with no login and make it current."""
    current = state.inspect(paths, provider, platform=platform)
    store = _store(paths, provider, platform)
    if current.kind == state.UNMANAGED and store.read() is not None:
        raise AlreadyManagedError(SAVE_FIRST)

    name = profiles.validate_profile_name(
        name, state.profile_names(paths, provider.id))
    paths.ensure_profile(provider.id, name)
    result = switch(paths, provider, name, platform=platform,
                    now_ms_fn=now_ms_fn, sleep=sleep)
    return result.profile or name


def abandon_new_account(paths, provider, created: str, previous: str | None, *,
                        platform=sys.platform, now_ms_fn=now_ms,
                        sleep=time.sleep) -> bool:
    """Undo the switch that ``add_empty_account`` made, after a failed sign-in.

    Adding an account has to switch to it: the vendor writes its credential to
    the one live location, so the slot must be empty and current before the
    login runs. That leaves the user signed out of a working account for as
    long as the sign-in takes -- and permanently, if it is cancelled or fails.

    Returns True when it rolled back. The profile itself is **kept**, so the
    sign-in can be retried without naming it again.

    Refuses to roll back a profile that did acquire a credential, so a caller
    wrong about which happened cannot undo a successful login.
    """
    if not previous or previous == created:
        return False
    if not paths.profile_dir(provider.id, previous).is_dir():
        return False

    try:
        if _store(paths, provider, platform).read() is not None:
            return False
    except ShamblesError:
        return False

    switch(paths, provider, previous, platform=platform,
           now_ms_fn=now_ms_fn, sleep=sleep)
    return True


def rename_profile(paths, provider, old_name: str, new_name: str, *,
                   sleep=time.sleep) -> str:
    if not paths.profile_dir(provider.id, old_name).is_dir():
        raise ProfileNotFoundError(f"Profile '{old_name}' does not exist.")

    existing = [n for n in state.profile_names(paths, provider.id) if n != old_name]
    new_name = profiles.validate_profile_name(new_name, existing)
    if new_name == old_name:
        return old_name

    try:
        paths.profile_dir(provider.id, old_name).rename(
            paths.profile_dir(provider.id, new_name))
    except OSError as exc:
        raise SwitchFailedError(f"Could not rename the profile:\n{exc}") from exc

    if state.read_active(paths, provider.id) == old_name:
        state.write_active(paths, provider.id, new_name)
    return new_name


def remove_profile(paths, provider, name: str, *, platform=sys.platform) -> None:
    """Delete a profile directory and the login inside it.

    Irreversible in the sense that matters: the refresh token goes with it, so
    that account needs a fresh login and its verification email to come back.

    Refuses the active profile even though the UI hides the control for it.
    Hiding a button is not a safety property.
    """
    current = state.inspect(paths, provider, platform=platform)
    if name == current.profile:
        raise AlreadyManagedError(REMOVE_ACTIVE.format(name=name))

    target = paths.profile_dir(provider.id, name)
    # A name like ".." resolves outside the store. validate_profile_name
    # blocks separators on the way in, but this deletes a tree, so it
    # re-checks rather than trusting how the name arrived.
    try:
        resolved = target.resolve()
        store_root = paths.provider_dir(provider.id).resolve()
    except OSError as exc:
        raise SwitchFailedError(f"Could not resolve '{name}':\n{exc}") from exc
    if resolved.parent != store_root or resolved == store_root:
        raise ProfileNotFoundError(f"'{name}' is not a profile.")
    if not target.is_dir():
        raise ProfileNotFoundError(f"Profile '{name}' does not exist.")

    try:
        shutil.rmtree(target)
    except OSError as exc:
        raise SwitchFailedError(
            f"Could not remove '{name}':\n{exc}\n\n"
            "Close any running sessions and try again.") from exc


def forget_active_marker(paths, provider) -> None:
    """Clear a marker pointing at a profile that no longer exists."""
    state.write_active(paths, provider.id, None)


def restash_active(paths, provider, *, platform=sys.platform,
                   now_ms_fn=now_ms) -> bool:
    """Refresh the stashed copy of a rotating provider's active credential.

    Returns whether anything was written.

    Codex replaces its refresh token on every use, so a snapshot taken before
    a refresh holds a token the server has already invalidated. Restoring one
    does not fail cleanly -- it silently breaks the account until the user
    logs in again, which is the single outcome this tool exists to prevent.

    A no-op for providers whose refresh token does not rotate: Claude's live
    file drifts from the stash constantly and harmlessly, and re-stashing it
    would be pure write amplification.

    Failures are swallowed. This runs on every window refresh as a background
    correction, and a locked file is a reason to try again next time, not to
    put a dialog in front of someone who did not ask for anything.
    """
    if not provider.rotates:
        return False

    name = state.read_active(paths, provider.id)
    if not name or not paths.profile_dir(provider.id, name).is_dir():
        return False

    # Only refresh a stash from a credential that is provably this profile's.
    # This runs on every window refresh, so without the check merely opening
    # the window while signed in as someone else replaces a saved token --
    # no click, no warning, and no copy left anywhere.
    if not belongs_to(paths, provider, name, platform=platform):
        return False

    try:
        live = _store(paths, provider, platform).read()
        if live is None:
            return False
        stashed_path = paths.credentials(provider.id, name)
        if stashed_path.exists() and stashed_path.read_bytes() == live:
            return False
        _write_credential(paths, provider, name, live, sleep=time.sleep)
    except (OSError, StoreUnavailableError, SwitchFailedError):
        return False

    companion = provider.companion_read(home=paths.home)
    if companion:
        configjson.write_sidecar(paths.account(provider.id, name), companion,
                                 now_ms_fn())
    return True
