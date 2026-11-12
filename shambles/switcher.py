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
from .providers import SIGNED_OUT
from .stores.base import StoreUnavailableError

NOTHING_TO_SAVE = (
    "There is no login to save — {store} has no credentials yet.\n\n"
    "Sign in with {provider} first, then save that account here."
)

SAVE_FIRST = (
    "Save your current account first.\n\n"
    "No saved profile holds the login that is live now. It would be "
    "replaced, and you would have to sign in again to get it back."
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


#: The same refusal, reached from the bytes instead of from two addresses.
#: Worded separately because the addresses can agree while the bytes do not,
#: and "signed in as X, but this profile holds X" explains nothing.
HELD_ELSEWHERE = (
    "The login that is live now is the one saved as '{holder}', not "
    "'{name}'.\n\n"
    "Filing it under '{name}' would overwrite the token saved there, and "
    "that account would need a new verification email to come back. Switch "
    "to '{holder}' instead."
)

DRIFT_REFUSAL = (
    "Signed in as {live}, but '{name}' holds {expected}.\n\n"
    "Filing this login under '{name}' would overwrite the token saved there, "
    "and that account would need a new verification email to come back. Save "
    "this login as its own account, or switch to the profile it belongs to."
)


def belongs_to(paths, provider, name, *, platform) -> bool:
    """Whether the live login may be filed under ``name``.

    False only when it is provably somebody else's. Returns True when the two
    agree *or* when either side has no identity to compare -- a brand new
    profile has no expectation to violate, and a credential we cannot
    attribute is not evidence of a mismatch.
    """
    # A credential identical to this profile's stash is this profile's login,
    # whatever the vendor's config file currently says about it. Without this
    # a running Claude Code session could rewrite that file and have Shambles
    # refuse to re-stash a login it had just installed itself.
    holders = state.holders_of_live_credential(paths, provider,
                                               platform=platform)
    if name in holders:
        return True
    # And one identical to another profile's stash is that profile's login,
    # for the same reason. The address cannot be asked here: a switch that
    # stopped after replacing the credential leaves the old account's address
    # on file beside the new account's token, and the two then agree.
    if holders:
        return False
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
    store = _store(paths, provider, platform)
    blob = retry.with_retry(store.read, f"read {store.describe()}", sleep=sleep)
    if not blob:
        # Nobody is signed in, so there is nothing to file and no login for
        # an identity to describe: whatever the vendor's config names is left
        # over from some other moment, and the profile keeps what it had.
        #
        # Empty counts as absent. Neither vendor replaces its credential file
        # atomically, so a read can land between the truncate and the write
        # and see nothing at all. Filing those zero bytes replaced the saved
        # token with an empty file.
        return

    expected = state.profile_email(paths, provider, name)
    live = state.live_email(paths, provider, platform=platform)
    if not belongs_to(paths, provider, name, platform=platform):
        holder = state.holder_of_live_credential(paths, provider,
                                                 platform=platform)
        if holder:
            raise DriftedLoginError(HELD_ELSEWHERE.format(
                holder=holder, name=name))
        raise DriftedLoginError(DRIFT_REFUSAL.format(
            live=live, name=name, expected=expected))
    paths.ensure_profile(provider.id, name)
    _write_credential(paths, provider, name, blob, sleep=sleep)

    # The identity filed beside a credential is only ever replaced by the
    # same identity, refreshed. The vendor's config file is not the
    # credential: it can name no account at all, or -- rewritten from memory
    # by a session still running as someone else -- the wrong one, while
    # belongs_to has just established from the bytes that this login is
    # ``name``'s. Filing either would leave the profile mislabelled or
    # unlabelled, and an unlabelled profile is one the drift check can no
    # longer protect.
    companion = provider.companion_read(home=paths.home)
    if companion and not (expected and live != expected):
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

    # Refuse before anything moves. Whatever is live is about to be replaced,
    # so it has to have somewhere to go first.
    outgoing = _outgoing_profile(paths, provider, current, platform=platform)

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

        # Stash the outgoing login so switching away is never lossy. Only
        # under the marked profile. Any other answer from _outgoing_profile
        # is a profile that already holds these exact bytes, so there is
        # nothing to copy -- and the one thing a stash would still do is file
        # the address from the vendor's config beside them. When the marker
        # is wrong that address usually is too: it would label the incoming
        # account's profile with the outgoing account's name.
        if outgoing and outgoing == current.profile:
            stash_live_login(paths, provider, outgoing, platform=platform,
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
        # Anything that fails below leaves the two still agreeing: the marked
        # profile holds the live bytes, which inspect() reads as MANAGED
        # whatever the address on file says, and running the switch again
        # redoes the identity write. The other order would leave a marker
        # naming a profile whose login has already been replaced, and that
        # is the dangerous one: restash_active would copy the incoming login
        # into the outgoing profile's store and destroy the account just
        # switched away from.
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


def _outgoing_profile(paths, provider, current, *, platform) -> str | None:
    """The profile the live login belongs under before it is replaced.

    Raises while the store holds a login that no saved profile could take:
    every caller is about to write over it, and a login filed nowhere is
    gone. ``None`` means there is no such profile and nothing to lose.

    The marker is only the second thing asked. A saved profile holding these
    exact bytes owns them whatever the marker says, and they are already
    safe there -- which is also what lets a switch that stopped between
    replacing the credential and moving the marker be finished by simply
    running it again.
    """
    live = _store(paths, provider, platform).read()
    holders = state.holders_of_live_credential(paths, provider,
                                               platform=platform)
    if holders:
        return current.profile if current.profile in holders else holders[0]

    marked = (current.profile
              if current.kind in (state.MANAGED, state.DRIFTED) else None)
    if not live:
        # Nobody is signed in, so nothing is at stake whatever the address
        # left in the vendor's config says. The marked profile is still
        # where the user was, for a caller that wants to come back to it.
        return marked

    # The copy-out files the live login under current.profile, so switching
    # while signed in as somebody else destroys that profile's token -- and
    # the card offers the button that does it, with only a warning line to
    # say otherwise.
    if current.kind == state.DRIFTED:
        raise DriftedLoginError(DRIFT_REFUSAL.format(
            live=current.live_email, name=current.profile,
            expected=current.expected_email))
    if marked:
        return marked

    # No profile is marked, or the marked one is gone from disk, so there is
    # nowhere to file a login and one that exists must be saved first. A
    # credential the vendor has emptied is not one: it cannot sign in, and
    # asking for it to be saved would mean saving a profile that is dead on
    # arrival.
    if provider.liveness(live, now_ms=now_ms()).state != SIGNED_OUT:
        raise AlreadyManagedError(SAVE_FIRST)
    return None


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

    # Not marked, but already here: a profile holds these exact bytes. A
    # second copy under a new name would only be a second card for one
    # login, and refusing would leave the Save control doing nothing in
    # exactly the state it is offered for. What is missing is the marker, so
    # that is what gets written, and the name that comes back is the one the
    # login was already saved under.
    holder = state.holder_of_live_credential(paths, provider, platform=platform)
    if holder:
        state.write_active(paths, provider.id, holder)
        return holder

    name = profiles.validate_profile_name(
        name, state.profile_names(paths, provider.id))
    stash_live_login(paths, provider, name, platform=platform,
                     now_ms_fn=now_ms_fn, sleep=sleep)
    state.write_active(paths, provider.id, name)
    return name


def add_empty_account(paths, provider, name, *, platform=sys.platform,
                      now_ms_fn=now_ms, sleep=time.sleep) -> str:
    """Create a profile with no login and make it current.

    The switch decides whether that is safe -- it clears the live slot, so
    it refuses a login that no profile holds -- and a refusal takes the new
    directory back out with it. Left behind, it is a blank card whose name
    cannot be used for the retry.
    """
    name = profiles.validate_profile_name(
        name, state.profile_names(paths, provider.id))
    paths.ensure_profile(provider.id, name)
    try:
        result = switch(paths, provider, name, platform=platform,
                        now_ms_fn=now_ms_fn, sleep=sleep)
    except ShamblesError:
        # Only while it is not the live profile: a switch that failed after
        # moving the marker has made this directory the active one.
        if state.read_active(paths, provider.id) != name:
            try:
                paths.profile_dir(provider.id, name).rmdir()
            except OSError:
                pass  # not empty, or already gone: leave it for the user
        raise
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

    Anything at all in the live slot counts as that credential, even bytes
    the profile already holds: a second window refreshing a rotating
    provider can have filed the vendor's new login under ``created`` before
    this runs. Past that check the question is the one
    :func:`abandon_relogin` answers, so it is asked there. That function also
    checks ``created`` is still the live profile, which this one used not to
    -- a cancelled Add could switch the user off whatever they had moved to
    in another window.
    """
    try:
        if _store(paths, provider, platform).read() is not None:
            return False
    except ShamblesError:
        return False
    return abandon_relogin(paths, provider, created, previous,
                           platform=platform, now_ms_fn=now_ms_fn, sleep=sleep)


#: What :func:`judge_relogin` found in the live slot after a vendor login.
RENEWED = "renewed"
UNCHANGED = "unchanged"
OTHER_ACCOUNT = "other_account"


def begin_relogin(paths, provider, name: str, *, platform=sys.platform,
                  now_ms_fn=now_ms, sleep=time.sleep) -> str | None:
    """Make ``name`` live so the vendor's login can fill it.

    Returns the profile the live login was filed under, which is what
    :func:`abandon_relogin` puts back if the sign-in comes to nothing. When
    ``name`` already is the live profile nothing moves and ``name`` comes back.

    Refuses, as ``switch`` does, when the vendor holds a login that no saved
    profile could take: it would be overwritten and kept nowhere.
    """
    if not paths.profile_dir(provider.id, name).is_dir():
        raise ProfileNotFoundError(f"Profile '{name}' no longer exists on disk.")

    current = state.inspect(paths, provider, platform=platform)
    if current.kind == state.MANAGED and current.profile == name:
        return name

    previous = _outgoing_profile(paths, provider, current, platform=platform)
    switch(paths, provider, name, platform=platform, now_ms_fn=now_ms_fn,
           sleep=sleep)
    return previous


def judge_relogin(paths, provider, name: str, *, platform=sys.platform,
                  now_ms_fn=now_ms) -> str:
    """What the vendor's login left in the live slot, judged against ``name``.

    :data:`UNCHANGED` when nothing usable arrived: no credential, no token in
    it, or a token whose window is itself closed. A vendor that exits 0
    without writing leaves the dead token exactly where ``begin_relogin`` put
    it, and that must not read as a success.

    :data:`OTHER_ACCOUNT` when the new login is provably somebody else's --
    the browser was already signed in to a different account. Saving it would
    overwrite ``name``'s stash with that account's token.
    """
    blob = _store(paths, provider, platform).read()
    if (blob is None or not provider.has_login(blob)
            or provider.liveness(blob, now_ms=now_ms_fn()).needs_login):
        return UNCHANGED
    if not belongs_to(paths, provider, name, platform=platform):
        return OTHER_ACCOUNT
    return RENEWED


def abandon_relogin(paths, provider, name: str, previous: str | None, *,
                    platform=sys.platform, now_ms_fn=now_ms,
                    sleep=time.sleep) -> bool:
    """Put the user back on ``previous`` after a re-login that produced nothing.

    A lapsed profile's switch leaves its dead token in the slot, so "the slot
    is empty" is not the test: the slot must hold nothing the profile does not
    already have.

    Returns True when it switched back. Touches nothing, and returns False,
    unless ``name`` is still the live profile and the live credential is
    exactly what ``name`` already holds (or nothing at all). Anything else
    means the vendor wrote a new login, and switching away would throw it out.
    """
    if not previous or previous == name:
        return False
    if not paths.profile_dir(provider.id, previous).is_dir():
        return False
    if state.read_active(paths, provider.id) != name:
        return False

    try:
        live = _store(paths, provider, platform).read()
        if live is not None and (
                paths.credentials(provider.id, name).read_bytes() != live):
            return False
    except (ShamblesError, OSError):
        return False

    switch(paths, provider, previous, platform=platform, now_ms_fn=now_ms_fn,
           sleep=sleep)
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

    Active means the marker names it, *or* it is the only profile holding
    the live credential. The second matters when marker and store disagree:
    its stash is then the only thing showing whose login is live, and with it
    gone the next switch would file that login under whichever profile the
    marker names. A second profile holding the same bytes is a duplicate,
    and removing the one that is not marked loses nothing.
    """
    current = state.inspect(paths, provider, platform=platform)
    holders = state.holders_of_live_credential(paths, provider,
                                               platform=platform)
    if name == current.profile or holders == [name]:
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

    try:
        # Only refresh a stash from a credential that is provably this
        # profile's. This runs on every window refresh, so without the check
        # merely opening the window while signed in as someone else replaces
        # a saved token -- no click, no warning, and no copy left anywhere.
        # Inside the guard, because it reads the store too.
        if not belongs_to(paths, provider, name, platform=platform):
            return False

        live = _store(paths, provider, platform).read()
        if not live:
            # Absent, or empty: a read that landed between the vendor's
            # truncate and its write. This runs on every refresh, so filing
            # that would empty the saved token with no click at all.
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
