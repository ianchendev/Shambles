"""Structured data exchanged by the application service boundary."""

from dataclasses import asdict, dataclass
import os
import threading

from .. import eject as eject_mod
from .. import login
from .. import migrate as migrate_mod
from .. import settings as settings_mod
from .. import state
from .. import switcher
from .. import usage as usage_mod
from ..errors import (AlreadyManagedError, ConfigUnreadableError,
                      DriftedLoginError, ProfileNotFoundError, ShamblesError)
from ..stores.base import StoreUnavailableError
from ..stores.fallback import FallbackStore
from ..stores.file import FileStore
from ..stores.unsupported import UnsupportedStore
from . import snapshot as snapshot_mod
from .snapshot import Snapshot


#: What a frontend says while a switch waits for the vendor's refresh lock.
#: The wait is :data:`shambles.switcher.REFRESH_LOCK_WAIT_S` at most.
WAITING_FOR_REFRESH = (
    "Waiting for Claude Code to finish renewing its login, so the new token "
    "is the one saved. This usually takes a few seconds; Shambles gives up "
    "after {seconds:.0f} s. Nothing has changed yet."
)


def waiting_for_refresh() -> str:
    return WAITING_FOR_REFRESH.format(seconds=switcher.REFRESH_LOCK_WAIT_S)


ERROR_CODES = {
    login.LoginUnavailableError: (
        "login_unavailable", "Install the vendor CLI and retry."),
    ProfileNotFoundError: (
        "profile_missing", "Choose an account that still exists."),
    AlreadyManagedError: (
        "active_profile_protected", "Switch away before removing it."),
    ConfigUnreadableError: (
        "companion_unreadable", "Repair the vendor configuration and retry."),
    StoreUnavailableError: (
        "store_unavailable", "Unlock or restore the credential store."),
}


@dataclass(frozen=True)
class ActionError:
    code: str
    message: str
    recovery: str = ""


@dataclass(frozen=True)
class ActionPlan:
    action: str
    provider: str | None
    account: str | None
    requires_confirmation: bool
    prompt: str
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class ActionResult:
    ok: bool
    action: str
    summary: str = ""
    warnings: tuple[str, ...] = ()
    snapshot: Snapshot | None = None
    error: ActionError | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "action": self.action,
            "summary": self.summary,
            "warnings": list(self.warnings),
            "snapshot": (snapshot_mod.to_dict(self.snapshot)
                         if self.snapshot else None),
            "error": (asdict(self.error) if self.error else None),
        }


@dataclass(frozen=True)
class MigrationNotice:
    """What a startup migration did, for a frontend to show once.

    Migrations are not offered as a choice, so the notice is the only moment
    the user learns anything moved. ``ok`` False means it could not run and
    ``message`` says why; the old layout is then still in place.
    """

    code: str
    message: str
    ok: bool = True


class LoginHandle:
    def __init__(self, process, completed, cancelled=None):
        self._process = process
        self._completed = completed
        self._cancelled = cancelled or threading.Event()

    def cancel(self):
        # Set first: the vendor's exit is reported from its own thread, and a
        # cancel has to read as a cancel there, not as a failed login.
        self._cancelled.set()
        if self._process is not None:
            self._process.cancel()

    def wait(self, timeout=None):
        return self._completed.wait(timeout)

    @property
    def running(self):
        return self._process is not None and self._process.running


#: What every non-URL vendor line becomes. Named rather than inlined because
#: a frontend has to recognise it to render it as progress instead of as
#: content: three of these in a row is the normal shape of a working login,
#: and repeating the literal text at the user reads as a malfunction.
HIDDEN_LINE = "[vendor output hidden]"


def _safe_login_line(line):
    # Vendor stdout has no stable schema and can contain credentials under
    # spellings Shambles cannot enumerate safely. The one documented value a
    # caller needs is a supported sign-in URL, checked by the login layer;
    # everything else becomes a fixed progress message.
    return login.authorization_url(line) or HIDDEN_LINE


def _reads_only_files(store) -> bool:
    """Whether reading ``store`` touches nothing but files.

    Anything not known to be a file counts as not, so a store added later
    is kept off the automatic path until someone says otherwise.
    """
    return isinstance(store, (FileStore, UnsupportedStore))


