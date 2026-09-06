from shambles.app.service import ActionError, ActionPlan, ActionResult


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
