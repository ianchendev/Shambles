"""The dashboard renders one immutable snapshot at every terminal size."""

import ast
from dataclasses import replace
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console
from textual.app import App, ComposeResult

from shambles.app.snapshot import Account, Group, Snapshot, Surface, Window
from shambles.app.tui.dashboard import Dashboard
from shambles.app.tui.widgets import AccountDetails, AccountList


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
            accounts=[Account("Personal", display_name="Taylor")],
        ),
    ])


class DashboardHarness(App[None]):
    CSS_PATH = Path(__file__).parents[2] / "shambles/app/tui/theme.tcss"

    def __init__(self, snapshot: Snapshot):
        super().__init__()
        self.snapshot = snapshot
        self.selected_messages = []

    def compose(self) -> ComposeResult:
        yield Dashboard(self.snapshot)

    def on_dashboard_account_selected(
        self, message: Dashboard.AccountSelected
    ) -> None:
        self.selected_messages.append((message.provider, message.account))


def rendered_text(widget) -> str:
    output = StringIO()
    console = Console(file=output, force_terminal=False, no_color=True, width=80)
    console.print(widget.content)
    return output.getvalue()


def screen_text(app) -> str:
    return "\n".join(
        strip.text for strip in app.screen._compositor.render_strips()
    )


async def test_wide_dashboard_has_list_and_detail_panes(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        assert app.query_one(Dashboard).has_class("wide")
        accounts = app.query_one("#account-list")
        details = app.query_one("#account-details")
        assert accounts.display and details.display
        assert accounts.region.right <= details.region.x
        assert accounts.region.y == details.region.y
        assert not app.query_one("#inline-details").display
        assert "work@example.test" in screen_text(app)


async def test_medium_dashboard_expands_selected_row(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(60, 32)) as pilot:
        await pilot.pause()
        assert app.query_one(Dashboard).has_class("medium")
        details = app.query_one("#inline-details")
        assert details.display
        assert details.region.width >= 50
        assert not app.query_one("#account-details").display
        assert "session: 22% used" in screen_text(app)


async def test_medium_details_expand_directly_after_the_selected_account(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(60, 32)) as pilot:
        await pilot.pause()
        screen = screen_text(app)
        assert screen.index("Claude / Work") < screen.index("work@example.test")
        assert screen.index("work@example.test") < screen.index("Claude / Personal")

        await pilot.press("down", "enter")
        await pilot.pause()
        screen = screen_text(app)
        assert screen.index("Claude / Personal") < screen.index("personal@example.test")
        assert screen.index("personal@example.test") < screen.index("Codex / Personal")
        assert "work@example.test" not in screen


async def test_narrow_dashboard_hides_decoration(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(40, 24)) as pilot:
        await pilot.pause()
        assert app.query_one(Dashboard).has_class("compact")
        assert not app.query_one("#surface-pills").display
        assert not app.query_one("#account-details").display
        assert app.query_one("#account-list").region.width > 30
        assert app.query_one("#inline-details").region.width > 30
        assert "Claude / Work" in screen_text(app)


async def test_compact_dashboard_keeps_usage_percentage_readable(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(40, 24)) as pilot:
        await pilot.pause()
        assert "session: 22% used" in screen_text(app)


async def test_wide_account_headers_keep_identity_separate_from_login_state(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 32)) as pilot:
        await pilot.pause()
        assert "Claude / Personal" in screen_text(app)
        assert "Login required" in screen_text(app)


@pytest.mark.parametrize("width", [60, 40])
async def test_usage_percentage_and_stale_copy_remain_visible(snapshot, width):
    group = snapshot.groups[0]
    account = group.accounts[0]
    window = replace(account.usage[0], stale=True)
    group = replace(group, accounts=[replace(account, usage=[window])])
    app = DashboardHarness(replace(snapshot, groups=[group]))
    async with app.run_test(size=(width, 32)) as pilot:
        await pilot.pause()
        assert "session: 22% used" in screen_text(app)
        assert "stale" in screen_text(app)
        assert "just now" in screen_text(app)


