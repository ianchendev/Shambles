"""The dashboard renders one immutable snapshot at every terminal size."""

import ast
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from textual.app import App, ComposeResult
from textual.binding import Binding

from settling import layout_report, screen_text, settled

from shambles.app.snapshot import Account, Group, Snapshot, Surface, Window
from shambles.app.tui.dashboard import Dashboard
from shambles.app.tui.widgets import (
    AccountDetails,
    AccountList,
    render_account_details,
    usage_bar,
)


@pytest.fixture
def snapshot():
    return Snapshot(1, groups=[
        Group(
            "claude",
            "Claude",
            surfaces=[
                Surface("terminal", "Terminal"),
                Surface("vscode", "VS Code"),
            ],
            accounts=[
                Account(
                    "Work",
                    email="work@example.test",
                    plan="Max 5x",
                    active=True,
                    state="healthy",
                    usage=[
                        Window(
                            "session",
                            22,
                            resets_at_ms=1_788_000_000_000,
                            resets_label="4:30 PM",
                            age_label="just now",
                        ),
                    ],
                ),
                Account(
                    "Personal",
                    email="personal@example.test",
                    state="unknown",
                    needs_login=True,
                    login_hint="Run claude login",
                    usage=[
                        Window(
                            "week",
                            33,
                            resets_at_ms=None,
                        ),
                    ],
                ),
            ],
        ),
        Group(
            "codex",
            "Codex",
            surfaces=[Surface("terminal", "Terminal")],
            accounts=[
                Account(
                    "Personal",
                    display_name="Taylor",
                    usage=[
                        Window("session", 2, resets_label="resets 4:00 PM"),
                        Window("week", 4, resets_label="resets Mon"),
                    ],
                ),
            ],
        ),
    ])


class DashboardHarness(App[None]):
    CSS_PATH = Path(__file__).parents[2] / "shambles/app/tui/theme.tcss"
    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
    ]

    def __init__(self, snapshot: Snapshot, *, unicode: bool = True):
        super().__init__()
        self.snapshot = snapshot
        self.unicode = unicode
        self.selected_messages = []

    def compose(self) -> ComposeResult:
        yield Dashboard(self.snapshot)

    def action_cursor_down(self) -> None:
        self.query_one(AccountList).action_cursor_down()

    def action_cursor_up(self) -> None:
        self.query_one(AccountList).action_cursor_up()

    def on_dashboard_account_selected(
        self, message: Dashboard.AccountSelected
    ) -> None:
        self.selected_messages.append((message.provider, message.account))


def table_text(table) -> str:
    output = StringIO()
    console = Console(file=output, force_terminal=False, no_color=True, width=80)
    console.print(table)
    return output.getvalue()


def rendered_text(widget) -> str:
    return table_text(widget.content)


class _LateText(App[None]):
    """Shows its text only after real time passes, as a slow runner does.

    A layout Textual finishes on a timer is invisible to any number of
    zero-length pumps that complete before the timer fires; on a busy CI
    runner that is the usual case.
    """

    def compose(self) -> ComposeResult:
        from textual.widgets import Static
        yield Static("", id="late")

    def on_mount(self) -> None:
        self.set_timer(0.3, lambda: self.query_one("#late").update("Taylor"))


async def test_settled_waits_for_time_not_for_a_count_of_pumps():
    app = _LateText()
    async with app.run_test(size=(40, 5)) as pilot:
        await settled(pilot, app, lambda: "Taylor" in screen_text(app))


async def test_a_condition_that_never_holds_fails_with_the_whole_screen():
    app = _LateText()
    async with app.run_test(size=(40, 5)) as pilot:
        with pytest.raises(AssertionError) as failed:
            await settled(pilot, app, lambda: "Morgan" in screen_text(app),
                          within=0.5)
    message = str(failed.value)
    assert "Morgan" in message            # the condition, by its source
    assert "--- widgets ---" in message and "#late" in message


