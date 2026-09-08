"""The terminal shell navigates immutable state and draws onboarding once."""

from copy import deepcopy
from dataclasses import replace
import json
import threading
import time

import pytest
from textual.events import Key
from textual.widgets import Input

from shambles import settings, update_check
from shambles.app.service import ActionError, ActionPlan, ActionResult
from shambles.app.snapshot import Account, Group, Snapshot, Surface
from shambles.app.tui.application import BoxPhase, OnboardingFrame, ShamblesTUI
from shambles.app.tui.brand import BrandVariant, brand_text
from shambles.app.tui.dashboard import Dashboard
from shambles.app.tui.widgets import AccountList


class FakeLoginHandle:
    """A controllable stand-in for ``service.LoginHandle``."""

    def __init__(self):
        self.cancelled = False
        self._done = threading.Event()

    def cancel(self):
        self.cancelled = True

    def wait(self, timeout=None):
        return self._done.wait(timeout)


class SnapshotService:
    """Keep UI tests at the service boundary without reading real stores."""

    def __init__(self, snapshot):
        # The real service carries the home it reads from. Left unset here so
        # that the update-check worker -- the one thing in the app that goes
        # looking at a home rather than at a snapshot -- stays out of every
        # test that is not about it. The tests that are about it assign one.
        self.paths = None
        self.current = snapshot
        self.refreshed = snapshot
        self.refresh_result = None
        self.refresh_exception = None
        self.switch_calls = []
        self.plan_calls = []
        self.switch_plan = None
        self.switch_result = ActionResult(
            True, "switch", "Switched to Work.", snapshot=snapshot,
        )
        self.switch_thread = None
        self.switch_exception = None
        self.switch_started = threading.Event()
        self.release_switch = threading.Event()
        self.block_switch = False
        self.refresh_calls = 0

        # Lifecycle actions (save/add/rename/remove/eject) share one blocking
        # knob because the TUI runs every one of them through the same
        # mutation worker; a test only needs to prove that worker is
        # exclusive, not repeat the proof per action.
        self.mutation_started = threading.Event()
        self.release_mutation = threading.Event()
        self.block_mutation = False

        self.save_calls = []
        self.save_result = None
        self.add_calls = []
        self.add_result = None
        self.rename_calls = []
        self.rename_result = None
        self.remove_plan_calls = []
        self.remove_plan = None
        self.remove_calls = []
        self.remove_result = None
        self.eject_plan_calls = 0
        self.eject_plan = None
        self.eject_calls = []
        self.eject_result = None

        self.login_calls = []
        self.login_result = None
        self.login_handle = None
        self._login_on_line = None
        self._login_on_done = None

    def snapshot(self):
        return self.current

    def refresh(self):
        self.refresh_calls += 1
        if self.refresh_exception is not None:
            raise self.refresh_exception
        return self.refresh_result or ActionResult(
            True, "refresh", snapshot=self.refreshed
        )

    def plan_switch(self, provider, account):
        self.plan_calls.append((provider, account))
        return self.switch_plan or ActionPlan(
            "switch", provider, account, False, f"Switch to {account}?"
        )

    def switch(self, provider, account):
        self.switch_calls.append((provider, account))
        self.switch_thread = threading.get_ident()
        self.switch_started.set()
        if self.block_switch:
            if not self.release_switch.wait(5):
                raise TimeoutError("Test did not release its switch worker")
        if self.switch_exception is not None:
            raise self.switch_exception
        return self.switch_result

    def _await_mutation_release(self):
        self.mutation_started.set()
        if self.block_mutation:
            if not self.release_mutation.wait(5):
                raise TimeoutError("Test did not release its mutation worker")

    def save_current(self, provider, name):
        self._await_mutation_release()
        self.save_calls.append((provider, name))
        return self.save_result or ActionResult(
            True, "save_current", f"Saved {name}.", snapshot=self.current)

    def add(self, provider, name):
        self._await_mutation_release()
        self.add_calls.append((provider, name))
        return self.add_result or ActionResult(
            True, "add", f"Added {name}.", snapshot=self.current)

    def rename(self, provider, old_name, new_name):
        self._await_mutation_release()
        self.rename_calls.append((provider, old_name, new_name))
        return self.rename_result or ActionResult(
            True, "rename", f"Renamed to {new_name}.", snapshot=self.current)

    def plan_remove(self, provider, name):
        self.remove_plan_calls.append((provider, name))
        return self.remove_plan or ActionPlan(
            "remove", provider, name, True, f"Remove {name}?",
            ("The saved login will be removed.",))

    def remove(self, plan):
        self._await_mutation_release()
        self.remove_calls.append(plan)
        return self.remove_result or ActionResult(
            True, "remove", f"Removed {plan.account}.", snapshot=self.current)

    def plan_eject(self):
        self.eject_plan_calls += 1
        return self.eject_plan or ActionPlan(
            "eject", None, None, True, "Eject Shambles?",
            ("1 account will be ejected.",))

    def eject(self, plan):
        self._await_mutation_release()
        self.eject_calls.append(plan)
        return self.eject_result or ActionResult(
            True, "eject", "Ejected.", snapshot=self.current)

    def start_login(self, provider, account, on_line, on_done):
        self.login_calls.append((provider, account))
        self._login_on_line = on_line
        self._login_on_done = on_done
        handle = FakeLoginHandle()
        self.login_handle = handle
        return handle

    def send_login_line(self, line):
        self._login_on_line(line)

    def finish_login(self, result=None):
        outcome = result or self.login_result or ActionResult(
            True, "login", "Logged in to Work.", snapshot=self.current)
        self._login_on_done(outcome)


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