def _files_of(store) -> list:
    """The files behind a store, for watching. Never reads the store."""
    if isinstance(store, FileStore):
        return [store.path]
    if isinstance(store, FallbackStore):
        return _files_of(store.primary) + _files_of(store.fallback)
    return []


class _Recorded:
    """A store whose every read is remembered for :meth:`refresh_files`."""

    def __init__(self, real, memory, key):
        self._real, self._memory, self._key = real, memory, key

    def read(self):
        try:
            blob = self._real.read()
        except Exception as exc:
            self._memory[self._key] = (False, exc)
            raise
        self._memory[self._key] = (True, blob)
        return blob

    def __getattr__(self, name):
        return getattr(self._real, name)


class _Remembered:
    """A store answered from the last explicit read, without touching it."""

    def __init__(self, real, outcome):
        self._real, self._outcome = real, outcome

    def read(self):
        ok, value = self._outcome
        if not ok:
            raise value
        return value

    def write(self, payload):
        raise StoreUnavailableError("A files-only refresh never writes.")

    def delete(self):
        raise StoreUnavailableError("A files-only refresh never writes.")

    def describe(self):
        return self._real.describe()


def _with_store(provider, wrap):
    """``provider``, its ``store()`` answered through ``wrap``.

    A shallow copy rather than a proxy: code that rebuilds a provider from
    ``type(provider)`` must still get the real class.
    """
    import copy
    twin = copy.copy(provider)
    real = provider.store

    def store(*, home, platform):
        return wrap(real(home=home, platform=platform))

    twin.store = store
    return twin


