"""Structured data exchanged by the application service boundary."""

from dataclasses import asdict, dataclass
import threading

from .. import eject as eject_mod
from .. import login
from .. import state
from .. import switcher
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


class LoginHandle:
    def __init__(self, process, completed):
        self._process = process
        self._completed = completed

    def cancel(self):
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
            switcher.switch(self.paths, self._provider(provider_id), account,
                            platform=self.platform)
            return self._result(True, "switch", f"Switched to {account}.")
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
            switcher.restash_active(
                self.paths, provider, platform=self.platform)
        return self._result(True, "refresh")

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
        provider = self._provider(provider_id)
        process = None
        completed = threading.Event()

        def deliver(result):
            try:
                on_done(result)
            except Exception:
                # A closed presentation client must not leak callback data or
                # prevent the worker from completing.
                pass
            finally:
                completed.set()

        def finish(exit_code):
            try:
                if exit_code:
                    result = self._result(
                        False, "login",
                        error=ActionError(
                            "login_failed", "The vendor login command failed.",
                            "Review the output and retry."),
                    )
                elif not self._usable_live_login(provider, account):
                    result = self._result(
                        False, "login",
                        error=ActionError(
                            "login_not_written",
                            "The vendor did not write a usable login.",
                            "Retry the login."),
                    )
                else:
                    switcher.stash_live_login(
                        self.paths, provider, account, platform=self.platform,
                        now_ms_fn=self.clock_ms)
                    result = self._result(
                        True, "login", f"Logged in to {account}.")
            except ShamblesError as exc:
                result = self._failure("login", exc)
            except Exception:
                result = self._result(
                    False, "login", error=ActionError(
                        "login_failed", "Could not validate or save the login.",
                        "Check the credential store and retry."))
            deliver(result)

        def progress(line):
            try:
                on_line(_safe_login_line(line))
            except Exception:
                pass

        try:
            process = login.LoginProcess(
                login.command(provider), env=login.environment(
                    provider, home=self.paths.home, platform=self.platform))
            switcher.switch(self.paths, provider, account,
                            platform=self.platform)
            process.start(
                on_line=progress,
                on_exit=finish,
            )
        except ShamblesError as exc:
            deliver(self._failure("login", exc))
        except Exception:
            deliver(self._result(
                False, "login", error=ActionError(
                    "login_failed", "Could not prepare the vendor login.",
                    "Check the login configuration and retry.")))
        return LoginHandle(process, completed)

    def _usable_live_login(self, provider, account):
        if (state.read_active(self.paths, provider.id) != account
                or not self.paths.profile_dir(provider.id, account).is_dir()):
            return False
        blob = provider.store(home=self.paths.home, platform=self.platform).read()
        return (provider.has_login(blob)
                and not provider.liveness(blob, now_ms=self.clock_ms()).needs_login
                and switcher.belongs_to(self.paths, provider, account,
                                        platform=self.platform))

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

    def _result(self, ok, action, summary="", *, error=None):
        """A failed read cannot erase an operation that already finished."""
        try:
            fresh = self.snapshot()
        except Exception:
            return ActionResult(
                ok, action, summary,
                warnings=("Account status is unavailable. Refresh to retry.",),
                error=error)
        return ActionResult(ok, action, summary, snapshot=fresh, error=error)
