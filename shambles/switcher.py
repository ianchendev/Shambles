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
from dataclasses import dataclass

from . import configjson, migrate, profiles, state
from .errors import (AlreadyManagedError, DriftedLoginError,
                     ProfileNotFoundError, ShamblesError, SwitchFailedError)
from .providers import SIGNED_OUT
from .providers import Identity
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

    In that layout ``~/.claude`` is a symlink *into* a profile directory, so
    writing the live credential would write through the link and corrupt the
    very profile the switch is trying to leave. The GUI migrates on startup,
    so this should be unreachable there -- it is here because a half-applied
    switch on that layout is unrecoverable.

    The test is :func:`migrate.needed`, the same one the migration itself
    uses, not a bare ``is_symlink``. A link the user made themselves, to a
    dotfiles checkout or another drive, points at no profile: there is
    nothing to corrupt and nothing to migrate, so refusing it would refuse
    every switch for good.

    Claude-only: the pre-1.0 layout predates every other provider.
    """
    if migrate.needed(paths):
        raise SwitchFailedError(MIGRATION_REQUIRED)


def now_ms() -> int:
    return int(time.time() * 1000)


# ``sleep`` is still accepted by the functions below and no longer used. It
# fed a retry wrapper that was removed (owner decision D5): a retried write
# waits out whatever held the file and then overwrites what that program
# wrote, from a copy taken before the wait -- a rotated token, if the program
# was the vendor. Kept in the signatures so existing callers need no change.


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


#: "The caller did not hand over the bytes", as distinct from None, which
#: is what an empty store reads as.
_UNREAD = object()


def belongs_to(paths, provider, name, *, platform, blob=_UNREAD) -> bool:
    """Whether the live login may be filed under ``name``.

    False only when it is provably somebody else's. Returns True when the two
    agree *or* when either side has no identity to compare -- a brand new
    profile has no expectation to violate, and a credential we cannot
    attribute is not evidence of a mismatch.

    ``blob`` is the credential the caller has read and is about to file.
    Every question here is asked of those bytes and never of a second read
    of the store: a store that is busy for one read and free for the next
    would otherwise answer about a different moment than the one being
    written, and "could not read it" is not "it has no identity". Without
    ``blob`` the store is read here, and a store that cannot be read raises.
    """
    if blob is _UNREAD:
        blob = _store(paths, provider, platform).read()

    # A credential identical to this profile's stash is this profile's login,
    # whatever the vendor's config file currently says about it. Without this
    # a running Claude Code session could rewrite that file and have Shambles
    # refuse to re-stash a login it had just installed itself.
    holders = state.proven_owners(paths, provider, blob)
    if name in holders:
        return True
    # And one identical to another profile's stash, or continuing its
    # lineage, is that profile's login, for the same reason. The address
    # cannot be asked here: a switch that stopped after replacing the
    # credential leaves the old account's address on file beside the new
    # account's token, and the two then agree.
    if holders:
        return False
    return not state.disagree(state.profile_identity(paths, provider, name),
                              _identity_of(paths, provider, blob))


def _identity_of(paths, provider, blob):
    """Whose login these bytes are, as far as the provider can say.

    Empty for an empty store: with nobody signed in, an address left in the
    vendor's config describes nobody.
    """
    if not blob:
        return Identity()
    return provider.identity(blob, home=paths.home, active=True)


def _may_file_identity(expected, live) -> bool:
    """Whether the vendor's account details may be filed as a profile's own.

    Only the same identity, refreshed. Never over one it disagrees with,
    never one with no address over one that has it, and never an
    organisation onto a profile saved before organisations were recorded:
    the config naming one may have been rewritten by a session in another
    organisation, and once filed the mismatch would read as known.
    """
    if state.disagree(expected, live):
        return False
    if expected.email and live.email != expected.email:
        return False
    return not (expected.email and not expected.account and live.account)


def stash_live_login(paths, provider, name, *, platform=sys.platform,
                     now_ms_fn=now_ms, sleep=time.sleep) -> None:
    """Capture whatever is logged in right now into profile ``name``.

    Refuses when the live login demonstrably belongs to a different account.
    The guard sits here rather than only in ``switch`` so that every caller
    inherits it -- this write is the one that costs a refresh token.
    """
    store = _store(paths, provider, platform)
    blob = store.read()
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

    # Everything from here on is decided about the bytes just read, not
    # about whatever a second read of the store would return.
    expected = state.profile_identity(paths, provider, name)
    live = _identity_of(paths, provider, blob)
    if not belongs_to(paths, provider, name, platform=platform, blob=blob):
        holders = state.proven_owners(paths, provider, blob)
        if holders:
            raise DriftedLoginError(HELD_ELSEWHERE.format(
                holder=holders[0], name=name))
        raise DriftedLoginError(DRIFT_REFUSAL.format(
            live=state.describe(live, expected), name=name,
            expected=state.describe(expected, live)))
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
    if companion and _may_file_identity(expected, live):
        configjson.write_sidecar(paths.account(provider.id, name), companion,
                                 now_ms_fn())


def _write_credential(paths, provider, name, blob: bytes, *, sleep) -> None:
    """Write a credential into a profile, 0600, atomically.

    Through :func:`profiles.save_credential`, which keeps the login it
    replaces.
    """
    profiles.save_credential(paths, provider, name, blob)


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
    outgoing = _outgoing_profile(paths, provider, current, platform=platform,
                                 target=target_name)

    # Refuse before anything moves if the companion cannot be parsed. Writing
    # onto an unreadable config would replace the whole file with two keys.
    # A provider with no companion has nothing to check.
    companion_path = _companion_path(provider, paths)
    if companion_path is not None:
        configjson.load_for_write(companion_path)

    stamp = now_ms_fn()
    store = _store(paths, provider, platform)

    # The vendor's own refresh lock, held from before the outgoing login is
    # read until the incoming one is in place. A refresh already in flight
    # lands first, so the token stashed is the one it was given rather than
    # the one it just spent. See _hold_refresh_locks.
    held = _hold_refresh_locks(provider, paths)

    # Everything touching the filesystem lives inside one guard, so no path
    # out of here raises a bare OSError. The GUI renders ShamblesError only;
    # anything else reaches the user as a stderr traceback and looks like the
    # switch silently did nothing.
    try:
        if companion_path is not None:
            configjson.backup(companion_path, paths.backup_dir, stamp)

        # Stash the outgoing login so switching away is never lossy, except
        # under a profile other than the marked one that already holds these
        # exact bytes. There is nothing to copy then, and the one thing a
        # stash would still do is file the address from the vendor's config
        # beside them: when the marker is wrong that address usually is too.
        # A profile whose login this *continues* (refreshed since it was
        # saved) does need the copy -- its own stash is now a spent token.
        exact = state.profiles_holding(paths, provider.id, store.read())
        if outgoing and (outgoing == current.profile or outgoing not in exact):
            stash_live_login(paths, provider, outgoing, platform=platform,
                             now_ms_fn=lambda: stamp, sleep=sleep)

        incoming = paths.credentials(provider.id, target_name)
        if incoming.exists():
            store.write(incoming.read_bytes())
        else:
            # A profile never signed into: clear the login so the vendor
            # prompts for one rather than reusing the last account.
            store.delete()

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
    finally:
        _release(held)

    provider.companion_write(
        configjson.read_sidecar(paths.account(provider.id, target_name)),
        home=paths.home)
    return state.inspect(paths, provider, platform=platform)


#: How long a switch waits for the vendor to finish a refresh in flight.
#: Claude Code gives up on its own request after 30 seconds.
REFRESH_LOCK_WAIT_S = 15.0

REFRESH_IN_PROGRESS = (
    "Claude Code is renewing this login right now.\n\n"
    "Try again in a moment. Nothing was changed."
)


def _hold_refresh_locks(provider, paths) -> list:
    """Take the lock the vendor refreshes under, waiting for it if held.

    Claude Code posts its refresh token, the server spends it at once, and
    the new one is saved only if the stored token is still the one posted.
    A switch landing in between stashed the spent token and replaced the
    stored one, so the save was refused and the new token was lost with the
    process. Holding the same lock makes a refresh in flight land first.

    A lock not touched for the vendor's stale interval belongs to a client
    that died; it is cleared, as the vendor itself would. One that is still
    held after ``REFRESH_LOCK_WAIT_S`` refuses the switch, before anything
    has moved. A lock that cannot be created at all -- no config directory,
    nothing to coordinate with -- is skipped.
    """
    block = provider.spec.get("refresh_lock") or {}
    stale_s = block.get("stale_ms", 60_000) / 1000
    held = []
    deadline = time.monotonic() + REFRESH_LOCK_WAIT_S
    try:
        for lock in provider.refresh_locks(home=paths.home):
            while True:
                try:
                    lock.mkdir()
                    held.append(lock)
                    break
                except FileExistsError:
                    try:
                        age = time.time() - lock.stat().st_mtime
                    except FileNotFoundError:
                        continue          # released while we looked
                    if age > stale_s:
                        try:
                            lock.rmdir()
                        except OSError:
                            pass
                        continue
                    if time.monotonic() >= deadline:
                        raise SwitchFailedError(REFRESH_IN_PROGRESS)
                    time.sleep(0.05)
                except OSError:
                    break                 # nowhere to put it: no client there
    except BaseException:
        _release(held)
        raise
    return held


def _release(held) -> None:
    for lock in reversed(held):
        try:
            lock.rmdir()
        except OSError:
            pass


def _outgoing_profile(paths, provider, current, *, platform,
                      target=None) -> str | None:
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
    holders = state.proven_owners(paths, provider, live)
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
    # Unless the switch is *to* the profile whose address the live login
    # carries. Nothing proves it is that account's login, but the user has
    # just said so: it is what the notice tells them to do, and the login
    # is filed there with the one it replaces kept beside it.
    if (current.kind == state.DRIFTED and target is not None
            and target == state.owner_by_address(paths, provider,
                                                 platform=platform)):
        return target
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
    return provider.companion_path(home=paths.home)


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
    if not belongs_to(paths, provider, name, platform=platform, blob=blob):
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


#: Adding an account brought back a login that is already saved under
#: another name -- the browser was still signed in to that account.
DUPLICATE = "duplicate"


def judge_new_login(paths, provider, name: str, *, platform=sys.platform,
                    now_ms_fn=now_ms) -> str:
    """What the vendor's login left in the live slot for a brand new profile.

    :func:`judge_relogin` cannot answer this. A new profile has no address to
    compare against, so a login for somebody already saved reads as a match,
    and filing it would leave two profiles holding one account under
    different names -- reported to the user as the new account they asked for.
    """
    blob = _store(paths, provider, platform).read()
    if (blob is None or not provider.has_login(blob)
            or provider.liveness(blob, now_ms=now_ms_fn()).needs_login):
        return UNCHANGED
    # Proof or address: this only refuses to file a second copy of a saved
    # account under a new name, and the vendor has just written the address.
    owner = (state.owner_of_live(paths, provider, platform=platform)
             or state.owner_by_address(paths, provider, platform=platform))
    if owner and owner != name:
        return DUPLICATE
    return RENEWED


@dataclass(frozen=True)
class LoginOutcome:
    """Where a vendor login left the user, for a frontend to put into words."""

    #: :data:`RENEWED`, :data:`UNCHANGED`, :data:`OTHER_ACCOUNT` or
    #: :data:`DUPLICATE`.
    kind: str
    profile: str
    previous: str | None = None
    #: True when the user was put back on ``previous``.
    restored: bool = False
    #: The saved profile the new login belongs to, when it is somebody else's.
    owner: str | None = None
    live_email: str | None = None
    expected_email: str | None = None


def settle_login(paths, provider, name: str, previous: str | None, *,
                 adding: bool, succeeded: bool, platform=sys.platform,
                 now_ms_fn=now_ms, sleep=time.sleep) -> LoginOutcome:
    """Decide what a finished vendor login means, and act on it.

    Every frontend runs the vendor's command and then lands here, so that
    each one files, refuses and rolls back identically. Before this the
    terminal UI saved whatever it found and stayed put otherwise, which left a
    cancelled sign-in on a dead account with the working one signed out.

    ``succeeded`` is the vendor's clean exit. A failed or cancelled login is
    judged as :data:`UNCHANGED` without reading the slot, and rolled back the
    same way; the rollback functions themselves refuse to discard a login the
    vendor did write, so a cancel that raced a successful write keeps it.

    - :data:`RENEWED`: filed under ``name``.
    - :data:`OTHER_ACCOUNT` / :data:`DUPLICATE`: nothing is filed under
      ``name``. When the login belongs to a saved profile the marker moves to
      it, which is a relabelling of what is already live; otherwise the login
      stays live and unsaved for the user to save or replace.
    - :data:`UNCHANGED`: the user goes back to ``previous`` when that is safe.
    """
    kind = UNCHANGED
    # Somebody switched away while the vendor ran. Whatever is live now is
    # not this sign-in's to judge, and the rollback below refuses to move.
    if succeeded and state.read_active(paths, provider.id) == name:
        judge = judge_new_login if adding else judge_relogin
        kind = judge(paths, provider, name, platform=platform,
                     now_ms_fn=now_ms_fn)

    if kind == RENEWED:
        stash_live_login(paths, provider, name, platform=platform,
                         now_ms_fn=now_ms_fn, sleep=sleep)
        return LoginOutcome(RENEWED, name, previous)

    if kind in (OTHER_ACCOUNT, DUPLICATE):
        # A relabelling, after a sign-in the user has just made and whose
        # address the vendor has just written: the marker only, no login is
        # filed anywhere.
        owner = (state.owner_of_live(paths, provider, platform=platform)
                 or state.owner_by_address(paths, provider,
                                           platform=platform))
        if owner == name:
            owner = None
        if owner:
            state.write_active(paths, provider.id, owner)
        return LoginOutcome(
            kind, name, previous, owner=owner,
            live_email=state.live_email(paths, provider, platform=platform),
            expected_email=state.profile_email(paths, provider, name))

    abandon = abandon_new_account if adding else abandon_relogin
    try:
        restored = abandon(paths, provider, name, previous, platform=platform,
                           now_ms_fn=now_ms_fn, sleep=sleep)
    except ShamblesError:
        restored = False
    return LoginOutcome(UNCHANGED, name, previous, restored=restored)


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


def adopt_live_owner(paths, provider, *, platform=sys.platform) -> str | None:
    """Point the marker at the saved account that is actually signed in.

    A token lapses, the user signs in again in the browser, and the machine is
    now on a different account than the marker names. If that account is one
    of the saved ones the marker is simply stale. Left alone, every frontend
    shows the wrong account as active, and ``switch`` refuses to move to the
    right one with a message telling the user to do exactly that.

    Moves the marker and nothing else: no credential is read into a profile
    or written anywhere, so it stays reversible by switching back. A login
    nobody saved is left for the user to name. Returns the profile adopted,
    or ``None`` when nothing moved. An unreadable store is not a reason to
    move anything.
    """
    try:
        current = state.inspect(paths, provider, platform=platform)
        if current.kind != state.DRIFTED:
            return None
        owner = state.owner_of_live(paths, provider, platform=platform)
    except ShamblesError:
        return None
    if not owner or owner == current.profile:
        return None
    state.write_active(paths, provider.id, owner)
    return owner


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
        live = _store(paths, provider, platform).read()
        if not live:
            # Absent, or empty: a read that landed between the vendor's
            # truncate and its write. This runs on every refresh, so filing
            # that would empty the saved token with no click at all.
            return False

        # Only refresh a stash from a credential that is provably this
        # profile's: the same login, refreshed. This runs on every refresh of
        # every interface, with no click, so an address is not enough -- a
        # session still running rewrites it from memory, and a half-written
        # config names nobody. Either way another account's token would be
        # filed here, and the copy made would then pass for proof.
        stashed_path = paths.credentials(provider.id, name)
        try:
            saved = stashed_path.read_bytes()
        except FileNotFoundError:
            return False
        if saved == live or not (provider.has_login(live)
                                 and provider.same_login(saved, live)):
            return False
        expected = state.profile_identity(paths, provider, name)
        address = _identity_of(paths, provider, live)
        _write_credential(paths, provider, name, live, sleep=time.sleep)
    except (OSError, StoreUnavailableError, SwitchFailedError):
        return False

    # The same rule stash_live_login follows: the identity filed beside a
    # login is only replaced by the same identity, refreshed. The lineage
    # proves the token is this profile's; it says nothing about which account
    # the vendor's config file names right now.
    companion = provider.companion_read(home=paths.home)
    if companion and _may_file_identity(expected, address):
        configjson.write_sidecar(paths.account(provider.id, name), companion,
                                 now_ms_fn())
    return True