async def test_short_wide_details_are_accessible_by_keyboard(snapshot):
    group = snapshot.groups[0]
    account = group.accounts[0]
    account = replace(account, usage=[
        *account.usage,
        Window("week", 88, resets_label="Sunday 9AM", age_label="1 hour ago", stale=True),
    ])
    snapshot = replace(snapshot, groups=[
        replace(group, accounts=[account, *group.accounts[1:]]),
    ])
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 16)) as pilot:
        await pilot.pause()
        assert "Claude / Work" in screen_text(app)
        await pilot.press("tab", "end")
        await pilot.pause()
        assert app.focused is app.query_one("#account-details")
        assert app.query_one("#account-details").scroll_y > 0
        assert "session: 22% used" in screen_text(app)
        assert "week: 88% used" in screen_text(app)
        assert "stale" in screen_text(app)
        assert "4:30 PM" in screen_text(app)
        assert "VS Code" in screen_text(app)
        assert screen_text(app).isascii()
        await pilot.press("shift+tab", "down", "enter")
        assert app.selected_messages == [("claude", "Personal")]


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
    app = DashboardHarness(replace(snapshot, groups=[group]))
    async with app.run_test(size=(width, 24)) as pilot:
        await pilot.pause()
        assert screen_text(app).isascii()
        await pilot.press("pagedown")
        await pilot.pause()
        assert app.query_one(AccountList).scroll_y > 0
        assert screen_text(app).isascii()


@pytest.mark.parametrize("size", [(80, 8), (48, 10)])
async def test_too_short_terminal_shows_a_safe_size_message(snapshot, size):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=size) as pilot:
        await pilot.pause()
        assert app.query_one("#terminal-too-small").display
        assert not app.query_one("#dashboard-body").display
        assert "Terminal is too small" in screen_text(app)
        assert "Claude / Work" not in screen_text(app)


async def test_minimum_height_still_leaves_an_account_row_visible(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(48, 16)) as pilot:
        await pilot.pause()
        assert not app.query_one("#terminal-too-small").display
        assert "Claude / Work" in screen_text(app)


async def test_dashboard_uses_the_shared_brand_breakpoints(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 24)) as pilot:
        dashboard = app.query_one(Dashboard)
        assert dashboard.has_class("wide")
        await pilot.resize_terminal(77, 24)
        assert dashboard.has_class("medium")
        await pilot.resize_terminal(47, 24)
        assert dashboard.has_class("compact")


async def test_resizing_preserves_selection_and_recovers_from_too_short(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("down", "down", "enter")
        assert app.selected_messages == [("codex", "Personal")]
        for size in [(60, 32), (40, 24), (80, 8), (100, 32)]:
            await pilot.resize_terminal(*size)
            await pilot.pause()
            assert app.query_one(AccountList).highlighted == 2
            assert app.selected_messages == [("codex", "Personal")]
            screen = screen_text(app)
            if size == (80, 8):
                assert "Terminal is too small" in screen
                assert "Taylor" not in screen
            else:
                assert "Taylor" in screen
                assert "Terminal is too small" not in screen


async def test_selecting_an_account_updates_both_detail_views(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        account_list = app.query_one(AccountList)
        account_list.highlighted = 1
        await pilot.press("enter")

        assert "Personal" in rendered_text(app.query_one("#account-details"))
        assert "Personal" in rendered_text(app.query_one("#inline-details"))
        assert app.selected_messages == [("claude", "Personal")]


async def test_account_details_use_snapshot_labels_and_safe_unavailable_copy(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)):
        details = app.query_one(AccountDetails)
        rendered = rendered_text(details)
        assert "22% used" in rendered
        assert "4:30 PM" in rendered
        assert "just now" in rendered
        assert "VS Code" in rendered

        details.show_account(snapshot.groups[0], snapshot.groups[0].accounts[1])
        rendered = rendered_text(details)
        assert "Resets Unavailable" in rendered


@pytest.mark.parametrize("width", [100, 60, 40])
async def test_no_color_account_copy_is_strict_ascii(snapshot, width):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(width, 32)) as pilot:
        await pilot.pause()
        rendered = rendered_text(app.query_one(AccountDetails))
        assert rendered.isascii()
        assert "\x1b" not in rendered
        screen = screen_text(app)
        assert screen.isascii()
        assert "\x1b" not in screen


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
