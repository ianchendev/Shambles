"""Focused, read-only widgets for the terminal dashboard."""

from typing import Optional, Tuple

from rich.table import Table
from rich.text import Text
from textual import events
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from ..snapshot import Account, Group, Snapshot, Window
from .brand import BrandVariant, variant_for


def _state_copy(account: Account) -> str:
    if account.active:
        return "Active"
    if account.needs_login:
        return "Login required"
    return account.state.replace("_", " ").title() if account.state else "Saved"


def _account_row(group: Group, account: Account) -> Table:
    row = Table.grid(expand=True)
    row.add_column(ratio=1, overflow="crop", no_wrap=True)
    row.add_column(justify="right", overflow="crop", no_wrap=True)
    label = Text()
    label.append(group.display_name, style="bold")
    label.append(" / ")
    label.append(account.name)
    row.add_row(label, Text(_state_copy(account)))
    return row


def _usage_row(window: Window) -> Tuple[Text, Text]:
    percent = (
        "Unavailable"
        if window.used_percent is None
        else f"{window.used_percent}% used"
    )
    reset = window.resets_label or "Unavailable"
    notes = [f"Resets {reset}"]
    if window.age_label:
        notes.append(window.age_label)
    if window.stale:
        notes.append("stale")
    return Text(f"{window.label}: {percent}"), Text(" | ".join(notes))


def render_account_details(
    group: Group, account: Account, *, compact: bool = False
) -> Table:
    """Build account details solely from presentation-ready snapshot fields."""

    details = Table.grid(expand=True, padding=(0, 1))
    details.add_column(ratio=1, overflow="ellipsis", no_wrap=True)
    if not compact:
        details.add_column(justify="right", overflow="ellipsis", no_wrap=True)

    def add_row(label: Text, value: Text) -> None:
        if compact:
            if label.plain:
                details.add_row(label)
            if value.plain:
                details.add_row(value)
        else:
            details.add_row(label, value)

    add_row(Text(account.name, style="bold"), Text(_state_copy(account)))

    identity = account.display_name or account.email
    if identity:
        add_row(Text(identity), Text(account.plan or ""))
    elif account.plan:
        add_row(Text(""), Text(account.plan))

    surfaces = " | ".join(surface.label for surface in group.surfaces)
    add_row(Text("Surfaces"), Text(surfaces or "Unavailable"))

    if account.usage:
        for window in account.usage:
            add_row(*_usage_row(window))
    else:
        add_row(Text("Usage"), Text("Unavailable"))

    if account.needs_login:
        add_row(Text("Login required"), Text(account.login_hint or ""))
    return details


class AccountRow(ListItem):
    """One account header, with room for its selected inline details."""

    def __init__(self, group: Group, account: Account, *children):
        self.group = group
        self.account = account
        super().__init__(
            Static(_account_row(group, account), classes="account-row"),
            *children,
        )


class AccountList(ListView):
    """Keyboard-selectable accounts with details nested in the selected row."""

    class Selected(Message):
        def __init__(self, list_view: ListView, item: AccountRow, index: int):
            self.provider = item.group.provider
            self.account = item.account.name
            super().__init__()

    def __init__(self, snapshot: Snapshot, **kwargs):
        accounts = [
            (group, account)
            for group in snapshot.groups
            for account in group.accounts
        ]
        initial_index = next(
            (index for index, (_, account) in enumerate(accounts) if account.active),
            0,
        )
        rows = []
        self._selected_row: Optional[AccountRow] = None
        self._inline_details: Optional[AccountDetails] = None
        for index, (group, account) in enumerate(accounts):
            if index == initial_index:
                details = AccountDetails(id="inline-details")
                details.show_account(group, account)
                row = AccountRow(group, account, details)
                self._selected_row = row
                self._inline_details = details
            else:
                row = AccountRow(group, account)
            rows.append(row)
        super().__init__(*rows, initial_index=initial_index, **kwargs)

    @property
    def highlighted(self) -> Optional[int]:
        """The highlighted account index, independent of layout composition."""
        return self.index

    @highlighted.setter
    def highlighted(self, index: Optional[int]) -> None:
        self.index = index

    async def show_account(self, provider: str, account: str) -> None:
        for row in self.children:
            if row.group.provider == provider and row.account.name == account:
                if row is self._selected_row:
                    return
                if self._inline_details is not None:
                    await self._inline_details.remove()
                details = AccountDetails(id="inline-details")
                details.show_account(row.group, row.account)
                await row.mount(details)
                self._selected_row = row
                self._inline_details = details
                self.call_after_refresh(self.scroll_to_widget, row, animate=False)
                return


class AccountDetails(Static):
    """Details for one account; it never reads stores or computes dates."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._account: Optional[Tuple[Group, Account]] = None

    def show_account(self, group: Group, account: Account) -> None:
        self._account = (group, account)
        self.update(render_account_details(
            group,
            account,
            compact=variant_for(self.content_size.width) is BrandVariant.COMPACT,
        ))

    def on_resize(self, event: events.Resize) -> None:
        if self._account is not None:
            self.show_account(*self._account)
