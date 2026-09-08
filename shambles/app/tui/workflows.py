"""Lifecycle screens: add-account, name input, the account action menu, and login progress.

Confirmation and completed-result presentation are not redefined here; both
already exist in ``overlays.py`` (``ConfirmAction`` and ``ResultScreen``) and
``application.py`` reuses them for remove, eject, save, add, rename, and
login the same way Task 5 already uses them for switch.
"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from ..snapshot import Group


class NameInputScreen(ModalScreen[str | None]):
    """Collect one profile name.

    The service validates the name and any resulting error is displayed by
    the caller via ``ResultScreen``; this screen does not duplicate naming
    rules.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "app.quit", "Quit"),
    ]
    DEFAULT_CSS = """
    NameInputScreen { align: center middle; }
    """

    def __init__(self, prompt: str, *, initial: str = ""):
        super().__init__(id="name-input")
        self.prompt = prompt
        self.initial = initial

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="overlay-panel"):
            yield Static(self.prompt, classes="overlay-title", markup=False)
            yield Input(value=self.initial, id="name-value")
            yield Static("Enter Submit   Esc Cancel   q Quit", markup=False)

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AddAccountScreen(ModalScreen[tuple[str, str] | None]):
    """Collect a provider and profile name for a new empty account."""

    BINDINGS = [
        Binding("up,k", "previous_provider", "Previous provider", show=False, priority=True),
        Binding("down,j", "next_provider", "Next provider", show=False, priority=True),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "app.quit", "Quit"),
    ]
    DEFAULT_CSS = """
    AddAccountScreen { align: center middle; }
    """

    def __init__(
        self, groups: list[Group], selected_provider: str | None = None,
    ):
        super().__init__(id="add-account")
        self.groups = list(groups)
        ids = [group.provider for group in self.groups]
        if selected_provider in ids:
            self.provider_index = ids.index(selected_provider)
        else:
            self.provider_index = 0

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="overlay-panel"):
            yield Static("Add account", classes="overlay-title", markup=False)
            yield Static(self._provider_lines(), id="add-providers", markup=False)
            yield Input(id="name-value")
            yield Static(
                "j/k Provider   Enter Submit   Esc Cancel   q Quit",
                markup=False,
            )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def _provider_lines(self) -> str:
        lines = []
        for index, group in enumerate(self.groups):
            mark = "*" if index == self.provider_index else " "
            lines.append(f"({mark}) {group.display_name}")
        return "\n".join(lines) if lines else "(no providers)"

    def _refresh_providers(self) -> None:
        self.query_one("#add-providers", Static).update(self._provider_lines())

    def action_next_provider(self) -> None:
        if self.groups:
            self.provider_index = min(
                self.provider_index + 1, len(self.groups) - 1,
            )
            self._refresh_providers()

    def action_previous_provider(self) -> None:
        if self.groups:
            self.provider_index = max(self.provider_index - 1, 0)
            self._refresh_providers()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self.groups:
            self.dismiss(None)
            return
        self.dismiss((self.groups[self.provider_index].provider, event.value))

    def action_cancel(self) -> None:
        self.dismiss(None)


class AccountMenu(ModalScreen[str | None]):
    """Offer the account-scoped edits for the currently selected account."""

    BINDINGS = [
        Binding("s", "choose('save')", "Save"),
        Binding("a", "choose('add')", "Add"),
        Binding("n", "choose('rename')", "Rename"),
        Binding("d", "choose('remove')", "Remove"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "app.quit", "Quit"),
    ]
    DEFAULT_CSS = """
    AccountMenu { align: center middle; }
    """

    def __init__(self, provider: str, account: str):
        super().__init__(id="account-menu")
        self.provider = provider
        self.account = account

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="overlay-panel"):
            yield Static(
                f"Actions for {self.account}", classes="overlay-title", markup=False,
            )
            yield Static(
                "s Save current login\n"
                "a Add new profile\n"
                "n Rename\n"
                "d Remove\n\n"
                "Esc Cancel   q Quit",
                markup=False,
            )

    def action_choose(self, choice: str) -> None:
        self.dismiss(choice)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LoginProgress(ModalScreen[None]):
    """Show vendor login output while ``ShamblesService.start_login`` runs.

    The vendor login runs as a subprocess already managed off the UI thread
    by the service; this screen only reflects progress lines and lets the
    user cancel. It never starts or joins that thread itself.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "app.quit", "Quit"),
    ]
    DEFAULT_CSS = """
    LoginProgress { align: center middle; }
    """

    def __init__(self, provider: str, account: str):
        super().__init__(id="login-progress")
        self.provider = provider
        self.account = account
        self.lines: list[str] = []

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes="overlay-panel"):
            yield Static(
                f"Logging in to {self.account}...",
                classes="overlay-title",
                markup=False,
            )
            yield Static("", id="login-lines", markup=False)
            yield Static("Esc Cancel   q Quit", markup=False)

    def add_line(self, line: str) -> None:
        self.lines.append(line)
        self.query_one("#login-lines", Static).update("\n".join(self.lines))

    def action_cancel(self) -> None:
        self.dismiss(None)
