"""Lifecycle screens: add-account, name input, the account action menu, and login progress.

Confirmation and completed-result presentation are not redefined here; both
already exist in ``overlays.py`` (``ConfirmAction`` and ``ResultScreen``) and
``application.py`` reuses them for remove, eject, save, add, rename, and
login the same way Task 5 already uses them for switch.
"""

from __future__ import annotations

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from ..service import HIDDEN_LINE
from ..snapshot import Group
from .overlays import overlay_panel_classes


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
        with VerticalScroll(classes=overlay_panel_classes(self)):
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
        options = [
            Option(group.display_name, id=group.provider)
            for group in self.groups
        ]
        with VerticalScroll(classes=overlay_panel_classes(self)):
            yield Static("Add account", classes="overlay-title", markup=False)
            yield OptionList(*options, id="add-providers", compact=True, markup=False)
            yield Input(id="name-value")
            yield Static(
                "j/k Provider   Tab Name   Enter Submit   Esc Cancel   q Quit",
                markup=False,
            )

    def on_mount(self) -> None:
        providers = self.query_one("#add-providers", OptionList)
        if self.groups:
            providers.highlighted = self.provider_index
        providers.focus()

    def action_next_provider(self) -> None:
        self.query_one("#add-providers", OptionList).action_cursor_down()

    def action_previous_provider(self) -> None:
        self.query_one("#add-providers", OptionList).action_cursor_up()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        option = self.query_one("#add-providers", OptionList).highlighted_option
        if option is None or option.id is None:
            self.dismiss(None)
            return
        self.dismiss((option.id, event.value))

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
        with VerticalScroll(classes=overlay_panel_classes(self)):
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

    The address the vendor prints gets a panel of its own rather than a place
    in the transcript. Both vendors print one exactly when they could not open
    a browser themselves -- the normal case under WSL and over SSH -- so it is
    the one line on this screen the user has to act on, and leaving it to
    scroll past as text is the failure this screen exists to prevent. The Tk
    window has offered it as a button since the beginning; this is the same
    affordance for the frontend that is now the default.
    """

    BINDINGS = [
        Binding("o", "open_link", "Open in browser"),
        Binding("c", "copy_link", "Copy link"),
        Binding("escape", "cancel", "Cancel"),
        Binding("q", "app.quit", "Quit"),
    ]
    DEFAULT_CSS = """
    LoginProgress { align: center middle; }
    LoginProgress #login-link { text-style: bold; }
    /* Set the link apart from the progress line above it: it is the one
       thing on this screen the reader has to act on. */
    LoginProgress #login-link-prompt { margin-top: 1; }
    LoginProgress #login-status { margin-top: 1; }
    """

    LINK_PROMPT = "Open this link to finish signing in:"

    #: One steady line instead of a stack of identical ones. Three
    #: :data:`~shambles.app.service.HIDDEN_LINE` placeholders in a row is what
    #: a healthy login looks like, and echoing that text at somebody waiting
    #: on a browser reads as concealment or breakage rather than progress.
    WAITING = "Waiting for the vendor CLI..."

    COPIED = "Link copied to the clipboard."

    #: Said when no opener worked. Not an error: it is the expected outcome
    #: over SSH, and the clipboard is the answer either way.
    OPEN_FAILED = ("No browser could be opened from here, which is usual under "
                   "WSL and over SSH. The link is on your clipboard.")

    OPENED = "Opened in your browser. The link is also on your clipboard."

    KEYS = "Esc Cancel   q Quit"
    LINK_KEYS = "o Open in browser   c Copy link   Esc Cancel   q Quit"

    def __init__(self, provider: str, account: str):
        super().__init__(id="login-progress")
        self.provider = provider
        self.account = account
        self.lines: list[str] = []
        self.url: str | None = None

    def compose(self) -> ComposeResult:
        with VerticalScroll(classes=overlay_panel_classes(self)):
            yield Static(
                f"Logging in to {self.account}...",
                classes="overlay-title",
                markup=False,
            )
            yield Static("", id="login-lines", markup=False)
            yield self._hidden(Static(self.WAITING, id="login-waiting",
                                      markup=False))
            yield self._hidden(Static(self.LINK_PROMPT, id="login-link-prompt",
                                      markup=False))
            yield self._hidden(Static("", id="login-link", markup=False))
            yield self._hidden(Static("", id="login-status", markup=False))
            yield Static(self.KEYS, id="login-keys", markup=False)

    @staticmethod
    def _hidden(widget: Static) -> Static:
        """Compose it now, show it when there is something to say."""
        widget.display = False
        return widget

    def add_line(self, line: str) -> None:
        """Route one sanitized line to the part of the screen that wants it."""
        if line == HIDDEN_LINE:
            self.query_one("#login-waiting", Static).display = True
            return
        found = self.app.service.sign_in_url(line)
        if found is not None:
            # Only the first. A vendor that reprints its address should not
            # move the link out from under a user reaching for it.
            if self.url is None:
                self._offer(found)
            return
        self.lines.append(line)
        self.query_one("#login-lines", Static).update("\n".join(self.lines))

    def _offer(self, url: str) -> None:
        self.url = url
        self.query_one("#login-link-prompt", Static).display = True
        link = self.query_one("#login-link", Static)
        link.update(url)
        link.display = True
        self.query_one("#login-keys", Static).update(self.LINK_KEYS)

    def _say(self, message: str) -> None:
        status = self.query_one("#login-status", Static)
        status.update(message)
        status.display = True

    def action_copy_link(self) -> None:
        if self.url is None:
            return
        self.app.copy_to_clipboard(self.url)
        self._say(self.COPIED)

    def action_open_link(self) -> None:
        """Hand the link to a browser, and copy it either way.

        Copying first is the point rather than a courtesy: under WSL the
        openers report success while doing nothing, so no return value here is
        worth trusting. The clipboard means the answer to "did it open?" never
        has to be.
        """
        if self.url is None:
            return
        self.app.copy_to_clipboard(self.url)
        self._open(self.url)

    @work(thread=True)
    def _open(self, url: str) -> None:
        """Off the UI thread: the openers allow ten seconds each, which would
        otherwise freeze the screen in the middle of a login."""
        opened = self.app.service.open_sign_in_url(url)
        self.app.call_from_thread(self._opened, opened)

    def _opened(self, opened: bool) -> None:
        self._say(self.OPENED if opened else self.OPEN_FAILED)

    def action_cancel(self) -> None:
        self.dismiss(None)
