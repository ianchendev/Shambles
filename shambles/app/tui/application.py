"""Textual presentation state, keyboard navigation, and first-run welcome."""

from __future__ import annotations

import os
from typing import Callable

from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.widget import Widget
from textual.widgets import Static

from ...errors import ShamblesError
from ..service import (ActionError, ActionPlan, ActionResult, LoginHandle,
                       ShamblesService)
from ..snapshot import Snapshot
from .brand import header_text
from .dashboard import Dashboard, MINIMUM_HEIGHT
from .overlays import ConfirmAction, ResultScreen
from .widgets import AccountList
from .workflows import AccountMenu, LoginProgress, NameInputScreen

WELCOME_COPY = "No saved accounts yet."
WELCOME_FOOTER = "a add · x eject · r refresh · ? help · q quit"
WELCOME_FOOTER_ASCII = "a add | x eject | r refresh | ? help | q quit"


class SwitchFinished(Message):
    def __init__(self, provider: str, result: ActionResult):
        super().__init__()
        self.provider = provider
        self.result = result


class MutationFinished(Message):
    """One save/add/rename/remove/eject worker has produced a result."""

    def __init__(self, result: ActionResult):
        super().__init__()
        self.result = result


class LoginLine(Message):
    """One line of sanitized vendor login output, forwarded off-thread."""

    def __init__(self, line: str):
        super().__init__()
        self.line = line


class LoginFinished(Message):
    def __init__(self, result: ActionResult):
        super().__init__()
        self.result = result


class Onboarding(Widget):
    DEFAULT_CSS = """
    Onboarding { width: 100%; height: 1fr; }
    Onboarding #welcome-body {
        width: 100%; height: 1fr; align: center middle; padding: 1 2;
    }
    Onboarding #welcome-copy {
        width: 100%; height: auto; content-align: center middle;
    }
    Onboarding.too-short #welcome-body,
    Onboarding.too-short #dashboard-header,
    Onboarding.too-short #shortcut-footer { display: none; }
    Onboarding.too-short #terminal-too-small { display: block; }
    """

    def __init__(self, *, unicode: bool):
        super().__init__(id="onboarding")
        self.unicode = unicode

    def compose(self) -> ComposeResult:
        yield Static(
            f"Terminal is too small. Use at least {MINIMUM_HEIGHT} rows.",
            id="terminal-too-small",
        )
        yield Static(id="dashboard-header", markup=False)
        with Vertical(id="welcome-body"):
            yield Static(WELCOME_COPY, id="welcome-copy")
        yield Static(id="shortcut-footer", markup=False)

    def on_resize(self, event: events.Resize) -> None:
        width, height = event.size.width, event.size.height
        unicode = getattr(self.app, "unicode", self.unicode)
        self.set_class(height < MINIMUM_HEIGHT, "too-short")
        self.query_one("#dashboard-header", Static).update(
            header_text(width, height, unicode=unicode)
        )
        self.query_one("#shortcut-footer", Static).update(
            WELCOME_FOOTER if unicode else WELCOME_FOOTER_ASCII
        )