async def test_wide_dashboard_has_list_and_detail_panes(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await settled(pilot, app, lambda: (
            app.query_one(Dashboard).has_class('wide')
            and app.query_one('#account-list').display and app.query_one('#account-details').display
            and app.query_one('#account-list').region.right <= app.query_one('#account-details').region.x
            and app.query_one('#account-list').region.y == app.query_one('#account-details').region.y
            and not app.query_one('#inline-details').display
            and 'work@example.test' in screen_text(app)))
        assert app.query_one(Dashboard).has_class("wide")
        accounts = app.query_one("#account-list")
        details = app.query_one("#account-details")
        assert accounts.display and details.display
        assert accounts.region.right <= details.region.x
        assert accounts.region.y == details.region.y
        assert not app.query_one("#inline-details").display
        assert "work@example.test" in screen_text(app)


def test_usage_bar_fills_and_falls_back_to_ascii():
    assert "█" in usage_bar(22, width=10, unicode=True)
    assert usage_bar(None, width=4, unicode=True) == "░░░░"
    assert usage_bar(50, width=4, unicode=False) == "##--"
    assert usage_bar(None, width=4, unicode=False) == "----"


def test_hero_details_use_meters_pills_and_context(snapshot):
    group, account = snapshot.groups[0], snapshot.groups[0].accounts[0]
    rendered = table_text(render_account_details(group, account, width=80, unicode=True))
    assert "Work" in rendered
    assert "Active" in rendered
    assert "work@example.test" in rendered
    assert "Max 5x" in rendered
    assert "Claude" in rendered
    assert "USAGE" in rendered
    assert "5h" in rendered
    assert "week" in rendered
    assert "unavailable" in rendered
    assert "22%" in rendered
    assert "█" in rendered
    assert "SWITCHES" in rendered
    assert "Terminal" in rendered
    assert "Already active · m for actions · running sessions keep their login" in rendered
    assert "Claude / Work" not in rendered
    assert "session: 22% used" not in rendered


async def test_wide_hero_shows_identity_meter_and_surfaces(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await settled(pilot, app, lambda: (
            'work@example.test' in screen_text(app)
            and 'Max 5x' in screen_text(app)
            and 'USAGE' in screen_text(app)
            and '5h' in screen_text(app)
            and 'week' in screen_text(app)
            and 'unavailable' in screen_text(app)
            and '22%' in screen_text(app)
            and 'SWITCHES' in screen_text(app)
            and 'Terminal' in screen_text(app)
            and 'Already active' in screen_text(app)
            and 'Claude / Work' not in screen_text(app)
            and 'session: 22% used' not in screen_text(app)))
        screen = screen_text(app)
        assert "work@example.test" in screen
        assert "Max 5x" in screen
        assert "USAGE" in screen
        assert "5h" in screen
        assert "week" in screen
        assert "unavailable" in screen
        assert "22%" in screen
        assert "SWITCHES" in screen
        assert "Terminal" in screen
        assert "Already active" in screen
        assert "Claude / Work" not in screen
        assert "session: 22% used" not in screen


async def test_hero_needs_login_callout(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        app.query_one(AccountList).highlighted = 1
        await pilot.press("enter")
        await settled(pilot, app, lambda: (
            'needs login' in screen_text(app)
            and ('Enter or l to sign in' in screen_text(app))
            and 'Run claude login' not in screen_text(app)
            and 'cannot switch' not in screen_text(app)))
        screen = screen_text(app)
        assert "needs login" in screen
        assert "Enter or l to sign in" in screen
        # The vendor's own advice is wrong for a parked account: run in a
        # terminal, it signs in whichever profile is live, not this one.
        assert "Run claude login" not in screen
        assert "cannot switch" not in screen


def test_an_active_account_that_needs_login_says_how_to_sign_in(snapshot):
    group = snapshot.groups[0]
    account = replace(group.accounts[1], active=True)
    rendered = table_text(render_account_details(group, account, width=80,
                                                 unicode=True))
    assert "Enter or l to sign in" in rendered
    assert "Already active" not in rendered


async def test_medium_dashboard_expands_selected_row(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(60, 32)) as pilot:
        await settled(pilot, app, lambda: (
            app.query_one(Dashboard).has_class('medium')
            and app.query_one('#inline-details').display
            and app.query_one('#inline-details').region.width >= 50
            and not app.query_one('#account-details').display
            and '22%' in screen_text(app)
            and 'SWITCHES' not in screen_text(app)))
        assert app.query_one(Dashboard).has_class("medium")
        details = app.query_one("#inline-details")
        assert details.display
        assert details.region.width >= 50
        assert not app.query_one("#account-details").display
        assert "22%" in screen_text(app)
        assert "SWITCHES" not in screen_text(app)


async def test_medium_details_expand_directly_after_the_selected_account(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(60, 32)) as pilot:
        await settled(pilot, app, lambda: (
            screen_text(app).index('Work') < screen_text(app).index('work@example.test')
            and screen_text(app).index('work@example.test') < screen_text(app).index('needs login')))
        screen = screen_text(app)
        assert screen.index("Work") < screen.index("work@example.test")
        assert screen.index("work@example.test") < screen.index("needs login")

        await pilot.press("down", "enter")
        await settled(pilot, app, lambda: (
            screen_text(app).index('Personal') < screen_text(app).index('personal@example.test')
            and screen_text(app).index('personal@example.test') < screen_text(app).index('Saved')
            and 'work@example.test' not in screen_text(app)))
        screen = screen_text(app)
        assert screen.index("Personal") < screen.index("personal@example.test")
        assert screen.index("personal@example.test") < screen.index("Saved")
        assert "work@example.test" not in screen


async def test_narrow_dashboard_hides_decoration(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(40, 24)) as pilot:
        await settled(pilot, app, lambda: (
            app.query_one(Dashboard).has_class('compact')
            and list(app.query('#surface-pills')) == []
            and not app.query_one('#account-details').display
            and app.query_one('#shortcut-footer').display
            and 'a add' in screen_text(app)
            and 'j/k move' not in screen_text(app)
            and app.query_one('#account-list').region.width > 30
            and app.query_one('#inline-details').region.width > 30
            and 'Work' in screen_text(app)
            and 'Claude / Work' not in screen_text(app)))
        assert app.query_one(Dashboard).has_class("compact")
        assert list(app.query("#surface-pills")) == []
        assert not app.query_one("#account-details").display
        assert app.query_one("#shortcut-footer").display
        assert "a add" in screen_text(app)
        assert "j/k move" not in screen_text(app)
        assert app.query_one("#account-list").region.width > 30
        assert app.query_one("#inline-details").region.width > 30
        assert "Work" in screen_text(app)
        assert "Claude / Work" not in screen_text(app)


async def test_compact_dashboard_keeps_usage_percentage_readable(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(40, 24)) as pilot:
        await settled(pilot, app, lambda: (
            '22%' in screen_text(app)
            and 'session: 22% used' not in screen_text(app)
            and 'week' not in screen_text(app)))
        screen = screen_text(app)
        assert "22%" in screen
        assert "session: 22% used" not in screen
        assert "week" not in screen


def test_compact_inspector_shows_only_the_5h_meter(snapshot):
    group, account = snapshot.groups[0], snapshot.groups[0].accounts[0]
    rendered = table_text(render_account_details(
        group, account, width=40, unicode=True, compact=True))
    assert "USAGE" in rendered
    assert "5h" in rendered
    assert "22%" in rendered
    assert "week" not in rendered
    assert "SWITCHES" not in rendered


async def test_wide_codex_hero_shows_5h_and_week(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        app.query_one(AccountList).highlighted = 2
        await pilot.press("enter")
        await settled(pilot, app, lambda: (
            'Taylor' in screen_text(app)
            and '5h' in screen_text(app)
            and '22%' not in screen_text(app)
            and '2%' in screen_text(app)
            and 'week' in screen_text(app)
            and '4%' in screen_text(app)))
        screen = screen_text(app)
        assert "Taylor" in screen
        assert "5h" in screen
        assert "22%" not in screen
        assert "2%" in screen
        assert "week" in screen
        assert "4%" in screen


async def test_provider_headers_are_spaced_from_accounts(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await settled(pilot, app, lambda: (
            len(list(app.query('.group-header'))) == 2))
        headers = list(app.query(".group-header"))
        assert len(headers) == 2
        first, second = headers
        assert first.styles.padding.top == 0
        assert second.styles.padding.top > 0
        screen = screen_text(app)
        assert "Claude" in screen
        assert "Codex" in screen


async def test_wide_account_headers_keep_identity_separate_from_login_state(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 32)) as pilot:
        await settled(pilot, app, lambda: (
            'Personal' in screen_text(app)
            and 'needs login' in screen_text(app)
            and 'Claude / Personal' not in screen_text(app)
            and 'Login required' not in screen_text(app)))
        screen = screen_text(app)
        assert "Personal" in screen
        assert "needs login" in screen
        assert "Claude / Personal" not in screen
        assert "Login required" not in screen


async def test_list_groups_by_provider_and_keeps_one_line_rows(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await settled(pilot, app, lambda: (
            'Claude' in screen_text(app)
            and 'Codex' in screen_text(app)
            and 'Claude / Work' not in screen_text(app)
            and app.query_one(AccountList).highlighted == 0))
        screen = screen_text(app)
        assert "Claude" in screen  # Group.display_name in fixture
        assert "Codex" in screen
        assert "Claude / Work" not in screen
        accounts = app.query_one(AccountList)
        assert accounts.highlighted == 0  # Work is active
        await pilot.press("down")
        await settled(pilot, app, lambda: accounts.highlighted == 1)
        assert accounts.highlighted == 1


@pytest.mark.parametrize("width", [60, 40])
async def test_usage_percentage_and_stale_copy_remain_visible(snapshot, width):
    group = snapshot.groups[0]
    account = group.accounts[0]
    window = replace(account.usage[0], stale=True)
    group = replace(group, accounts=[replace(account, usage=[window])])
    app = DashboardHarness(replace(snapshot, groups=[group]))
    async with app.run_test(size=(width, 32)) as pilot:
        await settled(pilot, app, lambda: (
            '22%' in screen_text(app)
            and 'session: 22% used' not in screen_text(app)
            and 'stale' in screen_text(app)
            and 'just now' in screen_text(app)))
        screen = screen_text(app)
        assert "22%" in screen
        assert "session: 22% used" not in screen
        assert "stale" in screen
        assert "just now" in screen


async def test_short_wide_details_are_accessible_by_keyboard(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 16)) as pilot:
        await settled(pilot, app, lambda: (
            not app.query_one(Dashboard).has_class('wide')
            and 'OFFLINE' not in screen_text(app)
            and app.query_one('#inline-details').display
            and '22%' in rendered_text(app.query_one('#inline-details'))))
        dash = app.query_one(Dashboard)
        assert not dash.has_class("wide")
        screen = screen_text(app)
        assert "OFFLINE" not in screen
        details = app.query_one("#inline-details")
        assert details.display
        rendered = rendered_text(details)
        assert "22%" in rendered
        accounts = app.query_one(AccountList)
        await pilot.press("j")
        await settled(pilot, app, lambda: accounts.highlighted == 1)
        assert accounts.highlighted == 1


@pytest.mark.parametrize("width", [78, 40])
async def test_ascii_fallback_covers_long_values_and_scrolled_lists(snapshot, width):
    group = snapshot.groups[0]
    account = replace(
        group.accounts[0],
        email="very.long.account.identity.with.more.characters@example.test",
        usage=[replace(group.accounts[0].usage[0], stale=True)],
    )
    group = replace(group, accounts=[account] + [
        Account(f"Account {index}") for index in range(30)
    ])
    app = DashboardHarness(replace(snapshot, groups=[group]), unicode=False)
    async with app.run_test(size=(width, 24)) as pilot:
        # Drawn first: a screen that has not drawn yet is ASCII too.
        await settled(pilot, app, lambda: "Account 0" in screen_text(app))
        screen = screen_text(app)
        assert "⏎" not in screen
        assert "·" not in screen
        assert "▊" not in screen
        assert screen.isascii()
        await pilot.press("pagedown")
        await settled(pilot, app, lambda: (
            app.query_one(AccountList).scroll_y > 0
            and screen_text(app).isascii()))
        assert app.query_one(AccountList).scroll_y > 0
        assert screen_text(app).isascii()


async def test_ascii_dashboard_chrome_is_strict_ascii(snapshot):
    app = DashboardHarness(snapshot, unicode=False)
    async with app.run_test(size=(100, 32)) as pilot:
        await settled(pilot, app, lambda: (
            screen_text(app).isascii()
            and '⏎' not in screen_text(app)
            and '·' not in screen_text(app)
            and '▊' not in screen_text(app)
            and 'Enter switch' in screen_text(app)
            and app.query_one(Dashboard).has_class('ascii')))
        screen = screen_text(app)
        assert screen.isascii()
        assert "⏎" not in screen
        assert "·" not in screen
        assert "▊" not in screen
        assert "Enter switch" in screen
        assert app.query_one(Dashboard).has_class("ascii")


def test_hero_context_line_ellipsizes_like_other_long_lines(snapshot):
    group = snapshot.groups[0]
    account = replace(group.accounts[0], email="a@b.c", display_name="A")
    rendered = table_text(render_account_details(group, account, width=18, unicode=True))
    assert "Already active" in rendered
    assert "running sessions keep their login" not in rendered
    assert "..." in rendered


async def test_needs_login_callout_is_reachable_at_78x28(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 28)) as pilot:
        app.query_one(AccountList).highlighted = 1
        await pilot.press("enter")
        details = app.query_one("#account-details")
        # On screen already, or reachable by scrolling the pane.
        await settled(pilot, app, lambda: (
            "l to sign in" in screen_text(app) or details.max_scroll_y > 0))
        if "l to sign in" not in screen_text(app):
            assert details.styles.scrollbar_size_vertical > 0
            details.scroll_end(animate=False)
        await settled(pilot, app, lambda: "l to sign in" in screen_text(app))


@pytest.mark.parametrize("size", [(80, 8), (48, 10)])
async def test_too_short_terminal_shows_a_safe_size_message(snapshot, size):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=size) as pilot:
        await settled(pilot, app, lambda: (
            app.query_one('#terminal-too-small').display
            and not app.query_one('#dashboard-body').display
            and 'Terminal is too small' in screen_text(app)
            and 'Work' not in screen_text(app)
            and 'Claude / Work' not in screen_text(app)))
        assert app.query_one("#terminal-too-small").display
        assert not app.query_one("#dashboard-body").display
        assert "Terminal is too small" in screen_text(app)
        assert "Work" not in screen_text(app)
        assert "Claude / Work" not in screen_text(app)


async def test_minimum_height_still_leaves_an_account_row_visible(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(48, 16)) as pilot:
        await settled(pilot, app, lambda: (
            not app.query_one('#terminal-too-small').display
            and 'Work' in screen_text(app)
            and 'Claude / Work' not in screen_text(app)))
        assert not app.query_one("#terminal-too-small").display
        assert "Work" in screen_text(app)
        assert "Claude / Work" not in screen_text(app)


async def test_wide_dashboard_shows_lockup_and_footer(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await settled(pilot, app, lambda: (
            'OFFLINE' in screen_text(app)
            and 'a add' in screen_text(app)
            and 'x eject' in screen_text(app)
            and 'j/k move' in screen_text(app)
            and app.query_one(Dashboard).has_class('wide')))
        screen = screen_text(app)
        assert "OFFLINE" in screen
        assert "a add" in screen
        assert "x eject" in screen
        assert "j/k move" in screen
        assert app.query_one(Dashboard).has_class("wide")


async def test_wide_minimum_shows_full_bleed_lockup_and_fitting_footer(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 24)) as pilot:
        await settled(pilot, app, lambda: (
            app.query_one(Dashboard).has_class('wide')
            and 'OFFLINE' in screen_text(app)
            and 'j/k move' not in screen_text(app)
            and 'q quit' in screen_text(app)
            and '? help' in screen_text(app)
            and 'a add' in screen_text(app)))
        screen = screen_text(app)
        assert app.query_one(Dashboard).has_class("wide")
        assert "OFFLINE" in screen
        assert "j/k move" not in screen
        assert "q quit" in screen
        assert "? help" in screen
        assert "a add" in screen


async def test_wide_but_short_drops_lockup_and_uses_inline_details(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 16)) as pilot:
        await settled(pilot, app, lambda: (
            not app.query_one(Dashboard).has_class('wide')
            and 'OFFLINE' not in screen_text(app)
            and ('>_ ⇄ SHAMBLES' in screen_text(app) or '>_ <-> SHAMBLES' in screen_text(app))
            and not app.query_one('#account-details').display
            and app.query_one('#inline-details').display))
        dash = app.query_one(Dashboard)
        assert not dash.has_class("wide")
        assert "OFFLINE" not in screen_text(app)
        assert ">_ ⇄ SHAMBLES" in screen_text(app) or ">_ <-> SHAMBLES" in screen_text(app)
        assert not app.query_one("#account-details").display
        assert app.query_one("#inline-details").display


async def test_dashboard_uses_the_shared_brand_breakpoints(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 24)) as pilot:
        dashboard = app.query_one(Dashboard)
        assert dashboard.has_class("wide")
        await pilot.resize_terminal(77, 24)
        # The class is set by the Resize handler, so it cannot be read until
        # that event has actually been processed. Without this the assertion
        # races the event loop -- Linux happened to win the race and Windows
        # lost it, which is how this passed locally and failed in CI.
        await settled(pilot, app, lambda: dashboard.has_class('medium'))
        assert dashboard.has_class("medium")
        await pilot.resize_terminal(47, 24)
        await settled(pilot, app, lambda: dashboard.has_class('compact'))
        assert dashboard.has_class("compact")


