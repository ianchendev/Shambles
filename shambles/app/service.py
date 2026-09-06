"""Structured data exchanged by the application service boundary."""

from dataclasses import asdict, dataclass

from .. import switcher
from ..errors import (AlreadyManagedError, ConfigUnreadableError,
                      ProfileNotFoundError, ShamblesError)
from ..stores.base import StoreUnavailableError
from . import snapshot as snapshot_mod
from .snapshot import Snapshot


ERROR_CODES = {
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

    def _failure(self, action, exc):
        code, recovery = ERROR_CODES.get(
            type(exc), ("operation_refused", "Review the message and retry."))
        return ActionResult(
            False, action,
            snapshot=self.snapshot(),
            error=ActionError(code, str(exc), recovery),
        )