async def test_enter_switches_selected_account_and_shows_fresh_result(service):
    before = deepcopy(service.current)
    service.switch_result = ActionResult(
        True, "switch", "Switched to Work.",
        warnings=("Restart existing sessions.",),
        snapshot=Snapshot(1, groups=[
            Group("claude", "Claude", accounts=[
                Account("Work", active=True, email="updated@example.test"),
                Account("Personal"),
            ]),
            service.current.groups[1],
        ]),
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        assert app.query_one(AccountList).has_focus
        await pilot.press("j", "enter")
        await pilot.pause()

        assert service.switch_calls == [("claude", "Work")]
        assert service.plan_calls == [("claude", "Work")]
        assert service.switch_thread != threading.get_ident()
        assert app.screen.id == "result"
        assert app.screen.result is service.switch_result
        assert "Switched to Work." in screen_text(app)
        assert "Restart existing sessions." in screen_text(app)
        assert "Launch" in screen_text(app)
        assert app.snapshot is service.switch_result.snapshot

        await pilot.press("escape")
        assert (app.selected_provider, app.selected_account) == ("claude", "Work")
        assert app.query_one(AccountList).highlighted == 0
        assert "updated@example.test" in screen_text(app)
        assert service.current == before


async def test_switch_worker_rejects_duplicate_input_and_refresh_but_allows_navigation(service):
    service.block_switch = True
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        try:
            await pilot.press("j", "enter", "enter", "enter", "r")
            await pilot.pause()
            assert service.switch_started.is_set()
            assert service.switch_calls == [("claude", "Work")]
            assert service.refresh_calls == 0
            await pilot.press("j", "?")
            assert app.screen.id == "help"
            await pilot.press("escape")
            assert (app.selected_provider, app.selected_account) == ("codex", "Personal")
        finally:
            service.release_switch.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.screen.id == "result"
        await pilot.press("escape", "r")
        assert service.refresh_calls == 1
        assert (app.selected_provider, app.selected_account) == ("codex", "Personal")


async def test_rapid_switch_uses_visible_cursor_before_selection_messages_arrive(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        app.post_message(Key("j", "j"))
        app.post_message(Key("enter", "enter"))
        await pilot.pause()
        assert service.switch_calls == [("claude", "Work")]


async def test_active_account_enter_performs_no_switch(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("enter")
        assert service.switch_calls == []
        assert service.plan_calls == []
        assert app.is_running
        assert app.screen.id != "result"


@pytest.mark.parametrize("height", [8, 15])
@pytest.mark.parametrize("resize", [False, True])
async def test_undersized_terminal_cannot_begin_switch(service, monkeypatch, height, resize):
    app = ShamblesTUI(service)
    begin_calls = []
    begin_switch = app._begin_switch

    def record_begin(plan, confirmed):
        begin_calls.append((plan, confirmed))
        begin_switch(plan, confirmed)

    monkeypatch.setattr(app, "_begin_switch", record_begin)
    async with app.run_test(size=(80, 24 if resize else height)) as pilot:
        await pilot.press("j")
        if resize:
            await pilot.resize_terminal(80, height)
        await pilot.pause()
        assert app.selected_account == "Work"
        assert not app.query_one("#dashboard-body").display
        assert "Terminal is too small" in screen_text(app)

        await pilot.press("enter")
        assert begin_calls == []
        assert service.plan_calls == []
        assert service.switch_calls == []

        await pilot.press("k", "j", "?")
        assert app.selected_account == "Work"
        assert app.screen.id == "help"
        await pilot.press("escape", "q")
        assert not app.is_running
        assert app.return_value is None


async def test_switch_reenabled_when_terminal_reaches_minimum_height(service):
    app = ShamblesTUI(service)
    async with app.run_test(size=(80, 8)) as pilot:
        await pilot.press("j", "enter")
        assert service.switch_calls == []
        await pilot.resize_terminal(80, 16)
        await pilot.press("enter")
        await pilot.pause()
        assert service.switch_calls == [("claude", "Work")]
        assert app.screen.id == "result"


async def test_confirmed_switch_refuses_mutation_after_terminal_shrinks(service):
    service.switch_plan = ActionPlan(
        "switch", "claude", "Work", True, "Confirm switching Work?",
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "enter")
        assert app.screen.id == "confirm-action"
        await pilot.resize_terminal(80, 8)
        await pilot.press("enter")
        assert service.switch_calls == []
        assert not app.mutation_running


@pytest.mark.parametrize("key", ["enter", "r", "j", "?"])
async def test_switch_failure_stays_visible_until_escape(service, key):
    service.switch_result = ActionResult(
        False, "switch", warnings=("Account status is unavailable. Refresh to retry.",),
        error=ActionError(
            "store_unavailable", "The store is locked.", "Unlock it and retry.",
        ),
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "enter")
        await pilot.pause()
        assert app.screen.id == "result"
        assert "The store is locked." in screen_text(app)
        assert "Unlock it and retry." in screen_text(app)
        assert "Account status is unavailable." in screen_text(app)
        assert "Launch" not in screen_text(app)
        await pilot.press(key)
        await pilot.pause()
        assert app.screen.id == "result"
        assert app.is_running
        assert service.switch_calls == [("claude", "Work")]
        assert service.refresh_calls == 0
        await pilot.press("escape")
        assert app.snapshot is service.current
        assert app.selected_account == "Work"


async def test_switch_launch_choice_exits_with_original_provider_after_navigation(service):
    service.block_switch = True
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        try:
            await pilot.press("j", "enter", "j")
            assert app.selected_provider == "codex"
        finally:
            service.release_switch.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.return_value is None
        assert app.is_running
        await pilot.press("enter")
        assert not app.is_running
        assert app.return_value == "claude"


@pytest.mark.parametrize("ok", [True, False])
async def test_switch_result_is_quittable_without_launching(service, ok):
    service.switch_result = ActionResult(ok, "switch", "Switch result")
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "enter")
        await pilot.pause()
        await pilot.press("q")
        assert not app.is_running
        assert app.return_value is None


async def test_unexpected_switch_failure_stays_visible_without_exception_details(service):
    service.switch_exception = RuntimeError("sensitive upstream exception")
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "enter")
        await pilot.pause()
        assert app.is_running
        assert app.screen.id == "result"
        assert not app.screen.result.ok
        assert "Could not switch accounts." in screen_text(app)
        assert "sensitive upstream" not in screen_text(app)
        assert not app.mutation_running
        await pilot.press("escape", "r")
        assert service.refresh_calls == 1


async def test_switch_honors_service_confirmation_plan_and_cancel(service):
    service.switch_plan = ActionPlan(
        "switch", "claude", "Work", True, "Confirm switching Work?",
        warnings=("The running session retains its login.",),
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "enter")
        assert service.switch_calls == []
        assert "Confirm switching Work?" in screen_text(app)
        assert "The running session retains its login." in screen_text(app)
        await pilot.press("r", "j")
        assert service.refresh_calls == 0
        await pilot.press("escape")
        assert service.switch_calls == []
        assert app.selected_account == "Work"
        await pilot.press("enter", "enter")
        await pilot.pause()
        assert service.switch_calls == [("claude", "Work")]
        assert app.screen.id == "result"


async def test_switch_finishing_while_help_is_open_keeps_result_visible(service):
    service.block_switch = True
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        try:
            await pilot.press("j", "enter", "?")
            assert app.screen.id == "help"
        finally:
            service.release_switch.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.screen.id == "result"
        assert "Switched to Work." in screen_text(app)
        await pilot.press("escape")
        assert app.screen.id == "help"
        await pilot.press("escape")
        assert app.selected_account == "Work"


# --- Account action menu ----------------------------------------------------

async def test_menu_opens_for_selected_account_and_lists_its_actions(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "m")
        assert app.screen.id == "account-menu"
        assert "Actions for Work" in screen_text(app)
        assert "Save current login" in screen_text(app)
        assert "Add new profile" in screen_text(app)
        assert "Rename" in screen_text(app)
        assert "Remove" in screen_text(app)


async def test_menu_can_be_cancelled_without_any_mutation(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m")
        assert app.screen.id == "account-menu"
        await pilot.press("escape")
        assert app.screen.id != "account-menu"
        assert app.is_running
        assert service.save_calls == []
        assert service.add_calls == []
        assert service.rename_calls == []
        assert service.remove_calls == []


@pytest.mark.parametrize("height", [8, 15])
async def test_undersized_terminal_cannot_open_menu_login_or_eject(service, height):
    app = ShamblesTUI(service)
    async with app.run_test(size=(80, height)) as pilot:
        await pilot.press("m")
        assert app.screen.id != "account-menu"
        await pilot.press("l")
        assert service.login_calls == []
        await pilot.press("x")
        assert service.eject_plan_calls == 0


# --- Save --------------------------------------------------------------

async def test_save_prompts_for_a_name_and_saves_the_current_login(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "s")
        assert app.screen.id == "name-input"
        assert "Save the current claude login" in screen_text(app)
        await pilot.press(*"backup", "enter")
        await pilot.pause()
        assert service.save_calls == [("claude", "backup")]
        assert app.screen.id == "result"
        assert "Saved backup." in screen_text(app)


async def test_save_can_be_cancelled_without_calling_the_service(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "s")
        assert app.screen.id == "name-input"
        await pilot.press("escape")
        assert service.save_calls == []
        assert app.screen.id != "name-input"


async def test_save_failure_shows_the_service_error(service):
    service.save_result = ActionResult(
        False, "save_current",
        error=ActionError("profile_missing", "No live login found.",
                          "Log in first."),
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "s", "enter")
        await pilot.pause()
        assert app.screen.id == "result"
        assert "No live login found." in screen_text(app)
        assert "Log in first." in screen_text(app)


# --- Add ---------------------------------------------------------------

async def test_add_prompts_for_a_name_and_creates_an_empty_profile(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "a")
        assert app.screen.id == "name-input"
        assert "Add a new claude profile" in screen_text(app)
        await pilot.press(*"fresh", "enter")
        await pilot.pause()
        assert service.add_calls == [("claude", "fresh")]
        assert app.screen.id == "result"
        assert "Added fresh." in screen_text(app)


async def test_add_can_be_cancelled_without_calling_the_service(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "a")
        assert app.screen.id == "name-input"
        await pilot.press("escape")
        assert service.add_calls == []
        assert app.screen.id != "name-input"


# --- Rename --------------------------------------------------------------

async def test_rename_prefills_the_selected_account_name(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "m", "n")
        assert app.screen.id == "name-input"
        assert "Rename Work" in screen_text(app)
        assert app.screen.query_one(Input).value == "Work"
        await pilot.press("enter")
        await pilot.pause()
        assert service.rename_calls == [("claude", "Work", "Work")]
        assert app.screen.id == "result"
        assert "Renamed to Work." in screen_text(app)


async def test_rename_can_edit_the_prefilled_name(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "m", "n")
        for _ in "Work":
            await pilot.press("backspace")
        await pilot.press(*"Job", "enter")
        await pilot.pause()
        assert service.rename_calls == [("claude", "Work", "Job")]


async def test_rename_failure_shows_the_service_error(service):
    service.rename_result = ActionResult(
        False, "rename",
        error=ActionError("profile_missing", "That account no longer exists.",
                          "Refresh and try again."),
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "m", "n", "enter")
        await pilot.pause()
        assert app.screen.id == "result"
        assert "That account no longer exists." in screen_text(app)


# --- Remove --------------------------------------------------------------

async def test_remove_needs_explicit_confirmation(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "d")
        assert app.screen.id == "confirm-action"
        assert service.remove_calls == []
        await pilot.press("escape")
        assert service.remove_calls == []


async def test_remove_confirmed_calls_the_service_and_shows_a_result(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "m", "d")
        assert "Remove Work?" in screen_text(app)
        assert "The saved login will be removed." in screen_text(app)
        await pilot.press("enter")
        await pilot.pause()
        assert len(service.remove_calls) == 1
        assert (service.remove_calls[0].provider,
                service.remove_calls[0].account) == ("claude", "Work")
        assert app.screen.id == "result"
        assert "Removed Work." in screen_text(app)


async def test_remove_failure_shows_the_service_error(service):
    service.remove_result = ActionResult(
        False, "remove",
        error=ActionError("active_profile_protected",
                          "Switch away before removing it.",
                          "Choose a different account first."),
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "d", "enter")
        await pilot.pause()
        assert app.screen.id == "result"
        assert "Switch away before removing it." in screen_text(app)


async def test_undersized_terminal_refuses_a_confirmed_removal(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "d")
        assert app.screen.id == "confirm-action"
        await pilot.resize_terminal(80, 8)
        await pilot.press("enter")
        assert service.remove_calls == []
        assert not app.mutation_running


async def test_concurrent_mutation_blocks_new_lifecycle_actions_until_released(service):
    service.block_mutation = True
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        try:
            await pilot.press("m", "d", "enter")
            assert service.mutation_started.wait(5)
            assert app.mutation_running
            await pilot.press("m")
            assert app.screen.id != "account-menu"
            await pilot.press("l")
            assert service.login_calls == []
            await pilot.press("x")
            assert service.eject_plan_calls == 0
            await pilot.press("r")
            assert service.refresh_calls == 0
        finally:
            service.release_mutation.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app.screen.id == "result"
        assert not app.mutation_running


# --- Eject -----------------------------------------------------------------

async def test_eject_needs_explicit_confirmation(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("x")
        assert app.screen.id == "confirm-action"
        assert "Eject Shambles?" in screen_text(app)
        assert "1 account will be ejected." in screen_text(app)
        assert service.eject_calls == []
        await pilot.press("escape")
        assert service.eject_calls == []


async def test_eject_confirmed_calls_the_service_and_shows_a_result(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("x", "enter")
        await pilot.pause()
        assert len(service.eject_calls) == 1
        assert app.screen.id == "result"
        assert "Ejected." in screen_text(app)


async def test_eject_failure_shows_the_service_error(service):
    service.eject_result = ActionResult(
        False, "eject",
        error=ActionError("operation_refused", "Eject was refused.",
                          "Review the message and retry."),
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("x", "enter")
        await pilot.pause()
        assert app.screen.id == "result"
        assert "Eject was refused." in screen_text(app)


# --- Login -------------------------------------------------------------

async def test_login_starts_immediately_and_shows_progress(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "l")
        assert app.screen.id == "login-progress"
        assert service.login_calls == [("claude", "Work")]
        assert "Logging in to Work" in screen_text(app)


async def test_login_progress_shows_incoming_lines(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("l")
        service.send_login_line("Open https://example.test/authorize")
        await pilot.pause()
        assert "Open https://example.test/authorize" in screen_text(app)


async def test_login_can_be_cancelled(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.press("escape")
        assert service.login_handle.cancelled is True


async def test_login_finished_after_cancel_still_shows_a_result(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.press("escape")
        assert app.screen.id != "login-progress"
        service.finish_login(ActionResult(
            False, "login",
            error=ActionError("login_failed", "The vendor login command failed.",
                              "Review the output and retry."),
        ))
        await pilot.pause()
        assert app.screen.id == "result"
        assert not app.mutation_running


async def test_login_success_shows_result_and_refreshes_snapshot(service):
    service.login_result = ActionResult(
        True, "login", "Logged in to Personal.",
        snapshot=Snapshot(1, groups=[
            Group("claude", "Claude", accounts=[
                Account("Personal", active=True, email="updated@example.test"),
                Account("Work"),
            ]),
            service.current.groups[1],
        ]),
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("l")
        service.finish_login()
        await pilot.pause()
        assert app.screen.id == "result"
        assert "Logged in to Personal." in screen_text(app)
        assert app.snapshot is service.login_result.snapshot
        assert not app.mutation_running


async def test_login_failure_shows_result_without_a_launch_option(service):
    service.login_result = ActionResult(
        False, "login",
        error=ActionError("login_failed", "The vendor login command failed.",
                          "Review the output and retry."),
    )
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("l")
        service.finish_login()
        await pilot.pause()
        assert app.screen.id == "result"
        assert "The vendor login command failed." in screen_text(app)
        assert "Launch" not in screen_text(app)


# --- The opt-in update notice ----------------------------------------------
#
# The lookup runs in a thread because it can block: TIMEOUT_S bounds one
# socket operation, not DNS plus connect plus read, so nothing that waits on
# it may sit in front of the first frame. A notice that turns up a second late
# is fine -- the 24-hour cache means it is usually already on disk.


def seed_update_cache(paths, *, latest):
    """Leave a tag on disk as though an earlier run had looked one up.

    Stamped now, so the check reads it as today's answer and has no reason to
    fetch: these tests exercise the wiring, never a socket.
    """
    paths.ensure_store()
    (paths.library_dir / update_check.CACHE_NAME).write_text(
        json.dumps({"checked_at": time.time(), "latest": latest}),
        encoding="utf-8")


async def test_a_default_install_shows_no_notice_and_looks_nothing_up(
        service, paths):
    """Off by default, all the way through to the screen.

    The cache is written by a lookup and only by a lookup, so its absence is
    the assertion that no lookup happened.
    """
    service.paths = paths
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        app.wait_for_update_lookup()
        await pilot.pause()
        assert not app.query_one("#update-notice").display
        assert "is available" not in screen_text(app)
        assert not (paths.library_dir / update_check.CACHE_NAME).exists()


async def test_a_cached_newer_release_arrives_as_a_one_line_notice(
        service, paths):
    settings.set_update_check(paths, True)
    seed_update_cache(paths, latest="99.0.0")
    service.paths = paths
    app = ShamblesTUI(service)
    async with app.run_test(size=(140, 32)) as pilot:
        app.wait_for_update_lookup()
        await pilot.pause()
        assert app.query_one("#update-notice").display
        assert app.query_one("#update-notice").size.height == 1
        assert "Shambles 99.0.0 is available" in screen_text(app)
        assert "npm i -g shambles@latest" in screen_text(app)
        assert app.query_one(Dashboard).display


async def test_the_notice_can_be_dismissed(service, paths):
    """It is one line of news, not a decision to make. Whoever has read it
    gets their row back."""
    settings.set_update_check(paths, True)
    seed_update_cache(paths, latest="99.0.0")
    service.paths = paths
    app = ShamblesTUI(service)
    async with app.run_test(size=(140, 32)) as pilot:
        app.wait_for_update_lookup()
        await pilot.pause()
        assert "99.0.0" in screen_text(app)

        await pilot.press("u")

        assert not app.query_one("#update-notice").display
        assert "99.0.0" not in screen_text(app)
        assert app.selected_account == "Personal"


async def test_a_cached_tag_that_is_not_newer_says_nothing(service, paths):
    settings.set_update_check(paths, True)
    seed_update_cache(paths, latest="0.0.1")
    service.paths = paths
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        app.wait_for_update_lookup()
        await pilot.pause()
        assert not app.query_one("#update-notice").display


async def test_startup_never_waits_for_the_lookup(service, paths, monkeypatch):
    """The point of the thread.

    A blocking lookup in front of the first frame would make a captive portal
    look like a hung program, so the interface has to be up and taking keys
    while the check is still out.
    """
    settings.set_update_check(paths, True)
    service.paths = paths
    started, release, ran_on = threading.Event(), threading.Event(), []

    def slow_lookup(_paths, **_kwargs):
        ran_on.append(threading.get_ident())
        started.set()
        release.wait(5)
        return update_check.UpdateStatus(True, "2.0.0", None, False, None)

    monkeypatch.setattr(update_check, "check_for_update", slow_lookup)
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        try:
            assert started.wait(5)
            assert ran_on[0] != threading.get_ident()
            await pilot.press("j")
            assert app.selected_account == "Work"
            assert app.is_running
        finally:
            release.set()
        app.wait_for_update_lookup()


async def test_the_lookup_cannot_hold_the_shell_after_a_quit(
        service, paths, monkeypatch):
    """Quitting has to give the terminal back, lookup or no lookup.

    Nothing can interrupt a thread parked in ``getaddrinfo`` -- ``TIMEOUT_S``
    bounds a socket operation, not name resolution, so a black-holed DNS
    server holds it for the resolver's own budget. The only way quitting stays
    instant is for the interpreter to be free to exit while it is still
    parked, which is what a daemon thread means and what a pooled worker
    thread is not: ``asyncio.run`` waits on its default executor on the way
    out.
    """
    settings.set_update_check(paths, True)
    service.paths = paths
    release, daemonic = threading.Event(), []

    def slow_lookup(_paths, **_kwargs):
        daemonic.append(threading.current_thread().daemon)
        release.wait(5)
        return update_check.UpdateStatus(True, "2.0.0", None, False, None)

    monkeypatch.setattr(update_check, "check_for_update", slow_lookup)
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        try:
            await pilot.pause()
            assert daemonic == [True]
        finally:
            release.set()
        app.wait_for_update_lookup()


async def test_a_default_install_starts_no_lookup_at_all(service, paths,
                                                         monkeypatch):
    """Off means the check is not consulted, not that it is asked and says no.

    The lookup declines on its own too, but a thread spawned on every launch
    to be told "no" is a thread that can still be in flight at quit.
    """
    service.paths = paths
    asked = []
    monkeypatch.setattr(update_check, "check_for_update",
                        lambda *args, **kwargs: asked.append(1))
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        app.wait_for_update_lookup()
        await pilot.pause()
        assert asked == []


async def test_a_lookup_that_raises_does_not_take_the_interface_down(
        service, paths, monkeypatch):
    """A version check is worth nobody's session. Whatever comes back out of
    that thread, the app stays up and says nothing about it."""
    settings.set_update_check(paths, True)
    service.paths = paths

    def boom(_paths, **_kwargs):
        raise RuntimeError("sensitive upstream exception")

    monkeypatch.setattr(update_check, "check_for_update", boom)
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        app.wait_for_update_lookup()
        await pilot.pause()
        assert app.is_running
        assert not app.query_one("#update-notice").display
        assert "sensitive upstream" not in screen_text(app)
        await pilot.press("j")
        assert app.selected_account == "Work"


async def test_the_lookup_does_not_block_a_switch_or_count_as_a_mutation(
        service, paths, monkeypatch):
    """It touches nothing but a cache file, so it must not reserve the slot
    that stops two credential writes overlapping."""
    settings.set_update_check(paths, True)
    service.paths = paths
    release = threading.Event()

    def slow_lookup(_paths, **_kwargs):
        release.wait(5)
        return update_check.UpdateStatus(True, "2.0.0", None, False, None)

    monkeypatch.setattr(update_check, "check_for_update", slow_lookup)
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        try:
            assert not app.mutation_running
            await pilot.press("j", "enter")
            await pilot.pause()
            assert service.switch_calls == [("claude", "Work")]
        finally:
            release.set()
        app.wait_for_update_lookup()
        await app.workers.wait_for_complete()


async def test_help_says_how_to_hide_the_notice_and_what_the_check_does(
        service):
    """The only place a key is ever advertised in this app, and the only
    place the interface gets to correct itself about the network."""
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("?")
        assert "Hide the update notice" in screen_text(app)
        assert "No telemetry" in screen_text(app)
        assert "No telemetry or update checks." not in screen_text(app)


async def test_help_lists_lifecycle_shortcuts(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("?")
        assert "Account actions" in screen_text(app)
        assert "Log in to selected account" in screen_text(app)
        assert "Eject Shambles" in screen_text(app)


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


async def test_refresh_reports_a_raised_store_error_instead_of_crashing(service):
    """``refresh()`` can raise ``StoreUnavailableError`` out of
    ``switcher.restash_active`` -- unlike every other mutation path, this one
    runs synchronously on the UI thread rather than in a guarded worker, so
    an uncaught raise here would crash the whole app instead of reporting
    through the normal result UI."""
    from shambles.stores.base import StoreUnavailableError

    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j")
        service.refresh_exception = StoreUnavailableError("store locked")
        await pilot.press("r")
        assert app.selected_account == "Work"
        assert app.snapshot is service.current
        assert "Could not refresh local state" in screen_text(app)


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
        assert "Enter" in screen_text(app)
        assert "Switch selected account" in screen_text(app)
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