async def test_resizing_preserves_selection_and_recovers_from_too_short(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("down", "down", "enter")
        await settled(pilot, app, lambda: (
            app.selected_messages == [('codex', 'Personal')]))
        assert app.selected_messages == [("codex", "Personal")]
        for size in [(60, 32), (40, 24), (80, 8), (100, 32)]:
            await pilot.resize_terminal(*size)
            shown = ("Terminal is too small" if size == (80, 8)
                     else "Taylor")
            await settled(pilot, app, lambda: shown in screen_text(app))
            assert app.query_one(AccountList).highlighted == 2
            assert app.selected_messages == [("codex", "Personal")]
            screen = screen_text(app)
            if size == (80, 8):
                assert "Taylor" not in screen, layout_report(app, screen)
            else:
                assert "Terminal is too small" not in screen, layout_report(
                    app, screen)


async def test_selecting_an_account_updates_both_detail_views(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        account_list = app.query_one(AccountList)
        account_list.highlighted = 1
        await pilot.press("enter")
        await settled(pilot, app, lambda: (
            'Personal' in rendered_text(app.query_one('#account-details'))
            and 'Personal' in rendered_text(app.query_one('#inline-details'))
            and app.selected_messages == [('claude', 'Personal')]))

        assert "Personal" in rendered_text(app.query_one("#account-details"))
        assert "Personal" in rendered_text(app.query_one("#inline-details"))
        assert app.selected_messages == [("claude", "Personal")]


async def test_account_details_use_snapshot_labels_and_safe_unavailable_copy(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)):
        details = app.query_one("#account-details", AccountDetails)
        rendered = rendered_text(details)
        assert "22%" in rendered
        assert "4:30 PM" in rendered
        assert "just now" in rendered
        assert "VS Code" in rendered
        assert "22% used" not in rendered

        details.show_account(snapshot.groups[0], snapshot.groups[0].accounts[1])
        rendered = rendered_text(details)
        assert "33%" in rendered
        assert "unavailable" in rendered
        assert "Resets Unavailable" not in rendered


@pytest.mark.parametrize("compact", [False, True])
def test_no_color_account_copy_is_strict_ascii(snapshot, compact):
    group, account = snapshot.groups[0], snapshot.groups[0].accounts[0]
    rendered = table_text(render_account_details(
        group,
        account,
        width=40 if compact else 80,
        unicode=False,
        compact=compact,
    ))
    assert rendered.isascii()
    assert "\x1b" not in rendered
    assert "#" in rendered


def test_widget_modules_do_not_import_mutation_layers():
    imports = set()
    for path in (
        Path("shambles/app/tui/widgets.py"),
        Path("shambles/app/tui/dashboard.py"),
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                imports.add(module)
                imports.update(f"{module}.{alias.name}" for alias in node.names)

    forbidden = {"switcher", "login", "eject"}
    assert not {name.rsplit(".", 1)[-1] for name in imports}.intersection(forbidden)


@pytest.mark.parametrize("width", [40, 60, 100])
async def test_details_are_not_truncated_to_a_width_the_pane_no_longer_has(
        snapshot, width):
    """Content follows the pane, not the last Resize it happened to receive.

    ``render_account_details`` truncates to fit, so its output is right for
    exactly one width. A pane can reach its final width without a Resize of
    its own, and content frozen at a narrow mid-layout pass then reads "wo..."
    and "5h..." in a pane with room for both -- which is how six of these
    tests failed on Windows while Linux, which got a second Resize, passed.
    """
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(width, 32)) as pilot:
        await settled(pilot, app, lambda: (
            "work@example.test" in screen_text(app)
            and "22%" in screen_text(app)))


async def test_an_80_column_footer_still_names_the_sign_in_key(snapshot):
    """At 80x24, the commonest terminal, the compact footer dropped l login,
    so the one key that fixes a lapsed account was not on screen."""
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(80, 24)) as pilot:
        await settled(pilot, app, lambda: 'l login' in screen_text(app))
        assert "l login" in screen_text(app)


