"""Structured data exchanged by the application service boundary."""

from dataclasses import asdict, dataclass
import threading

from .. import eject as eject_mod
from .. import login
from .. import migrate as migrate_mod
from .. import settings as settings_mod
from .. import state
from .. import switcher
from .. import usage as usage_mod
from ..errors import (AlreadyManagedError, ConfigUnreadableError,
                      ProfileNotFoundError, ShamblesError)
from ..stores.base import StoreUnavailableError
from . import snapshot as snapshot_mod
from .snapshot import Snapshot


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


class ShamblesService:
    def __init__(self, *, paths, providers, platform,
                 clock_ms=switcher.now_ms):
        self.paths = paths
        self.providers = tuple(providers)
        self.platform = platform
        self.clock_ms = clock_ms

    def _provider(self, provider_id):
        try:
            return next(p for p in self.providers if p.id == provider_id)
        except StopIteration:
            raise KeyError(provider_id)

    def snapshot(self):
        return snapshot_mod.build(paths=self.paths, providers=self.providers,
                                  platform=self.platform,
                                  now_ms=self.clock_ms())

    def plan_switch(self, provider_id, account):
        return ActionPlan("switch", provider_id, account, False,
                          f"Switch to {account}?")

    def switch(self, provider_id, account):
        try:
            provider = self._provider(provider_id)
            # A stale marker would make switch() refuse, and would file the
            # outgoing login under the wrong name if it did not.
            switcher.adopt_live_owner(self.paths, provider,
                                      platform=self.platform)
            switcher.switch(self.paths, provider, account,
                            platform=self.platform)
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
            return self._result(True, action, summary, warnings=(
                "Running sessions keep the login they started with. Start a "
                "new one to use this account.",))

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
        return ActionPlan(
            "remove", provider_id, name, True, f"Remove {name}?",
            ("The saved login will be removed.",),
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
        return ActionPlan(
            "eject", None, None, True, "Eject Shambles?",
            (eject_mod.summary(plan),),
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
        code, recovery = ERROR_CODES.get(
            type(exc), ("operation_refused", "Review the message and retry."))
        if isinstance(exc, AlreadyManagedError) and action != "remove":
            recovery = "Review the current login and saved accounts before retrying."
        message = "The login could not be completed." if action == "login" else str(exc)
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
