"""The terminal shell navigates immutable state and draws onboarding once."""

from copy import deepcopy
from dataclasses import replace

import pytest
from textual.events import Key

from shambles.app.service import ActionError, ActionResult
from shambles.app.snapshot import Account, Group, Snapshot, Surface
from shambles.app.tui.application import BoxPhase, OnboardingFrame, ShamblesTUI
from shambles.app.tui.brand import BrandVariant, brand_text
from shambles.app.tui.dashboard import Dashboard
from shambles.app.tui.widgets import AccountList


class SnapshotService:
    """Keep UI tests at the service boundary without reading real stores."""

    def __init__(self, snapshot):
        self.current = snapshot
        self.refreshed = snapshot
        self.refresh_result = None

    def snapshot(self):
        return self.current

    def refresh(self):
        return self.refresh_result or ActionResult(
            True, "refresh", snapshot=self.refreshed
        )


@pytest.fixture
def service():
    return SnapshotService(Snapshot(1, groups=[
        Group("claude", "Claude", surfaces=[Surface("terminal", "Terminal")],
              accounts=[Account("Personal", active=True),
                        Account("Work", email="work@example.test")]),
        Group("codex", "Codex", accounts=[Account("Personal")]),
    ]))


@pytest.fixture
def empty_service():
    return SnapshotService(Snapshot(1, groups=[Group("claude", "Claude")]))


@pytest.fixture
def stepped_motion(monkeypatch):
    """Pause only the clock; tests advance the production phase callback."""
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("SHAMBLES_NO_MOTION", raising=False)
    original = OnboardingFrame.set_interval

    def paused_interval(self, interval, callback, **kwargs):
        return original(self, interval, callback, **{**kwargs, "pause": True})

    monkeypatch.setattr(OnboardingFrame, "set_interval", paused_interval)


def screen_text(app):
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


@pytest.mark.parametrize("keys", [("j", "k"), ("down", "up")])
@pytest.mark.parametrize("width", [100, 60])
async def test_cursor_keys_update_selection_and_visible_details(service, keys, width):
    app = ShamblesTUI(service)
    async with app.run_test(size=(width, 32)) as pilot:
        assert (app.selected_provider, app.selected_account) == ("claude", "Personal")
        await pilot.press(keys[0])
        assert (app.selected_provider, app.selected_account) == ("claude", "Work")
        assert app.query_one(AccountList).highlighted == 1
        assert "work@example.test" in screen_text(app)
        await pilot.press(keys[1])
        assert app.selected_account == "Personal"