# CI probe on macOS (draft PR #49): after a resize from 100 to 60 columns the
# header stayed 23 rows tall around the one-line compact header -- the wide
# 76-column lockup, wrapped at 60 -- and pushed the account list off the
# screen. A forced refresh did not bring it back. The header's height was
# measured from the text last pushed into it, not from the size it was being
# measured at; nothing can leave those two disagreeing if the header derives
# its text from that size.

async def test_the_header_measures_for_the_size_it_is_measured_at(snapshot):
    from textual.geometry import Size

    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await settled(pilot, app, lambda: (
            app.query_one('#dashboard-header').region.height == 11
            and app.query_one('#dashboard-header').get_content_height(Size(60, 32), Size(60, 32), 60) == 1
            and app.query_one('#dashboard-header').get_content_height(Size(100, 32), Size(100, 32), 100) == 11))
        header = app.query_one("#dashboard-header")
        assert header.region.height == 11

        narrow = Size(60, 32)
        assert header.get_content_height(narrow, narrow, 60) == 1
        wide = Size(100, 32)
        assert header.get_content_height(wide, wide, 100) == 11


async def test_the_header_follows_every_resize(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        for size, rows in [((60, 32), 1), ((100, 32), 11), ((40, 24), 1),
                           ((100, 32), 11)]:
            await pilot.resize_terminal(*size)
            await settled(pilot, app, lambda: (
                app.query_one('#dashboard-header').region.height == rows))
            header = app.query_one("#dashboard-header")
            assert header.region.height == rows, (size, header.region)
