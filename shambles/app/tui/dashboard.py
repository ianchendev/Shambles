"""Responsive Textual dashboard composed from an immutable snapshot."""

from typing import Optional, Tuple

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static

from ..snapshot import Account, Group, Snapshot
from .brand import BrandVariant, LOCKUP_MIN_HEIGHT, variant_for
from .widgets import AccountDetails, AccountList


MINIMUM_HEIGHT = 16
BANNER_MIN_HEIGHT = LOCKUP_MIN_HEIGHT


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

    def _surfaces(self) -> str:
        labels = []
        for group in self.snapshot.groups:
            for surface in group.surfaces:
                label = surface.label
                if label not in labels:
                    labels.append(label)
        return (
            "Surfaces: " + " | ".join(labels)
            if labels
            else "Surfaces: Unavailable"
        )

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
        with Vertical(id="dashboard-body"):
            yield Static("SHAMBLES", id="dashboard-title")
            yield Static(self._surfaces(), id="surface-pills")
            with Horizontal(id="main-panes"):
                yield AccountList(self.snapshot, id="account-list")
                yield account_details

    def on_resize(self, event: events.Resize) -> None:
        variant = variant_for(event.size.width)
        self.set_class(variant is BrandVariant.WIDE, "wide")
        self.set_class(variant is BrandVariant.MEDIUM, "medium")
        self.set_class(variant is BrandVariant.COMPACT, "compact")
        self.set_class(event.size.height < MINIMUM_HEIGHT, "too-short")

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
