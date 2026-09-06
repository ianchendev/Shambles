"""Structured data exchanged by the application service boundary."""

from dataclasses import asdict, dataclass
import threading

from .. import eject as eject_mod
from .. import login
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
        self._process.cancel()

    def wait(self, timeout=None):
        return self._completed.wait(timeout)

    @property
    def running(self):
        return self._process.running


def _safe_login_line(_line):
    # Vendor stdout has no stable schema and can contain credentials under
    # spellings Shambles cannot enumerate safely. Treat every byte as secret;
    # callers receive only a fixed progress message.
    return "[vendor output hidden]"


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
            return ActionResult(True, "switch",
                                f"Switched to {account}.",
                                snapshot=self.snapshot())
        except ShamblesError as exc:
            return self._failure("switch", exc)

    def save_current(self, provider_id, name):
        try:
            saved = switcher.save_current_account(
                self.paths, self._provider(provider_id), name,
                platform=self.platform)
            return ActionResult(True, "save_current", f"Saved {saved}.",
                                snapshot=self.snapshot())
        except ShamblesError as exc:
            return self._failure("save_current", exc)

    def add(self, provider_id, name):
        try:
            added = switcher.add_empty_account(
                self.paths, self._provider(provider_id), name,
                platform=self.platform)
            return ActionResult(True, "add", f"Added {added}.",
                                snapshot=self.snapshot())
        except ShamblesError as exc:
            return self._failure("add", exc)

    def rename(self, provider_id, old_name, new_name):
        try:
            switcher.rename_profile(
                self.paths, self._provider(provider_id), old_name, new_name)
            return ActionResult(True, "rename", f"Renamed to {new_name}.",
                                snapshot=self.snapshot())
        except ShamblesError as exc:
            return self._failure("rename", exc)

    def refresh(self):
        for provider in self.providers:
            switcher.restash_active(
                self.paths, provider, platform=self.platform)
        return ActionResult(True, "refresh", snapshot=self.snapshot())

    def start_login(self, provider_id, account, on_line, on_done):
        provider = self._provider(provider_id)
        process = login.LoginProcess(login.command(provider))
        completed = threading.Event()

        def deliver(result):
            try:
                on_done(result)
            finally:
                completed.set()

        def finish(exit_code):
            fresh = self.snapshot()
            if exit_code:
                result = ActionResult(
                    False, "login", snapshot=fresh,
                    error=ActionError(
                        "login_failed", "The vendor login command failed.",
                        "Review the output and retry."),
                )
            else:
                requested = next(
                    (candidate
                     for group in fresh.groups
                     if group.provider == provider_id
                     for candidate in group.accounts
                     if candidate.name == account),
                    None,
                )
                if (requested is None or not requested.active
                        or requested.needs_login):
                    result = ActionResult(
                        False, "login", snapshot=fresh,
                        error=ActionError(
                            "login_not_written",
                            "The vendor did not write a usable login.",
                            "Retry the login."),
                    )
                else:
                    result = ActionResult(
                        True, "login", f"Logged in to {account}.",
                        snapshot=fresh,
                    )
            deliver(result)

        try:
            switcher.switch(self.paths, provider, account,
                            platform=self.platform)
        except ShamblesError as exc:
            deliver(self._failure("login", exc))
            return LoginHandle(process, completed)

        try:
            process.start(
                on_line=lambda line: on_line(_safe_login_line(line)),
                on_exit=finish,
            )
        except login.LoginUnavailableError as exc:
            deliver(self._failure("login", exc))
        return LoginHandle(process, completed)

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
            return ActionResult(True, "remove", f"Removed {plan.account}.",
                                snapshot=self.snapshot())
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
            return ActionResult(True, "eject", eject_mod.summary(completed),
                                snapshot=self.snapshot())
        except ShamblesError as exc:
            return self._failure("eject", exc)

    def _failure(self, action, exc):
        code, recovery = ERROR_CODES.get(
            type(exc), ("operation_refused", "Review the message and retry."))
        return ActionResult(
            False, action,
            snapshot=self.snapshot(),
            error=ActionError(code, str(exc), recovery),
        )
