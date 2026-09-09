"""Focused, read-only widgets for the terminal dashboard."""

from dataclasses import replace
from typing import Optional, Tuple

from rich.table import Table
from rich.text import Text
from textual import events
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from ..snapshot import Account, Group, Snapshot, Window

GOLD = "#d9a441"
TERRACOTTA = "#e07a5f"
MUTED = "#8b90a0"

#: Wide inspector always shows both quota windows, matching the mockup.
#: ``session`` is Claude's 5-hour bucket; Codex uses the same contract label.
METER_SLOTS = (("5h", ("session", "5h")), ("week", ("week",)))


def _chip(account: Account) -> str:
    if account.active:
        return "Active"
    if account.needs_login:
        return "needs login"
    return "Saved"


def _chip_style(account: Account) -> str:
    if account.active:
        return GOLD
    if account.needs_login:
        return TERRACOTTA
    return MUTED


def _join(parts: list[str], *, unicode: bool) -> str:
    return (" · " if unicode else " | ").join(parts)


def usage_bar(percent: int | None, width: int = 20, *, unicode: bool = True) -> str:
    filled_ch = "█" if unicode else "#"
    empty_ch = "░" if unicode else "-"
    if percent is None:
        return empty_ch * width
    filled = round(max(0, min(100, percent)) * width / 100)
    filled = max(0, min(width, filled))
    return filled_ch * filled + empty_ch * (width - filled)


def _meter_windows(account: Account, *, compact: bool) -> list[Window]:
    """Always 5h then week; missing windows render as empty unavailable bars."""
    by_label = {window.label: window for window in account.usage or []}
    windows = []
    for display, aliases in METER_SLOTS:
        found = next((by_label[name] for name in aliases if name in by_label), None)
        if found is None:
            windows.append(Window(display, None))
        elif found.label == display:
            windows.append(found)
        else:
            windows.append(replace(found, label=display))
    if compact:
        return windows[:1]
    return windows


def _account_row(group: Group, account: Account) -> Table:
    row = Table.grid(expand=True)
    row.add_column(ratio=1, overflow="crop", no_wrap=True)
    row.add_column(justify="right", no_wrap=True, width=12)
    row.add_row(Text(account.name), Text(_chip(account), style=_chip_style(account)))
    return row


def _meter_lines(window: Window, *, width: int, unicode: bool) -> list[Text]:
    if window.used_percent is None:
        percent_copy = "unavailable"
        percent_style = MUTED
    else:
        percent_copy = f"{window.used_percent}%"
        percent_style = ""
    heading = Text.assemble((window.label, "bold"), "  ", (percent_copy, percent_style))
    bar_width = max(4, min(20, width))
    bar = usage_bar(window.used_percent, width=bar_width, unicode=unicode)
    bar_style = MUTED if window.used_percent is None else TERRACOTTA
    lines = [heading, Text(bar, style=bar_style)]
    meta: list[str] = []
    if window.used_percent is not None:
        meta.append(window.resets_label or "unavailable")
    if window.stale:
        meta.append("stale")
    if window.age_label:
        meta.append(window.age_label)
    if meta:
        lines.append(Text(_join(meta, unicode=unicode), style=MUTED))
    return lines


def _context_line(account: Account, *, unicode: bool) -> str:
    if account.active:
        parts = [
            "Already active",
            "m for actions",
            "running sessions keep their login",
        ]
    elif account.needs_login:
        parts = ["l to log in", "cannot switch until this account is signed in"]
    else:
        parts = ["Enter to switch", "m for actions"]
    return _join(parts, unicode=unicode)


def render_account_details(
    group: Group,
    account: Account,
    *,
    width: int = 80,
    unicode: bool = True,
    compact: bool = False,
) -> Table:
    """Build the hero inspector solely from presentation-ready snapshot fields."""

    details = Table.grid(expand=True)
    details.add_column(ratio=1, overflow="crop", no_wrap=True)

    def add_line(line: Text) -> None:
        if line.cell_len > width:
            line = line.copy()
            line.truncate(max(0, width - 3), overflow="crop")
            line.append("." * min(3, width))
        details.add_row(line)

    title = Table.grid(expand=True)
    title.add_column(ratio=1, overflow="crop", no_wrap=True)
    title.add_column(justify="right", no_wrap=True, width=12)
    title.add_row(
        Text(account.name, style="bold"),
        Text(_chip(account), style=_chip_style(account)),
    )
    details.add_row(title)

    identity = account.display_name or account.email
    if identity:
        add_line(Text(identity, style="bold"))

    pills: list[str] = []
    if account.plan:
        pills.append(account.plan)
    if not compact and group.display_name:
        pills.append(group.display_name)
    if pills:
        add_line(Text(_join(pills, unicode=unicode), style=GOLD))

    windows = _meter_windows(account, compact=compact)
    add_line(Text("USAGE", style=GOLD))
    for window in windows:
        for line in _meter_lines(window, width=width, unicode=unicode):
            add_line(line)

    if not compact and group.surfaces:
        add_line(Text("SWITCHES", style=GOLD))
        for surface in group.surfaces:
            line = Text(surface.label, style=GOLD)
            if surface.detail:
                line.append("  ")
                line.append(surface.detail, style=MUTED)
            add_line(line)

    if account.needs_login and account.login_hint:
        add_line(Text(account.login_hint, style=TERRACOTTA))

    if not compact:
        add_line(Text(_context_line(account, unicode=unicode), style=GOLD))

    return details


class AccountRow(ListItem):
    """One account header, with room for its selected inline details."""

    def __init__(self, group: Group, account: Account, *children):
        self.group = group
        self.account = account
        widgets = list(children)
        headers = [widget for widget in widgets if "group-header" in widget.classes]
        rest = [widget for widget in widgets if widget not in headers]
        super().__init__(
            *headers,
            Static(_account_row(group, account), classes="account-row"),
            *rest,
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
        previous_group = None
        for index, (group, account) in enumerate(accounts):
            children = []
            if group is not previous_group:
                children.append(Static(group.display_name, classes="group-header"))
                previous_group = group
            details = None
            if index == initial_index:
                details = AccountDetails(id="inline-details")
                details.show_account(group, account)
                children.append(details)
            row = AccountRow(group, account, *children)
            if details is not None:
                self._selected_row = row
                self._inline_details = details
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


class AccountDetails(VerticalScroll):
    """Details for one account; it never reads stores or computes dates."""

    def __init__(self, **kwargs):
        self._body = Static()
        super().__init__(self._body, **kwargs)
        self._account: Optional[Tuple[Group, Account]] = None

    @property
    def content(self) -> Table:
        return self._body.content

    def show_account(self, group: Group, account: Account) -> None:
        self._account = (group, account)
        unicode = getattr(self.app, "unicode", True)
        compact = self.id == "inline-details"
        self._body.update(render_account_details(
            group,
            account,
            width=self.content_size.width or 80,
            unicode=unicode,
            compact=compact,
        ))
        if compact:
            return
        if account.needs_login:
            self.call_after_refresh(self._reveal_login_callout)
        else:
            self.scroll_home(animate=False)

    def _reveal_login_callout(self) -> None:
        self.scroll_end(animate=False)

    def on_resize(self, event: events.Resize) -> None:
        self._diag_resizes = getattr(self, "_diag_resizes", 0) + 1
        if self._account is not None:
            self.show_account(*self._account)
