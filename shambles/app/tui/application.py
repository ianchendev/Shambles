"""Textual presentation state, keyboard navigation, and first-run welcome."""

from __future__ import annotations

import os
from enum import Enum

from rich.cells import cell_len
from textual import events, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.message import Message
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widget import Widget
from textual.widgets import Static

from ..service import ActionError, ActionPlan, ActionResult, ShamblesService
from ..snapshot import Snapshot
from .brand import BrandVariant, brand_text, variant_for
from .dashboard import Dashboard, MINIMUM_HEIGHT
from .overlays import ConfirmAction, ResultScreen
from .widgets import AccountList


class SwitchFinished(Message):
    def __init__(self, provider: str, result: ActionResult):
        super().__init__()
        self.provider = provider
        self.result = result


class BoxPhase(Enum):
    """One pass around the welcome frame; the wordmark never animates."""

    CORNERS = "corners"
    HORIZONTAL = "horizontal"
    VERTICAL = "vertical"
    SETTLED = "settled"


class OnboardingFrame(Widget):
    DEFAULT_CSS = """
    OnboardingFrame { width: auto; height: auto; }
    OnboardingFrame #frame-top, OnboardingFrame #frame-bottom {
        height: 1; color: #d9a441;
    }
    OnboardingFrame #frame-middle { height: auto; }
    OnboardingFrame #frame-left, OnboardingFrame #frame-right {
        width: 2; height: 100%; color: #d9a441;
    }
    OnboardingFrame #onboarding-brand {
        width: 1fr; height: auto; color: #e07a5f;
    }
    """

    def __init__(self, variant: BrandVariant, *, motion: bool, unicode: bool):
        super().__init__(id="onboarding-frame")
        self.variant = variant
        self.unicode = unicode
        self.phase = (
            BoxPhase.CORNERS
            if motion and variant is BrandVariant.WIDE
            else BoxPhase.SETTLED
        )
        self._timer: Timer | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="frame-top", markup=False)
        with Horizontal(id="frame-middle"):
            yield Static(id="frame-left", markup=False)
            yield Static(id="onboarding-brand", markup=False)
            yield Static(id="frame-right", markup=False)
        yield Static(id="frame-bottom", markup=False)

    def on_mount(self) -> None:
        self._draw()
        if self.phase is not BoxPhase.SETTLED:
            self._timer = self.set_interval(0.15, self.advance_phase)

    def set_variant(self, variant: BrandVariant) -> None:
        self.variant = variant
        if variant is not BrandVariant.WIDE:
            self.settle()
        else:
            self._draw()

    def advance_phase(self) -> None:
        phases = tuple(BoxPhase)
        if self.phase is BoxPhase.SETTLED:
            return
        self.phase = phases[phases.index(self.phase) + 1]
        if self.phase is BoxPhase.SETTLED:
            self.settle()
        else:
            self._draw()

    def settle(self) -> None:
        self.phase = BoxPhase.SETTLED
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._draw()

    def _draw(self) -> None:
        wordmark = brand_text(self.variant, unicode=self.unicode)
        rows = wordmark.splitlines()
        width = max(map(cell_len, rows)) + 4
        self.styles.width = width
        self.styles.height = len(rows) + 2
        self.query_one("#frame-middle").styles.height = len(rows)
        self.query_one("#onboarding-brand", Static).update(wordmark)

        top_left, top_right, bottom_left, bottom_right, horizontal, vertical = (
            ("┌", "┐", "└", "┘", "─", "│")
            if self.unicode else ("+", "+", "+", "+", "-", "|")
        )
        edge = horizontal if self.phase is not BoxPhase.CORNERS else " "
        side = (
            vertical
            if self.phase in (BoxPhase.VERTICAL, BoxPhase.SETTLED)
            else " "
        )
        self.query_one("#frame-top", Static).update(
            top_left + edge * (width - 2) + top_right
        )
        self.query_one("#frame-bottom", Static).update(
            bottom_left + edge * (width - 2) + bottom_right
        )
        self.query_one("#frame-left", Static).update(
            "\n".join([side + " "] * len(rows))
        )
        self.query_one("#frame-right", Static).update(
            "\n".join([" " + side] * len(rows))
        )
        self.set_class(self.phase is BoxPhase.SETTLED, "settled")
        self.set_class(self.phase is not BoxPhase.SETTLED, "drawing")


class Onboarding(Widget):
    DEFAULT_CSS = """
    Onboarding { height: 1fr; }
    Onboarding #welcome-body {
        width: 100%; height: 100%; align: center middle; padding: 1 2;
    }
    Onboarding #welcome-title {
        width: 100%; height: 2; text-style: bold; content-align: center middle;
    }
    Onboarding #welcome-copy {
        width: 100%; height: auto; content-align: center middle;
    }
    Onboarding.too-short #welcome-body { display: none; }
    Onboarding.too-short #terminal-too-small { display: block; }
    """

    def __init__(self, *, motion: bool, unicode: bool):
        super().__init__(id="onboarding")
        self.motion = motion
        self.unicode = unicode

    def compose(self) -> ComposeResult:
        yield Static(
            f"Terminal is too small. Use at least {MINIMUM_HEIGHT} rows.",
            id="terminal-too-small",
        )
        with Vertical(id="welcome-body"):
            yield Static("Welcome to SHAMBLES", id="welcome-title")
            yield OnboardingFrame(
                variant_for(self.app.size.width),
                motion=self.motion,
                unicode=self.unicode,
            )
            yield Static(
                "No saved accounts yet.\n"
                "Manage Claude and Codex accounts locally.\n\n"
                "r Refresh   ? Help   q Quit",
                id="welcome-copy",
            )

    def on_resize(self, event: events.Resize) -> None:
        frame = self.query_one(OnboardingFrame)
        frame.set_variant(variant_for(event.size.width))
        too_short = event.size.height < MINIMUM_HEIGHT
        self.set_class(too_short, "too-short")
        if too_short:
            frame.settle()


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
        Binding("escape", "settle_onboarding", "Skip", show=False),
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
            and "NO_COLOR" not in os.environ
            and os.environ.get("SHAMBLES_NO_MOTION") != "1"
        )
        self.unicode = unicode
        self.selected_provider: str | None = None
        self.selected_account: str | None = None
        self._onboarding_seen = False
        self._mutation_pending = False
        self._choose_selection()

    @property
    def mutation_running(self) -> bool:
        return self._mutation_pending or any(
            worker.group == "mutation" and not worker.is_finished
            for worker in self.workers
        )

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        if action in {"switch_selected", "refresh_snapshot"}:
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
        motion = self.motion and not self._onboarding_seen
        self._onboarding_seen = True
        return Onboarding(motion=motion, unicode=self.unicode)

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
        result = self.service.refresh()
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
        if self.mutation_running or self.screen.is_modal:
            return
        self.action_settle_onboarding()
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

    def action_settle_onboarding(self) -> None:
        for frame in self.query(OnboardingFrame):
            frame.settle()

    def action_help(self) -> None:
        self.push_screen(HelpScreen())


def run_tui(
    service: ShamblesService, *, motion: bool = True, unicode: bool = True,
) -> str | None:
    """Return the optional provider choice after Textual restores the terminal."""
    return ShamblesTUI(service, motion=motion, unicode=unicode).run()