async def test_navigation_stops_at_list_edges(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("k", "j", "j", "j")
        assert (app.selected_provider, app.selected_account) == ("codex", "Personal")


async def test_dashboard_selection_messages_update_shell_state(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        app.query_one(AccountList).highlighted = 2
        await pilot.pause()
        assert (app.selected_provider, app.selected_account) == ("codex", "Personal")


async def test_refresh_keeps_provider_and_account_after_reordering(service):
    before = deepcopy(service.current)
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "j")
        service.refreshed = Snapshot(1, groups=[
            replace(service.current.groups[1], accounts=[
                Account("Personal", email="new@example.test"),
            ]),
            service.current.groups[0],
        ])
        await pilot.press("r")
        await pilot.pause()
        assert (app.selected_provider, app.selected_account) == ("codex", "Personal")
        assert app.query_one(AccountList).highlighted == 0
        assert "new@example.test" in screen_text(app)
        assert app.snapshot is service.refreshed
        assert service.current == before


@pytest.mark.parametrize("key", ["j", "down"])
@pytest.mark.parametrize("reorder", [False, True])
async def test_rapid_refresh_preserves_cursor_before_selection_messages_arrive(
    service, key, reorder,
):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        if reorder:
            group = service.current.groups[0]
            service.refreshed = replace(service.current, groups=[
                replace(group, accounts=list(reversed(group.accounts))),
                service.current.groups[1],
            ])

        # Queue keys together: highlight/detail notifications can still be
        # pending when refresh starts handling the very next input event.
        app.post_message(Key(key, key))
        app.post_message(Key("r", "r"))
        await pilot.pause()

        assert (app.selected_provider, app.selected_account) == ("claude", "Work")
        assert app.query_one(AccountList).highlighted == (0 if reorder else 1)
        assert "work@example.test" in screen_text(app)


async def test_refresh_falls_back_to_active_account_if_selection_disappears(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j")
        service.refreshed = Snapshot(1, groups=[
            Group("codex", "Codex", accounts=[
                Account("First"), Account("Active", active=True),
            ]),
        ])
        await pilot.press("r")
        assert (app.selected_provider, app.selected_account) == ("codex", "Active")
        assert app.query_one(AccountList).highlighted == 1


async def test_refresh_without_snapshot_keeps_accounts_and_shows_feedback(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j")
        service.refresh_result = ActionResult(
            False, "refresh", error=ActionError("unavailable", "Refresh unavailable."),
            warnings=("Account status is unavailable. Refresh to retry.",),
        )
        await pilot.press("r")
        assert app.selected_account == "Work"
        assert app.snapshot is service.current
        assert "Refresh unavailable" in screen_text(app)


async def test_refresh_can_enter_and_leave_onboarding(service, empty_service):
    app = ShamblesTUI(service, motion=False)
    async with app.run_test() as pilot:
        service.refreshed = empty_service.current
        await pilot.press("r", "j", "k")
        assert app.query_one("#onboarding").display
        assert app.selected_account is None
        service.refreshed = service.current
        await pilot.press("r")
        assert app.query_one(Dashboard).display
        assert app.selected_account == "Personal"


async def test_help_can_be_dismissed_without_changing_selection(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "?")
        assert app.screen.id == "help"
        assert "Refresh" in screen_text(app)
        await pilot.press("escape")
        assert app.selected_account == "Work"
        await pilot.press("k")
        assert app.selected_account == "Personal"


async def test_help_remains_quittable(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("?", "q")
        assert not app.is_running


async def test_too_short_terminal_remains_quittable(service):
    app = ShamblesTUI(service)
    async with app.run_test(size=(80, 8)) as pilot:
        await pilot.pause()
        assert "Terminal is too small" in screen_text(app)
        await pilot.press("q")
        assert app.return_value is None
        assert not app.is_running


async def test_wide_onboarding_has_the_exact_static_readme_wordmark(empty_service, stepped_motion):
    app = ShamblesTUI(empty_service)
    async with app.run_test(size=(100, 32)):
        assert app.query_one("#onboarding").display
        assert app.query_one("#onboarding-brand").content == brand_text(BrandVariant.WIDE)
        assert "SHAMBLES" in screen_text(app)


@pytest.mark.parametrize("width", [78, 100])
async def test_wide_onboarding_keeps_controls_visible_at_minimum_height(
    empty_service, width,
):
    app = ShamblesTUI(empty_service, motion=False)
    async with app.run_test(size=(width, 16)) as pilot:
        await pilot.pause()
        assert not app.query_one("#terminal-too-small").display
        assert app.query_one("#welcome-body").display
        assert app.query_one("#welcome-copy").region.bottom <= 16
        assert "r Refresh   ? Help   q Quit" in screen_text(app)
        for row in brand_text(BrandVariant.WIDE).splitlines():
            assert row in screen_text(app)


async def test_onboarding_draws_each_border_phase_then_stays_settled(empty_service, stepped_motion):
    app = ShamblesTUI(empty_service)
    async with app.run_test(size=(100, 32)) as pilot:
        frame = app.query_one(OnboardingFrame)
        brand = app.query_one("#onboarding-brand")
        static_wordmark, static_region = brand.content, brand.region
        assert frame.phase is BoxPhase.CORNERS
        assert frame.has_class("drawing")
        assert "┌" in screen_text(app) and "─" not in screen_text(app)
        assert "│" not in screen_text(app)

        for phase in (BoxPhase.HORIZONTAL, BoxPhase.VERTICAL, BoxPhase.SETTLED):
            frame.advance_phase()
            await pilot.pause()
            assert frame.phase is phase
            assert brand.content == static_wordmark
            assert brand.region == static_region
            assert "─" in screen_text(app)
            assert ("│" in screen_text(app)) == (phase is not BoxPhase.HORIZONTAL)
        assert frame.has_class("settled")
        assert not frame.has_class("drawing")
        frame.advance_phase()
        assert frame.phase is BoxPhase.SETTLED


@pytest.mark.parametrize("key", ["enter", "escape"])
@pytest.mark.parametrize("steps", [0, 1, 2])
async def test_enter_and_escape_immediately_settle_every_phase(empty_service, stepped_motion, key, steps):
    app = ShamblesTUI(empty_service)
    async with app.run_test(size=(100, 32)) as pilot:
        frame = app.query_one(OnboardingFrame)
        for _ in range(steps):
            frame.advance_phase()
        await pilot.press(key)
        assert frame.phase is BoxPhase.SETTLED
        assert frame.has_class("settled")
        assert app.is_running


@pytest.mark.parametrize("mode", ["configuration", "NO_COLOR", "SHAMBLES_NO_MOTION"])
async def test_motion_opt_out_starts_with_a_complete_frame(empty_service, stepped_motion, monkeypatch, mode):
    if mode != "configuration":
        monkeypatch.setenv(mode, "" if mode == "NO_COLOR" else "1")
    app = ShamblesTUI(empty_service, motion=mode != "configuration")
    async with app.run_test(size=(100, 32)):
        assert app.query_one(OnboardingFrame).phase is BoxPhase.SETTLED
        assert app.query_one(OnboardingFrame).has_class("settled")


@pytest.mark.parametrize("width", [77, 48, 47, 40])
async def test_narrow_onboarding_is_static_and_fits(empty_service, stepped_motion, width):
    app = ShamblesTUI(empty_service)
    async with app.run_test(size=(width, 24)):
        assert app.query_one(OnboardingFrame).phase is BoxPhase.SETTLED
        brand = app.query_one("#onboarding-brand")
        assert brand.region.right <= width
        assert "SHAMBLES" in screen_text(app)


async def test_narrow_resize_settles_and_widening_does_not_replay(empty_service, stepped_motion):
    app = ShamblesTUI(empty_service)
    async with app.run_test(size=(100, 32)) as pilot:
        frame = app.query_one(OnboardingFrame)
        assert frame.phase is BoxPhase.CORNERS
        await pilot.resize_terminal(40, 24)
        assert frame.phase is BoxPhase.SETTLED
        await pilot.resize_terminal(100, 32)
        assert frame.phase is BoxPhase.SETTLED
        assert app.query_one("#onboarding-brand").content == brand_text(BrandVariant.WIDE)


async def test_refresh_does_not_replay_onboarding(empty_service, stepped_motion):
    app = ShamblesTUI(empty_service)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("enter", "r")
        assert app.query_one(OnboardingFrame).phase is BoxPhase.SETTLED


async def test_ascii_onboarding_fallback_is_readable(empty_service):
    app = ShamblesTUI(empty_service, unicode=False)
    async with app.run_test(size=(100, 32)):
        assert screen_text(app).isascii()
        assert "SHAMBLES" in screen_text(app)