class ShamblesService:
    def __init__(self, *, paths, providers, platform,
                 clock_ms=switcher.now_ms):
        self.paths = paths
        self.providers = tuple(providers)
        self.platform = platform
        self.clock_ms = clock_ms
        #: provider id -> (ok, bytes or exception): the last explicit read of
        #: each store that is not a plain file. What refresh_files() answers
        #: from, so nothing automatic ever reaches the Keychain.
        self._remembered = {}
        #: provider id -> newest session log, found at the last read. Kept so
        #: watch_signature() never walks the session tree; a log started
        #: since is found by the next read (the minute timer at the latest).
        self._session_logs = {}
        #: provider id -> who the vendor's own files named at the last
        #: explicit read, for each provider answered from memory above.
        self._file_identity = {}

    def _identity_in_files(self, provider):
        """Who the vendor's files say is signed in, without its store.

        Claude Code writes the account into ``~/.claude.json`` at sign-in,
        so a sign-in made outside Shambles shows there even when the token
        itself is in the Keychain. None for a provider with no such file.
        """
        from .. import configjson
        try:
            where = provider.companion_path(home=self.paths.home)
        except Exception:
            return None
        if where is None:
            return None
        account = configjson.load(where).get("oauthAccount")
        if not isinstance(account, dict):
            return ()
        return tuple(account.get(key) for key in
                     ("accountUuid", "emailAddress", "organizationUuid"))

    def _find_session_logs(self):
        from ..providers import spec as specmod
        for provider in self.providers:
            if provider.id != "codex":
                continue
            try:
                self._session_logs[provider.id] = usage_mod.latest_codex_session(
                    specmod.config_dir(provider.spec, home=self.paths.home,
                                       env=getattr(provider, "env", None)))
            except Exception:
                self._session_logs.pop(provider.id, None)

    def _provider(self, provider_id):
        try:
            return next(p for p in self.providers if p.id == provider_id)
        except StopIteration:
            raise KeyError(provider_id)

    def snapshot(self):
        """Read everything, stores included, and remember what they said."""
        def recorded(provider):
            def wrap(store):
                if _reads_only_files(store):
                    return store
                return _Recorded(store, self._remembered, provider.id)
            return _with_store(provider, wrap)

        self._find_session_logs()
        for provider in self.providers:
            self._file_identity[provider.id] = self._identity_in_files(provider)
        return snapshot_mod.build(
            paths=self.paths,
            providers=[recorded(p) for p in self.providers],
            platform=self.platform, now_ms=self.clock_ms())

    def refresh_files(self):
        """Re-read what the vendors wrote, from files only (U2).

        For everything nobody asked for: the window regaining focus, a file
        changing, the minute timer. Reading the macOS Keychain on a timer
        raises password prompts, so a store that is not a plain file is
        answered with what it said at the last explicit read (Refresh, a
        switch, a sign-in). With no such read yet there is no answer, and
        guessing "empty" would show the live account as signed out, so this
        then returns no snapshot at all.

        Writes nothing but the usage sidecar, as :meth:`refresh` does: no
        adoption, no re-stash. Those read the live store and move bytes, and
        stay behind an explicit action.
        """
        wrapped = []
        for provider in self.providers:
            try:
                store = provider.store(home=self.paths.home,
                                       platform=self.platform)
            except Exception:
                store = None
            if store is not None and not _reads_only_files(store):
                if provider.id not in self._remembered:
                    return ActionResult(True, "refresh_files")
                # Signed in outside Shambles: the files name somebody new
                # while the remembered store answer is the old token. A
                # snapshot from both would be neither state, so none.
                if (self._identity_in_files(provider)
                        != self._file_identity.get(provider.id)):
                    return ActionResult(False, "refresh_files", error=ActionError(
                        "changed_outside",
                        f"{provider.display_name}'s login changed outside "
                        "Shambles.",
                        "Press Refresh to read it."))
            outcome = self._remembered.get(provider.id)
            wrapped.append(_with_store(
                provider,
                lambda real, outcome=outcome: (
                    real if _reads_only_files(real) or outcome is None
                    else _Remembered(real, outcome))))

        for provider in self.providers:
            try:
                usage_mod.capture_live(
                    self.paths, provider.id,
                    state.read_active(self.paths, provider.id),
                    now_ms=self.clock_ms(), provider=provider)
            except Exception:
                pass  # display only; the next read tries again
        self._find_session_logs()
        try:
            fresh = snapshot_mod.build(paths=self.paths, providers=wrapped,
                                       platform=self.platform,
                                       now_ms=self.clock_ms())
        except Exception:
            return ActionResult(True, "refresh_files")
        return ActionResult(True, "refresh_files", snapshot=fresh)

    def watch_signature(self):
        """A cheap fingerprint of every file a refresh would read.

        Size and modification time of the vendors' login files and config,
        Shambles' own markers, and the newest Codex session log. Stats only:
        no file is opened, and no store is asked anything. When this changes
        something was written, and :meth:`refresh_files` is worth running.
        """
        watched = []
        for provider in self.providers:
            try:
                store = provider.store(home=self.paths.home,
                                       platform=self.platform)
            except Exception:
                store = None
            watched += _files_of(store)
            companion = provider.companion_path(home=self.paths.home)
            if companion is not None:
                watched.append(companion)
            watched.append(self.paths.active_marker(provider.id))
            watched.append(self.paths.provider_dir(provider.id))
            watched.append(self._session_logs.get(provider.id))
        signature = []
        for path in watched:
            if path is None:
                continue
            try:
                info = os.stat(path)
            except OSError:
                signature.append((str(path), None))
                continue
            signature.append((str(path), info.st_mtime_ns, info.st_size))
        return tuple(signature)

    def plan_switch(self, provider_id, account):
        return ActionPlan("switch", provider_id, account, False,
                          f"Switch to {account}?")

    def switch(self, provider_id, account, *, on_wait=None):
        """Switch accounts. ``on_wait`` is called once if the switch has to
        wait for the vendor to finish renewing a login; see
        :data:`WAITING_FOR_REFRESH` for what to tell the user."""
        try:
            provider = self._provider(provider_id)
            # A stale marker would make switch() refuse, and would file the
            # outgoing login under the wrong name if it did not.
            switcher.adopt_live_owner(self.paths, provider,
                                      platform=self.platform)
            switcher.switch(self.paths, provider, account,
                            platform=self.platform, on_wait=on_wait)
            return self._result(True, "switch", f"Switched to {account}.",
                                warnings=self._switch_warnings(provider))
        except ShamblesError as exc:
            return self._failure("switch", exc)

    def save_current(self, provider_id, name):
        try:
            saved = switcher.save_current_account(
                self.paths, self._provider(provider_id), name,
                platform=self.platform)
            return self._result(True, "save_current", f"Saved {saved}.")
        except ShamblesError as exc:
            return self._failure("save_current", exc)

    def add(self, provider_id, name):
        try:
            added = switcher.add_empty_account(
                self.paths, self._provider(provider_id), name,
                platform=self.platform)
            return self._result(True, "add", f"Added {added}.")
        except ShamblesError as exc:
            return self._failure("add", exc)

    def rename(self, provider_id, old_name, new_name):
        try:
            renamed = switcher.rename_profile(
                self.paths, self._provider(provider_id), old_name, new_name)
            return self._result(True, "rename", f"Renamed to {renamed}.")
        except ShamblesError as exc:
            return self._failure("rename", exc)

    def refresh(self):
        for provider in self.providers:
            # Adoption first, as the window does: re-stashing is gated on the
            # live login belonging to the marked profile, so a stale marker
            # would leave a rotating token un-stashed.
            switcher.adopt_live_owner(self.paths, provider,
                                      platform=self.platform)
            switcher.restash_active(
                self.paths, provider, platform=self.platform)
            # The account in use only otherwise learns its figures at the
            # moment it is switched away from. A no-op unless the vendor's
            # cache provably belongs to the marked profile.
            usage_mod.capture_live(
                self.paths, provider.id,
                state.read_active(self.paths, provider.id),
                now_ms=self.clock_ms())
        return self._result(True, "refresh")

    def forget_marker(self, provider_id):
        """Clear a marker that names a profile no longer on disk.

        Moves no credential. What is live stays live and, if nobody saved
        holds it, stays on offer to be saved.
        """
        try:
            switcher.forget_active_marker(self.paths,
                                          self._provider(provider_id))
            return self._result(True, "forget_marker")
        except ShamblesError as exc:
            return self._failure("forget_marker", exc)

    def run_migrations(self):
        """Bring an older store up to date, and say what was done.

        Unprompted, for the reason the Tk window gives: the old layouts
        either hid session history or cannot hold a second provider, and
        neither is something anyone would choose to keep. Both steps are
        additive, so there is nothing to undo.

        Returns one :class:`MigrationNotice` per step that ran or could not;
        an up-to-date home returns none. Never raises a
        :class:`~shambles.errors.ShamblesError`: a migration that cannot run
        is a reason to say so, not to refuse the window.
        """
        notices = []
        if migrate_mod.needed(self.paths):
            try:
                plan = migrate_mod.run(self.paths, now_ms=self.clock_ms())
            except ShamblesError as exc:
                notices.append(MigrationNotice(
                    "history_merge_failed", str(exc), ok=False))
            else:
                others = ", ".join(plan.others) or "the other profiles"
                notices.append(MigrationNotice(
                    "history_merged",
                    "Your session history was split across accounts and has "
                    f"been merged. {plan.merged_files} files were brought "
                    f"over from {others} into one shared ~/.claude, so every "
                    "account can now see every session and switching will "
                    "not hide them again. Nothing was deleted. The old "
                    "copies are still on disk if you want to check them."))
        if migrate_mod.store_migration_needed(self.paths):
            try:
                moved = migrate_mod.migrate_store(self.paths)
            except ShamblesError as exc:
                notices.append(MigrationNotice(
                    "store_move_failed", str(exc), ok=False))
            else:
                if moved.profiles:
                    notices.append(MigrationNotice(
                        "store_moved",
                        f"Your profiles moved to {moved.dest}. "
                        f"{len(moved.profiles)} account(s) are now filed "
                        "under the provider they belong to, which is what "
                        "lets Shambles hold Codex accounts alongside Claude "
                        f"ones. Nothing was deleted. The old {moved.source} "
                        "is still there, and you can remove it once you are "
                        "satisfied."))
        return tuple(notices)

    def window_theme(self):
        """``system``, ``light`` or ``dark``: what the window should draw in."""
        return settings_mod.window_theme(self.paths)

    def set_window_theme(self, theme):
        try:
            settings_mod.set_window_theme(self.paths, theme)
        except ValueError as exc:
            return ActionResult(False, "set_window_theme", error=ActionError(
                "invalid_setting", str(exc)))
        except OSError as exc:
            return ActionResult(False, "set_window_theme", error=ActionError(
                "unwritable",
                f"Could not save the theme: {exc.strerror or exc}."))
        return ActionResult(True, "set_window_theme")

    def window_place(self):
        """Where the window was left, or None: see
        :func:`shambles.settings.window_place`."""
        return settings_mod.window_place(self.paths)

    def set_window_place(self, x, y, width, height, maximized=False):
        try:
            settings_mod.set_window_place(self.paths, x, y, width, height,
                                          maximized)
        except ValueError as exc:
            return ActionResult(False, "set_window_place", error=ActionError(
                "invalid_setting", str(exc)))
        except OSError as exc:
            return ActionResult(False, "set_window_place", error=ActionError(
                "unwritable",
                f"Could not save the window's place: {exc.strerror or exc}."))
        return ActionResult(True, "set_window_place")

    def hidden_deadlines(self):
        """``{"provider/account": "YYYY-MM-DD"}``: deadline lines the user
        closed, and the day they did. See :func:`settings.hide_deadline`."""
        return settings_mod.hidden_deadlines(self.paths)

    def hide_deadline(self, key, today):
        try:
            settings_mod.hide_deadline(self.paths, key, today)
        except ValueError as exc:
            return ActionResult(False, "hide_deadline", error=ActionError(
                "invalid_setting", str(exc)))
        except OSError as exc:
            return ActionResult(False, "hide_deadline", error=ActionError(
                "unwritable", f"Could not save that: {exc.strerror or exc}."))
        return ActionResult(True, "hide_deadline")

    def sign_in_url(self, line):
        """The sign-in address in one progress line, or None.

        Here rather than in the frontend because ``shambles/app/tui`` may not
        import :mod:`shambles.login` at all -- every mutation and every vendor
        process reaches the terminal UI through this object, and a screen that
        reached around it for "just a URL" is how that rule starts to rot.

        The line has already been through :func:`_safe_login_line`, so it is
        either a validated sign-in URL or :data:`HIDDEN_LINE`; this only has
        to find the address in what survived.
        """
        return login.find_url(line)

    def open_sign_in_url(self, url):
        """Hand the address to a browser. Returns whether one accepted it.

        The return value is worth less than it looks under WSL, where the
        openers report success while doing nothing -- callers are expected to
        put the link on the clipboard regardless rather than trust this.
        """
        return login.open_url(url)

    def start_login(self, provider_id, account, on_line, on_done):
        """Sign a saved profile in again through the vendor's own command.

        The profile is made live first, because the vendor writes to the one
        live location. However it ends -- cancelled, failed, nothing written,
        or a login for somebody else -- the user is never left on a dead
        account with the one they were using signed out:
        :func:`shambles.switcher.settle_login` decides, the same way the
        window does.
        """
        return self._run_login(provider_id, account, on_line, on_done,
                               adding=False)

    def start_add(self, provider_id, name, on_line, on_done):
        """Create a profile and sign it in, in one step.

        Adding has to switch to the new, empty profile before the vendor runs,
        which signs the user out of the account they were on. Ending there --
        what ``add`` alone does -- leaves them signed out with nothing to show
        for it, so this runs the sign-in straight away and rolls back if it
        comes to nothing. The profile is kept either way, so a retry does not
        need the name again.
        """
        return self._run_login(provider_id, name, on_line, on_done,
                               adding=True)

    def _run_login(self, provider_id, account, on_line, on_done, *, adding):
        action = "add" if adding else "login"
        provider = self._provider(provider_id)
        process = None
        completed = threading.Event()
        cancelled = threading.Event()
        #: Filled in once the profile is live: who to put back, and on what.
        prepared = {}

        def deliver(result):
            try:
                on_done(result)
            except Exception:
                # A closed presentation client must not leak callback data or
                # prevent the worker from completing.
                pass
            finally:
                completed.set()

        def settle(succeeded):
            return switcher.settle_login(
                self.paths, provider, prepared["account"],
                prepared["previous"], adding=adding, succeeded=succeeded,
                platform=self.platform, now_ms_fn=self.clock_ms)

        def finish(exit_code):
            try:
                outcome = settle(exit_code == 0 and not cancelled.is_set())
                result = self._login_result(action, provider, outcome,
                                            exit_code=exit_code,
                                            cancelled=cancelled.is_set())
            except ShamblesError as exc:
                result = self._failure(action, exc)
            except Exception:
                result = self._result(
                    False, action, error=ActionError(
                        "login_failed", "Could not validate or save the login.",
                        "Check the credential store and retry."))
            deliver(result)

        def progress(line):
            try:
                on_line(_safe_login_line(line))
            except Exception:
                pass

        try:
            env = login.environment(provider, home=self.paths.home,
                                    platform=self.platform)
            # Before anything moves. A missing CLI found only at launch used
            # to leave the user switched onto the account it could not sign in.
            if not login.available(provider):
                binary = login.binary(provider)
                deliver(self._result(False, action, error=ActionError(
                    "login_unavailable",
                    f"{binary} is not installed, or not on your PATH.",
                    f"Shambles signs you in by running {binary}. Install it, "
                    "then try again. Switching between saved accounts still "
                    "works without it.")))
                return LoginHandle(None, completed)
            if adding:
                prepared["previous"] = self._live_profile(provider)
                prepared["account"] = switcher.add_empty_account(
                    self.paths, provider, account, platform=self.platform)
                email = None
            else:
                prepared["previous"] = switcher.begin_relogin(
                    self.paths, provider, account, platform=self.platform)
                prepared["account"] = account
                email = state.profile_email(self.paths, provider, account)
            process = login.LoginProcess(login.command(provider, email=email),
                                         env=env)
            process.start(on_line=progress, on_exit=finish)
        except ShamblesError as exc:
            self._unwind(prepared, settle)
            deliver(self._failure(action, exc))
        except Exception:
            self._unwind(prepared, settle)
            deliver(self._result(
                False, action, error=ActionError(
                    "login_failed", "Could not prepare the vendor login.",
                    "Check the login configuration and retry.")))
        return LoginHandle(process, completed, cancelled)

    @staticmethod
    def _unwind(prepared, settle):
        """Put the user back after a launch that failed once they had moved."""
        if "account" not in prepared:
            return
        try:
            settle(False)
        except Exception:
            pass

    def _switch_warnings(self, provider):
        """What a successful switch did not reach.

        A terminal whose environment points the vendor somewhere else keeps
        its own login, and "Launch claude here" in the terminal UI would start
        it on exactly that one. Said with the result, because that is when a
        person acts on it.
        """
        override = state.config_dir_override(
            provider, home=self.paths.home, env=getattr(provider, "env", None))
        if not override:
            return ()
        variable = (provider.spec.get("config_dir") or {}).get("env", "")
        return (f"{variable} is set in this environment, so a terminal started "
                f"from here reads its login from {override}, not the one "
                "Shambles just switched. VS Code is unaffected.",)

    def _live_profile(self, provider):
        """The saved profile that is live right now, if there is one."""
        current = state.inspect(self.paths, provider, platform=self.platform)
        if current.profile and self.paths.profile_dir(
                provider.id, current.profile).is_dir():
            return current.profile
        return None

    def _login_result(self, action, provider, outcome, *, exit_code,
                      cancelled):
        """Put a settled login into words a person can act on."""
        name = outcome.profile
        if outcome.kind == switcher.RENEWED:
            summary = (f"Added {name} and signed in." if action == "add"
                       else f"Logged in to {name}.")
            # No word on running sessions: Claude Code 2.1.300 re-reads a
            # changed login at its next request, older versions and Codex
            # are unconfirmed, so any claim either way could be wrong.
            return self._result(True, action, summary)

        if outcome.kind == switcher.DUPLICATE:
            where = f"You are on '{outcome.owner}' now. " if outcome.owner else ""
            return self._result(False, action, error=ActionError(
                "login_duplicate",
                f"You signed in as {outcome.live_email or 'an account'}, "
                f"which is already saved as '{outcome.owner}'. Nothing was "
                f"saved under '{name}'.",
                f"{where}To add a different account, sign out in your "
                f"browser or use a private window, then sign in to "
                f"'{name}' again."))

        if outcome.kind == switcher.OTHER_ACCOUNT:
            where = (f"You are on '{outcome.owner}', which that login belongs "
                     "to. " if outcome.owner else
                     "That login is live but not saved; save it as its own "
                     "account to keep it. ")
            return self._result(False, action, error=ActionError(
                "login_other_account",
                f"Your browser signed in as "
                f"{outcome.live_email or 'another account'}, but '{name}' is "
                f"{outcome.expected_email or 'a different account'}. Nothing "
                f"was saved over '{name}'.",
                f"{where}Sign out in your browser, or use a private window, "
                f"then sign in to '{name}' again."))

        if outcome.restored:
            where = f"You are back on '{outcome.previous}'. Nothing was lost."
        elif outcome.still_works:
            where = f"'{name}' still works as it did. Nothing was lost."
        elif action == "add":
            where = f"'{name}' was created but has no login yet."
        else:
            where = f"'{name}' still needs a sign-in."
        if cancelled:
            code, message = "login_cancelled", "Sign-in cancelled."
        elif exit_code:
            code, message = ("login_failed",
                             "The vendor's sign-in did not finish.")
        else:
            code, message = ("login_not_written",
                             "The vendor did not write a usable login.")
        return self._result(False, action, error=ActionError(
            code, message, f"{where} Sign in to '{name}' to try again."))

    def plan_remove(self, provider_id, name):
        """Ask before deleting a login, and say what getting it back costs."""
        try:
            email = state.profile_email(
                self.paths, self._provider(provider_id), name)
        except Exception:
            email = None
        who = email or "that account"
        return ActionPlan(
            "remove", provider_id, name, True, f"Remove {name}?",
            (f"Its saved login is deleted. Signing {who} back in here will "
             "need a new verification email.",),
        )

    def remove(self, plan):
        if plan.action != "remove" or not plan.provider or not plan.account:
            return ActionResult(
                False, "remove",
                error=ActionError(
                    "invalid_plan", "The removal plan is invalid."),
            )
        try:
            switcher.remove_profile(
                self.paths, self._provider(plan.provider), plan.account,
                platform=self.platform)
            return self._result(True, "remove", f"Removed {plan.account}.")
        except ShamblesError as exc:
            return self._failure("remove", exc)

    def plan_eject(self):
        plan = eject_mod.survey(
            self.paths, self.providers, platform=self.platform)
        # What eject does comes first. The survey's summary is written for
        # after the fact, and shown alone it read as if eject had happened.
        return ActionPlan(
            "eject", None, None, True, "Eject Shambles?",
            ("Shambles will stop managing your accounts. Each provider keeps "
             "the login it has now and goes back to being an ordinary "
             "install. Nothing is deleted.",
             "Afterwards:\n" + eject_mod.summary(plan)),
        )

    def eject(self, plan):
        if plan.action != "eject":
            return ActionResult(
                False, "eject",
                error=ActionError(
                    "invalid_plan", "The eject plan is invalid."),
            )
        try:
            completed = eject_mod.run(
                self.paths, self.providers, platform=self.platform)
            return self._result(True, "eject", eject_mod.summary(completed))
        except ShamblesError as exc:
            return self._failure("eject", exc)

    def _failure(self, action, exc):
        # The nearest mapped class, not only an exact one: a store may raise
        # something more specific than StoreUnavailableError, and it is still
        # a store failure with the same way out.
        code, recovery = next(
            (ERROR_CODES[cls] for cls in type(exc).__mro__
             if cls in ERROR_CODES),
            ("operation_refused", "Review the message and retry."))
        if isinstance(exc, AlreadyManagedError) and action != "remove":
            # One exception class, four refusals. Only Remove raises it to
            # mean "this is the active profile"; from anywhere else that code
            # would tell a client to offer the wrong remedy.
            code = "operation_refused"
            recovery = "Review the current login and saved accounts before retrying."
        # A login failure is reported in general terms, because a store's
        # error text carries paths and whatever the OS said. The switcher's
        # own refusals are the exception: they are written for the user, hold
        # nothing the snapshot does not already carry, and are the only
        # place the way out is named.
        hidden = action == "login" and not isinstance(exc, (
            AlreadyManagedError, DriftedLoginError, ProfileNotFoundError))
        message = "The login could not be completed." if hidden else str(exc)
        return self._result(False, action,
                            error=ActionError(code, message, recovery))

    def _result(self, ok, action, summary="", *, error=None, warnings=()):
        """A failed read cannot erase an operation that already finished."""
        try:
            fresh = self.snapshot()
        except Exception:
            return ActionResult(
                ok, action, summary,
                warnings=(*warnings,
                          "Account status is unavailable. Refresh to retry."),
                error=error)
        return ActionResult(ok, action, summary, warnings=tuple(warnings),
                            snapshot=fresh, error=error)
