"""Responsive Textual dashboard composed from an immutable snapshot."""

from typing import Optional, Tuple

from rich.cells import cell_len
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from ..snapshot import Account, Group, Snapshot
from .brand import LOCKUP_MIN_HEIGHT, header_kind
from .widgets import AccountDetails, AccountList, BrandHeader, notices_text


MINIMUM_HEIGHT = 16
BANNER_MIN_HEIGHT = LOCKUP_MIN_HEIGHT

FULL_FOOTER = (
    "j/k move · ⏎ switch · a add · x eject · m menu · "
    "l login · r refresh · ? help · q quit"
)
# Eject gives way to login at this width: it is rare, still listed under ?,
# and l is the only key that fixes an account that needs a login.
COMPACT_FOOTER = "⏎ switch · l login · a add · m menu · ? help · q quit"
FULL_FOOTER_ASCII = (
    "j/k move | Enter switch | a add | x eject | m menu | "
    "l login | r refresh | ? help | q quit"
)
COMPACT_FOOTER_ASCII = "Enter switch | l login | a add | m menu | ? help | q quit"


def _paint_footer(text: str) -> str:
    sep = " | " if " | " in text else " · "
    gold = "|" if sep == " | " else "·"
    painted = []
    for part in text.split(sep):
        key, _, label = part.partition(" ")
        painted.append(f"[#e07a5f]{key}[/] {label}")
    return f" [#d9a441]{gold}[/] ".join(painted)


def _footer_for_width(width: int, *, wide: bool, unicode: bool = True) -> str:
    full = FULL_FOOTER if unicode else FULL_FOOTER_ASCII
    compact = COMPACT_FOOTER if unicode else COMPACT_FOOTER_ASCII
    if wide and cell_len(full) <= width:
        return full
    return compact


class Dashboard(Widget):
    """A read-only account dashboard that adapts at the brand breakpoints."""

    class AccountSelected(Message):
        def __init__(self, provider: str, account: str):
            self.provider = provider
            self.account = account
            super().__init__()

    def __init__(self, snapshot: Snapshot, **kwargs):
        super().__init__(**kwargs)
        self.snapshot = snapshot

    def _initial_account(self) -> Optional[Tuple[Group, Account]]:
        first = None
        for group in self.snapshot.groups:
            for account in group.accounts:
                first = first or (group, account)
                if account.active:
                    return group, account
        return first

    def compose(self) -> ComposeResult:
        selected = self._initial_account()
        account_details = AccountDetails(id="account-details")
        if selected is not None:
            group, account = selected
            account_details.show_account(group, account)

        yield Static(
            f"Terminal is too small. Use at least {MINIMUM_HEIGHT} rows.",
            id="terminal-too-small",
        )
        yield BrandHeader(id="dashboard-header")
        # What is true about a provider rather than an account: a login
        # nobody saved, a stale marker, an override. Hidden when all is well.
        notices = Static(notices_text(self.snapshot), id="provider-notices",
                         markup=False)
        notices.display = bool(notices_text(self.snapshot))
        yield notices
        # What a switch in progress is waiting for. Hidden unless it waits.
        status = Static(id="switch-status", markup=False)
        status.display = False
        yield status
        with Vertical(id="dashboard-body"):
            with Horizontal(id="main-panes"):
                yield AccountList(self.snapshot, id="account-list")
                yield account_details
        yield Static(id="shortcut-footer")

    def show_status(self, text: str) -> None:
        """Say what a running action is waiting for; empty text hides it."""
        status = self.query_one("#switch-status", Static)
        status.update(text)
        status.display = bool(text)

    def on_resize(self, event: events.Resize) -> None:
        width, height = event.size.width, event.size.height
        wide = header_kind(width, height) == "lockup"
        unicode = getattr(self.app, "unicode", True)
        self.set_class(wide, "wide")
        self.set_class(width >= 48 and not wide, "medium")
        self.set_class(width < 48, "compact")
        self.set_class(height < MINIMUM_HEIGHT, "too-short")
        self.set_class(not unicode, "ascii")
        self.query_one("#shortcut-footer", Static).update(
            _paint_footer(_footer_for_width(width, wide=wide, unicode=unicode))
        )

    async def on_account_list_selected(self, event: AccountList.Selected) -> None:
        selected = self._find_account(event.provider, event.account)
        if selected is None:
            return
        group, account = selected
        self.query_one("#account-details", AccountDetails).show_account(
            group, account
        )
        await self.query_one(AccountList).show_account(event.provider, event.account)
        self.post_message(self.AccountSelected(event.provider, event.account))

    def _find_account(
        self, provider_name: str, account_name: str
    ) -> Optional[Tuple[Group, Account]]:
        for group in self.snapshot.groups:
            if group.provider != provider_name:
                continue
            for account in group.accounts:
                if account.name == account_name:
                    return group, account
        return None
