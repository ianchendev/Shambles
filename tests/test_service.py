from helpers import (NOW, healthy_ms, make_claude_json,
                     make_live_claude_login, make_live_codex_login,
                     make_profile)
from shambles import providers, state
from shambles.app.service import (ActionError, ActionPlan, ActionResult,
                                  ShamblesService)


def service(paths):
    return ShamblesService(paths=paths, providers=providers.all_providers(),
                           platform="linux", clock_ms=lambda: NOW)


def test_action_result_has_a_stable_wire_shape():
    error = ActionError("profile_missing", "Missing.", "Choose another account.")
    result = ActionResult(ok=False, action="switch", error=error)
    assert result.to_dict() == {
        "ok": False,
        "action": "switch",
        "summary": "",
        "warnings": [],
        "snapshot": None,
        "error": {
            "code": "profile_missing",
            "message": "Missing.",
            "recovery": "Choose another account.",
        },
    }


def test_action_plan_is_read_only_data():
    plan = ActionPlan("remove", "claude", "Old", True,
                      "Remove Old?", ("The saved login will be removed.",))
    assert plan.requires_confirmation is True
    assert plan.warnings == ("The saved login will be removed.",)


def test_switch_plan_does_not_mutate_disk(paths):
    make_profile(paths, "claude", "Work", active=True)
    make_profile(paths, "claude", "Personal")
    plan = service(paths).plan_switch("claude", "Personal")
    assert plan.requires_confirmation is False
    assert state.read_active(paths, "claude") == "Work"


def test_switch_delegates_and_returns_fresh_snapshot(paths):
    make_profile(paths, "claude", "Work", active=True)
    make_profile(paths, "claude", "Personal")
    make_live_claude_login(paths)
    result = service(paths).switch("claude", "Personal")
    assert result.ok is True
    assert state.read_active(paths, "claude") == "Personal"
    account = next(a for g in result.snapshot.groups
                   for a in g.accounts if a.name == "Personal")
    assert account.active is True


def test_missing_switch_profile_returns_a_structured_failure(paths):
    result = service(paths).switch("claude", "Missing")
    assert result.ok is False
    assert result.error.code == "profile_missing"
    assert result.snapshot is not None


def test_snapshot_formats_usage_dates_for_every_client(paths):
    make_profile(paths, "claude", "Work", active=True)
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": {
            "fetchedAtMs": NOW - 10 * 60_000,
            "accountUuid": "uuid-a",
            "utilization": {"limits": [{
                "kind": "session", "percent": 42, "severity": "normal",
                "resets_at": "2026-09-06T12:00:00+10:00",
            }]},
        },
    })
    group = next(g for g in service(paths).snapshot().groups
                 if g.provider == "claude")
    window = group.accounts[0].usage[0]
    assert window.resets_label
    assert window.age_label == "10m ago"


def test_remove_requires_a_plan_and_confirmation(paths):
    make_profile(paths, "claude", "Old")
    app = service(paths)
    plan = app.plan_remove("claude", "Old")
    assert plan.requires_confirmation is True
    assert paths.profile_dir("claude", "Old").exists()
    result = app.remove(plan)
    assert result.ok is True
    assert not paths.profile_dir("claude", "Old").exists()
    assert result.snapshot is not None


def test_remove_rejects_a_different_action_plan_without_mutation(paths):
    make_profile(paths, "claude", "Old")
    wrong_plan = ActionPlan("eject", "claude", "Old", True,
                            "Eject Shambles?")

    result = service(paths).remove(wrong_plan)

    assert result.ok is False
    assert result.error.code == "invalid_plan"
    assert paths.profile_dir("claude", "Old").exists()


def test_rename_returns_the_new_profile_selected(paths):
    make_profile(paths, "claude", "Work", active=True)
    result = service(paths).rename("claude", "Work", "Job")
    assert result.ok is True
    assert state.read_active(paths, "claude") == "Job"


def test_eject_plan_lists_profiles_without_mutation(paths):
    make_profile(paths, "claude", "Work", active=True)
    plan = service(paths).plan_eject()
    assert plan.requires_confirmation is True
    assert "Work" in plan.warnings[0]
    assert state.read_active(paths, "claude") == "Work"


def test_save_current_returns_the_saved_profile_snapshot(paths):
    make_claude_json(paths, email="work@example.com")
    make_live_claude_login(paths)

    result = service(paths).save_current("claude", "Work")

    assert result.ok is True
    assert state.read_active(paths, "claude") == "Work"
    account = next(a for g in result.snapshot.groups
                   for a in g.accounts if a.name == "Work")
    assert account.active is True


def test_add_returns_the_new_empty_profile_snapshot(paths):
    make_profile(paths, "claude", "Work", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_claude_login(paths, access_token="tok-Work")

    result = service(paths).add("claude", "Fresh")

    assert result.ok is True
    assert state.read_active(paths, "claude") == "Fresh"
    account = next(a for g in result.snapshot.groups
                   for a in g.accounts if a.name == "Fresh")
    assert account.active is True
    assert account.needs_login is True


def test_refresh_restashes_rotated_credentials_before_snapshot(paths):
    make_profile(paths, "codex", "Work", email="work@example.com",
                 refresh_expires_ms=1, active=True)
    make_live_codex_login(paths, email="work@example.com",
                          exp_ms=healthy_ms())

    result = service(paths).refresh()

    assert result.ok is True
    account = next(a for g in result.snapshot.groups
                   for a in g.accounts if a.name == "Work")
    assert account.needs_login is False


def test_eject_executes_only_its_confirmation_plan(paths):
    make_profile(paths, "claude", "Work", active=True)
    make_live_claude_login(paths, access_token="tok-Work")
    app = service(paths)

    result = app.eject(app.plan_eject())

    assert result.ok is True
    assert state.read_active(paths, "claude") is None
    assert result.snapshot is not None


def test_eject_rejects_a_different_action_plan_without_mutation(paths):
    make_profile(paths, "claude", "Work", active=True)
    wrong_plan = ActionPlan("remove", "claude", "Work", True,
                            "Remove Work?")

    result = service(paths).eject(wrong_plan)

    assert result.ok is False
    assert result.error.code == "invalid_plan"
    assert state.read_active(paths, "claude") == "Work"