class HelpScreen(ModalScreen[None]):
    BINDINGS = [
        Binding("escape,question_mark", "dismiss", "Close"),
        Binding("q", "app.quit", "Quit"),
    ]
    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen VerticalScroll {
        width: 64; max-width: 100%; height: auto; max-height: 100%;
        padding: 1 2; border: ascii #d9a441; background: #11182b;
    }
    """

    def __init__(self):
        super().__init__(id="help")

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(
                "SHAMBLES help\n\n"
                "j / Down     Next account\n"
                "k / Up       Previous account\n"
                "Enter        Switch selected account\n"
                "m            Account actions (save, add, rename, remove)\n"
                "l            Log in to selected account\n"
                "x            Eject Shambles\n"
                "r            Refresh local state\n"
                "?            Help\n"
                "q            Quit\n"
                "Esc          Close help / skip welcome motion\n\n"
                "Accounts and usage come from local state.\n"
                "No telemetry or update checks.\n"
                "Affected applications appear in account details.\n"
                "Existing sessions keep their loaded login; restart them\n"
                "after switching accounts.",
                markup=False,
            )


class ShamblesTUI(App[str | None]):
    """A shell over the application service's presentation-ready snapshots."""

    CSS_PATH = "theme.tcss"
    DEFAULT_CSS = """
    #app-body { height: 1fr; }
    #refresh-status {
        display: none; height: auto; padding: 0 1; color: #d9a441;
    }
    #refresh-status.visible { display: block; }
    """
    BINDINGS = [
        Binding("j,down", "next_account", "Next", show=False, priority=True),
        Binding("k,up", "previous_account", "Previous", show=False, priority=True),
        Binding("r", "refresh_snapshot", "Refresh"),
        Binding("question_mark", "help", "Help"),
        Binding("enter", "switch_selected", "Switch", priority=True),
        Binding("m", "open_menu", "Menu"),
        Binding("l", "login_selected", "Login"),
        Binding("x", "eject", "Eject"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(
        self, service: ShamblesService, *, motion: bool = True,
        unicode: bool = True,
    ):
        super().__init__()
        self.service = service
        self.snapshot = service.snapshot()
        self.motion = (
            motion
            and not self.no_color
            and os.environ.get("SHAMBLES_NO_MOTION") != "1"
        )
        self.unicode = unicode
        self.selected_provider: str | None = None
        self.selected_account: str | None = None
        self._mutation_pending = False
        self._login_handle: LoginHandle | None = None
        self._choose_selection()

    @property
    def mutation_running(self) -> bool:
        return self._mutation_pending or any(
            worker.group == "mutation" and not worker.is_finished
            for worker in self.workers
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        gated = {"switch_selected", "refresh_snapshot",
                "open_menu", "login_selected", "eject"}
        # Refresh only rereads/restashes already-active credentials; it does
        # not begin a new credential mutation, so (like before) it alone is
        # exempt from the undersized-terminal guard.
        height_gated = gated - {"refresh_snapshot"}
        if action in height_gated and self.size.height < MINIMUM_HEIGHT:
            return False
        if action in gated:
            return not self.mutation_running and not self.screen.is_modal
        if action in {"next_account", "previous_account"}:
            return not self.screen.is_modal
        return True

    def _accounts(self) -> list[tuple[str, str]]:
        return [
            (group.provider, account.name)
            for group in self.snapshot.groups for account in group.accounts
        ]

    def _choose_selection(self, *, preserve: bool = False) -> None:
        accounts = self._accounts()
        if preserve and (self.selected_provider, self.selected_account) in accounts:
            return
        active = next((
            (group.provider, account.name)
            for group in self.snapshot.groups for account in group.accounts
            if account.active
        ), None)
        self.selected_provider, self.selected_account = (
            active or (accounts[0] if accounts else (None, None))
        )

    def _view(self) -> Widget:
        if self._accounts():
            return Dashboard(self.snapshot)
        return Onboarding(unicode=self.unicode)

    def compose(self) -> ComposeResult:
        with Vertical(id="app-body"):
            yield self._view()
        yield Static(id="refresh-status", markup=False)

    def on_list_view_highlighted(self, event: AccountList.Highlighted) -> None:
        if isinstance(event.list_view, AccountList) and event.list_view.is_attached:
            event.list_view.action_select_cursor()

    def on_dashboard_account_selected(self, event: Dashboard.AccountSelected) -> None:
        if (event.provider, event.account) in self._accounts():
            self.selected_provider, self.selected_account = event.provider, event.account

    def action_next_account(self) -> None:
        for accounts in self.query(AccountList):
            accounts.action_cursor_down()

    def action_previous_account(self) -> None:
        for accounts in self.query(AccountList):
            accounts.action_cursor_up()

    async def render_snapshot(
        self, snapshot: Snapshot, *, preserve_selection: bool = True,
    ) -> None:
        self.snapshot = snapshot
        self._choose_selection(preserve=preserve_selection)
        selected = (self.selected_provider, self.selected_account)
        body = self.query_one("#app-body", Vertical)
        await body.remove_children()
        await body.mount(self._view())
        if selected[0] is not None:
            accounts = self.query_one(AccountList)
            accounts.highlighted = self._accounts().index(selected)
            accounts.action_select_cursor()
            accounts.focus()

    async def action_refresh_snapshot(self) -> None:
        if self.mutation_running or self.screen.is_modal:
            return
        self._capture_selection()
        try:
            result = self.service.refresh()
        except ShamblesError:
            # Unlike the other mutation paths, refresh runs synchronously on
            # the UI thread rather than in a worker -- but it can still raise
            # StoreUnavailableError (a ShamblesError) out of
            # switcher.restash_active. An uncaught raise here would crash the
            # whole app instead of reporting through the normal result UI.
            result = ActionResult(False, "refresh", error=ActionError(
                "refresh_failed", "Could not refresh local state.",
                "Retry, or unlock/restore the credential store.",
            ))
        if result.snapshot is not None:
            await self.render_snapshot(result.snapshot)
        feedback = list(result.warnings)
        if result.error is not None:
            feedback = [result.error.message, result.error.recovery, *feedback]
        status = self.query_one("#refresh-status", Static)
        status.update("\n".join(line for line in feedback if line))
        status.set_class(bool(any(feedback)), "visible")

    def _capture_selection(self) -> None:
        # Cursor movement is immediate, but its selection messages may still
        # be queued behind the action key. Capture identity from the current
        # snapshot before the refreshed snapshot can reorder its rows.
        for account_list in self.query(AccountList):
            index = account_list.highlighted
            if index is not None:
                self.selected_provider, self.selected_account = self._accounts()[index]

    def action_switch_selected(self) -> None:
        if not self.check_action("switch_selected", ()):
            return
        self._capture_selection()
        for group in self.snapshot.groups:
            if group.provider != self.selected_provider:
                continue
            for account in group.accounts:
                if account.name == self.selected_account and not account.active:
                    plan = self.service.plan_switch(group.provider, account.name)
                    if plan.requires_confirmation:
                        self.push_screen(
                            ConfirmAction(plan),
                            lambda confirmed: self._begin_switch(plan, confirmed),
                        )
                    else:
                        self._begin_switch(plan, True)
                    return

    def _begin_switch(self, plan: ActionPlan, confirmed: bool) -> None:
        if (not confirmed or self.mutation_running
                or self.size.height < MINIMUM_HEIGHT
                or plan.provider is None or plan.account is None):
            return
        # Reserve the mutation slot before scheduling the worker:
        # cancelling an exclusive thread cannot undo its writes.
        self._mutation_pending = True
        self.perform_switch(plan.provider, plan.account)

    @work(thread=True, exclusive=True, group="mutation")
    def perform_switch(self, provider: str, account: str) -> None:
        try:
            result = self.service.switch(provider, account)
        except Exception:
            # Unexpected store/OS failures must not expose an exception dump
            # or close the interface before the user can read the result.
            result = ActionResult(False, "switch", error=ActionError(
                "switch_failed", "Could not switch accounts.",
                "Refresh local state and retry.",
            ))
        self.post_message(SwitchFinished(provider, result))

    async def on_switch_finished(self, event: SwitchFinished) -> None:
        self._capture_selection()
        if event.result.snapshot is not None:
            await self.render_snapshot(event.result.snapshot)
        await self.push_screen(
            ResultScreen(event.result, provider=event.provider), self._choose_launch,
        )
        self._mutation_pending = False

    def _choose_launch(self, provider: str | None) -> None:
        if provider is not None:
            self.exit(provider)

    def action_open_menu(self) -> None:
        if not self.check_action("open_menu", ()):
            return
        self._capture_selection()
        provider, account = self.selected_provider, self.selected_account
        if provider is None or account is None:
            return
        self.push_screen(
            AccountMenu(provider, account),
            lambda choice: self._menu_chosen(provider, account, choice),
        )

    def _menu_chosen(self, provider: str, account: str, choice: str | None) -> None:
        if choice == "save":
            self.push_screen(
                NameInputScreen(f"Save the current {provider} login as:"),
                lambda name: self._begin_save(provider, name),
            )
        elif choice == "add":
            self.push_screen(
                NameInputScreen(f"Add a new {provider} profile named:"),
                lambda name: self._begin_add(provider, name),
            )
        elif choice == "rename":
            self.push_screen(
                NameInputScreen(f"Rename {account} to:", initial=account),
                lambda name: self._begin_rename(provider, account, name),
            )
        elif choice == "remove":
            plan = self.service.plan_remove(provider, account)
            if plan.requires_confirmation:
                self.push_screen(
                    ConfirmAction(plan),
                    lambda confirmed: self._begin_mutation(
                        lambda: self.service.remove(plan), confirmed,
                    ),
                )
            else:
                self._begin_mutation(lambda: self.service.remove(plan), True)

    def _begin_save(self, provider: str, name: str | None) -> None:
        if name is None:
            return
        self._begin_mutation(lambda: self.service.save_current(provider, name))

    def _begin_add(self, provider: str, name: str | None) -> None:
        if name is None:
            return
        self._begin_mutation(lambda: self.service.add(provider, name))

    def _begin_rename(
        self, provider: str, old_name: str, new_name: str | None,
    ) -> None:
        if new_name is None:
            return
        self._begin_mutation(
            lambda: self.service.rename(provider, old_name, new_name))

    def action_eject(self) -> None:
        if not self.check_action("eject", ()):
            return
        plan = self.service.plan_eject()
        if plan.requires_confirmation:
            self.push_screen(
                ConfirmAction(plan),
                lambda confirmed: self._begin_mutation(
                    lambda: self.service.eject(plan), confirmed,
                ),
            )
        else:
            self._begin_mutation(lambda: self.service.eject(plan), True)

    def _begin_mutation(
        self, run: Callable[[], ActionResult], confirmed: bool = True,
    ) -> None:
        if (not confirmed or self.mutation_running
                or self.size.height < MINIMUM_HEIGHT):
            return
        # Reserve the mutation slot before scheduling the worker, exactly as
        # switch does: cancelling an exclusive thread cannot undo its writes.
        self._mutation_pending = True
        self.perform_mutation(run)

    @work(thread=True, exclusive=True, group="mutation")
    def perform_mutation(self, run: Callable[[], ActionResult]) -> None:
        try:
            result = run()
        except Exception:
            # Unexpected store/OS failures must not expose an exception dump
            # or close the interface before the user can read the result.
            result = ActionResult(False, "mutation", error=ActionError(
                "action_failed", "Could not complete the requested action.",
                "Refresh local state and retry.",
            ))
        self.post_message(MutationFinished(result))

    async def on_mutation_finished(self, event: MutationFinished) -> None:
        self._capture_selection()
        if event.result.snapshot is not None:
            await self.render_snapshot(event.result.snapshot)
        await self.push_screen(ResultScreen(event.result))
        self._mutation_pending = False

    def action_login_selected(self) -> None:
        if not self.check_action("login_selected", ()):
            return
        self._capture_selection()
        provider, account = self.selected_provider, self.selected_account
        if provider is None or account is None:
            return
        self._mutation_pending = True
        self._login_handle = self.service.start_login(
            provider, account,
            on_line=lambda line: self.post_message(LoginLine(line)),
            on_done=lambda result: self.post_message(LoginFinished(result)),
        )
        self.push_screen(LoginProgress(provider, account), self._login_cancelled)

    def _login_cancelled(self, _: None) -> None:
        # The service still delivers an eventual LoginFinished once the
        # cancelled vendor process actually exits; the mutation slot is
        # released there, not here, so a still-terminating subprocess cannot
        # race a freshly started mutation.
        if self._login_handle is not None:
            self._login_handle.cancel()

    def on_login_line(self, event: LoginLine) -> None:
        if isinstance(self.screen, LoginProgress):
            self.screen.add_line(event.line)

    async def on_login_finished(self, event: LoginFinished) -> None:
        self._mutation_pending = False
        self._capture_selection()
        if event.result.snapshot is not None:
            await self.render_snapshot(event.result.snapshot)
        if isinstance(self.screen, LoginProgress):
            self.pop_screen()
        await self.push_screen(ResultScreen(event.result))

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


def run_tui(
    service: ShamblesService, *, motion: bool = True, unicode: bool = True,
) -> str | None:
    """Return the optional provider choice after Textual restores the terminal."""
    return ShamblesTUI(service, motion=motion, unicode=unicode).run()
