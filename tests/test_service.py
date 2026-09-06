from helpers import (NOW, make_claude_json, make_live_claude_login,
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
