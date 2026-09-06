import json

import pytest

from conftest import posix_only
from helpers import (NOW, healthy_ms, make_claude_json,
                     make_live_claude_login, make_live_codex_login,
                     make_profile)
from shambles import providers, state
from shambles.errors import ConfigUnreadableError
from shambles.app.service import (ActionError, ActionPlan, ActionResult,
                                  ShamblesService)


def service(paths):
    return ShamblesService(paths=paths, providers=providers.all_providers(env={}),
                           platform="linux", clock_ms=lambda: NOW)


@pytest.fixture
def deferred_login(monkeypatch):
    """Replace only the external process; switching and disk reads stay real."""
    processes = []

    class DeferredLoginProcess:
        running = False

        def __init__(self, argv, **kwargs):
            processes.append(self)

        def start(self, *, on_line, on_exit):
            self.running = True
            self.on_line = on_line
            self.on_exit = on_exit

        def finish(self, code=0):
            self.running = False
            self.on_exit(code)

        def cancel(self):
            if self.running:
                self.finish(-15)

    monkeypatch.setattr("shambles.app.service.login.LoginProcess",
                        DeferredLoginProcess)
    return processes


def test_public_service_operations_are_present():
    expected = {
        "snapshot", "plan_switch", "switch", "save_current", "add",
        "rename", "refresh", "plan_remove", "remove", "start_login",
        "plan_eject", "eject",
    }
    assert expected <= set(dir(ShamblesService))


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


@posix_only
def test_login_rechecks_disk_instead_of_trusting_exit_zero(
        paths, fake_vendor):
    make_profile(paths, "codex", "Personal", token=False)
    fake_vendor("codex", lines=("Signed in",))
    done = []
    handle = service(paths).start_login(
        "codex", "Personal", on_line=lambda line: None,
        on_done=done.append)
    handle.wait(timeout=10)
    assert done[0].ok is False
    assert done[0].error.code == "login_not_written"


@posix_only
def test_login_output_is_sanitized(paths, fake_vendor):
    make_profile(paths, "codex", "Personal", token=False)
    fake_vendor("codex", lines=('{"access_token":"secret"}', "Signed in"))
    lines = []
    handle = service(paths).start_login(
        "codex", "Personal", on_line=lines.append,
        on_done=lambda result: None)
    handle.wait(timeout=10)
    assert "secret" not in "\n".join(lines)


@posix_only
def test_login_output_never_forwards_arbitrary_vendor_bytes(
        paths, fake_vendor):
    make_profile(paths, "codex", "Personal", token=False)
    fake_vendor("codex", lines=("opaque-secret-bytes",))
    lines = []

    handle = service(paths).start_login(
        "codex", "Personal", on_line=lines.append,
        on_done=lambda result: None)

    assert handle.wait(timeout=10)
    assert lines
    assert set(lines) == {"[vendor output hidden]"}


@posix_only
def test_login_output_exposes_only_the_normalized_sign_in_url(
        paths, fake_vendor):
    make_profile(paths, "codex", "Personal", token=False)
    url = "https://auth.openai.com/oauth/authorize?state=abc"
    fake_vendor(
        "codex",
        lines=(f"credential-before Visit {url}). credential-after",),
    )
    lines = []

    handle = service(paths).start_login(
        "codex", "Personal", on_line=lines.append,
        on_done=lambda result: None)

    assert handle.wait(timeout=10)
    assert url in lines
    assert "credential-before" not in "\n".join(lines)
    assert "credential-after" not in "\n".join(lines)


@posix_only
def test_failed_login_returns_an_error_with_a_fresh_snapshot(
        paths, fake_vendor):
    make_profile(paths, "codex", "Personal", active=True)
    fake_vendor("codex", exit_code=1, lines=("Login failed",))
    done = []

    handle = service(paths).start_login(
        "codex", "Personal", on_line=lambda line: None,
        on_done=done.append)

    assert handle.wait(timeout=10)
    assert done[0].ok is False
    assert done[0].error.code == "login_failed"
    assert done[0].snapshot is not None


@pytest.mark.parametrize("url", [
    "https://example.test/auth?access_token=credential-sentinel",
    "https://auth.openai.com/oauth/authorize?access_token=credential-sentinel",
    "https://auth.openai.com/oauth/authorize?%61ccess_token=credential-sentinel",
    "https://auth.openai.com/oauth/authorize?refreshToken=credential-sentinel",
    "https://auth.openai.com/oauth/authorize?id_token=credential-sentinel",
    "https://auth.openai.com/oauth/authorize?code=credential-sentinel",
    "https://auth.openai.com/oauth/authorize#access_token=credential-sentinel",
    "https://credential-sentinel@auth.openai.com/oauth/authorize?state=abc",
    "https://auth.openai.com/credential-sentinel?state=abc",
    "https://auth.openai.com.evil.test/oauth/authorize?state=credential-sentinel",
    "http://auth.openai.com/oauth/authorize?state=credential-sentinel",
    "https://auth.openai.com/oauth/authorize?state=abc%23credential-sentinel",
    "https://auth.openai.com/oauth/authorize?redirect_uri="
    "http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback%3Ftoken%3Dcredential-sentinel",
])
def test_login_hides_credential_bearing_or_unsupported_urls(url):
    from shambles.app.service import _safe_login_line

    assert _safe_login_line(f"Visit {url}") == "[vendor output hidden]"


@pytest.mark.parametrize("endpoint", [
    "https://auth.openai.com/authorize",
    "https://auth.openai.com/oauth/authorize",
    "https://claude.ai/oauth/authorize",
    "https://console.anthropic.com/oauth/authorize",
])
def test_login_preserves_supported_authorization_parameters(endpoint):
    from shambles.app.service import _safe_login_line

    url = (endpoint + "?response_type=code&client_id=cli&state=state-value"
           "&code_challenge=challenge-value&code_challenge_method=S256"
           "&redirect_uri=http%3A%2F%2Flocalhost%3A1455%2Fauth%2Fcallback"
           "&scope=openid+profile+email+offline_access")
    assert _safe_login_line(f"Visit {url}).") == url


@posix_only
def test_login_activates_the_requested_account_before_launch(
        paths, fake_vendor):
    make_profile(paths, "codex", "Work", email="work@example.com",
                 active=True)
    make_live_codex_login(paths, email="work@example.com",
                          exp_ms=healthy_ms())
    make_profile(paths, "codex", "Personal")
    fake_vendor("codex", exit_code=1)

    handle = service(paths).start_login(
        "codex", "Personal", on_line=lambda line: None,
        on_done=lambda result: None)

    assert handle.wait(timeout=10)
    assert state.read_active(paths, "codex") == "Personal"


@posix_only
def test_login_rejects_a_missing_target_without_launching_vendor(
        paths, fake_vendor):
    fake_vendor("codex", lines=("vendor started",))
    lines, done = [], []

    handle = service(paths).start_login(
        "codex", "Missing", on_line=lines.append,
        on_done=done.append)

    assert handle.wait(timeout=10)
    assert lines == []
    assert done[0].error.code == "profile_missing"


def test_login_does_not_accept_a_different_active_account(
        paths, monkeypatch):
    make_profile(paths, "codex", "Work", email="work@example.com",
                 active=True)
    make_live_codex_login(paths, email="work@example.com",
                          exp_ms=healthy_ms())
    make_profile(paths, "codex", "Personal", email="personal@example.com")
    processes = []

    class DeferredLoginProcess:
        running = True

        def __init__(self, argv, **kwargs):
            processes.append(self)

        def start(self, *, on_line, on_exit):
            self.on_exit = on_exit

        def cancel(self):
            pass

    monkeypatch.setattr(
        "shambles.app.service.login.LoginProcess", DeferredLoginProcess)
    app = service(paths)
    done = []
    handle = app.start_login(
        "codex", "Personal", on_line=lambda line: None,
        on_done=done.append)
    app.switch("codex", "Work")

    processes[0].on_exit(0)

    assert handle.wait(timeout=10)
    assert done[0].ok is False
    assert done[0].error.code == "login_not_written"


def test_login_launch_failure_uses_the_result_callback(paths, monkeypatch):
    make_profile(paths, "codex", "Personal", token=False, active=True)
    monkeypatch.setenv("PATH", "")
    done = []

    handle = service(paths).start_login(
        "codex", "Personal", on_line=lambda line: None,
        on_done=done.append)

    assert handle.wait(timeout=10)
    assert done[0].ok is False
    assert done[0].error.code == "login_unavailable"
    assert done[0].snapshot is not None


@pytest.mark.parametrize("action", [
    "switch", "save_current", "add", "rename", "refresh", "remove", "eject",
])
@pytest.mark.parametrize("failure", [OSError, ConfigUnreadableError, ValueError])
def test_completed_mutation_survives_snapshot_failure(paths, monkeypatch,
                                                     action, failure):
    app = service(paths)
    if action == "save_current":
        make_live_codex_login(paths)
    else:
        make_profile(paths, "codex", "Work", active=action == "eject")
    calls = {
        "switch": lambda: app.switch("codex", "Work"),
        "save_current": lambda: app.save_current("codex", "Work"),
        "add": lambda: app.add("codex", "Fresh"),
        "rename": lambda: app.rename("codex", "Work", "Job"),
        "refresh": app.refresh,
        "remove": lambda: app.remove(app.plan_remove("codex", "Work")),
        "eject": lambda: app.eject(app.plan_eject()),
    }

    def broken_snapshot():
        raise failure("snapshot-private-sentinel")

    monkeypatch.setattr(app, "snapshot", broken_snapshot)
    result = calls[action]()

    assert result.ok is True
    assert result.error is None
    assert result.snapshot is None
    assert result.warnings
    assert "snapshot-private-sentinel" not in str(result.to_dict())
    if action in {"switch", "save_current", "add"}:
        assert state.read_active(paths, "codex") == (
            "Fresh" if action == "add" else "Work")
    elif action == "rename":
        assert paths.profile_dir("codex", "Job").is_dir()
    elif action == "remove":
        assert not paths.profile_dir("codex", "Work").exists()
    elif action == "eject":
        assert state.read_active(paths, "codex") is None
        assert paths.credentials("codex", "Work").is_file()


def test_refusal_survives_snapshot_failure(paths, monkeypatch):
    app = service(paths)

    def broken_snapshot():
        raise OSError("snapshot-private-sentinel")

    monkeypatch.setattr(app, "snapshot", broken_snapshot)
    result = app.switch("codex", "Missing")

    assert result.ok is False
    assert result.error.code == "profile_missing"
    assert result.snapshot is None
    assert result.warnings
    assert "snapshot-private-sentinel" not in str(result.to_dict())


@posix_only
@pytest.mark.parametrize("exit_code", [0, 1])
def test_login_completes_when_snapshot_fails(paths, fake_vendor, monkeypatch,
                                           exit_code):
    make_profile(paths, "codex", "Personal", token=False)
    fake_vendor("codex", exit_code=exit_code)
    app, done = service(paths), []

    def broken_snapshot():
        raise OSError("snapshot-private-sentinel")

    monkeypatch.setattr(app, "snapshot", broken_snapshot)
    handle = app.start_login("codex", "Personal", on_line=lambda line: None,
                             on_done=done.append)

    assert handle.wait(timeout=1)
    assert len(done) == 1
    assert done[0].ok is False
    assert done[0].snapshot is None
    assert done[0].warnings
    assert "snapshot-private-sentinel" not in str(done[0].to_dict())


@pytest.mark.parametrize("provider_id", ["claude", "codex"])
@pytest.mark.parametrize("blob", [None, b"not-json", b"{}", b"[]",
                                   b'{"token": "private-sentinel"}'])
def test_login_rejects_missing_or_invalid_live_credentials(
        paths, deferred_login, provider_id, blob):
    make_profile(paths, provider_id, "Personal")
    done = []
    app = service(paths)
    handle = app.start_login(provider_id, "Personal", lambda line: None,
                             done.append)
    store = providers.load(provider_id, env={}).store(
        home=paths.home, platform="linux")
    if blob is None:
        store.delete()
    else:
        store.write(blob)
    saved = paths.credentials(provider_id, "Personal").read_bytes()

    deferred_login[0].finish()

    assert handle.wait(timeout=1)
    assert done[0].ok is False
    assert done[0].error.code == "login_not_written"
    assert paths.credentials(provider_id, "Personal").read_bytes() == saved
    assert "private-sentinel" not in str(done[0].to_dict())


@pytest.mark.parametrize("provider_id", ["claude", "codex"])
def test_login_rejects_a_live_identity_mismatch(paths, deferred_login,
                                              provider_id):
    make_profile(paths, provider_id, "Personal", email="personal@example.com")
    done = []
    handle = service(paths).start_login(provider_id, "Personal",
                                        lambda line: None, done.append)
    saved = paths.credentials(provider_id, "Personal").read_bytes()
    if provider_id == "claude":
        make_live_claude_login(paths)
        make_claude_json(paths, email="stranger@example.com")
    else:
        make_live_codex_login(paths, email="stranger@example.com")

    deferred_login[0].finish()

    assert handle.wait(timeout=1)
    assert done[0].ok is False
    assert done[0].error.code == "login_not_written"
    assert paths.credentials(provider_id, "Personal").read_bytes() == saved


@pytest.mark.parametrize("provider_id", ["claude", "codex"])
@pytest.mark.parametrize("unknown_expiry", [False, True])
def test_login_saves_valid_live_credentials_before_completion(
        paths, deferred_login, provider_id, unknown_expiry):
    make_profile(paths, provider_id, "Personal", token=False)
    done = []
    handle = service(paths).start_login(provider_id, "Personal",
                                        lambda line: None, done.append)
    if provider_id == "claude":
        live_path = make_live_claude_login(paths, access_token="new-credential")
        make_claude_json(paths, email="personal@example.com")
    else:
        live_path = make_live_codex_login(paths, email="personal@example.com")
    if unknown_expiry:
        data = json.loads(live_path.read_bytes())
        if provider_id == "claude":
            del data["claudeAiOauth"]["refreshTokenExpiresAt"]
        else:
            data["tokens"]["access_token"] = "opaque-access-token"
            del data["last_refresh"]
        live_path.write_text(json.dumps(data), encoding="utf-8")

    deferred_login[0].finish()

    assert handle.wait(timeout=1)
    assert done[0].ok is True
    assert paths.credentials(provider_id, "Personal").read_bytes() == live_path.read_bytes()
    if provider_id == "claude":
        sidecar = json.loads(paths.account(provider_id, "Personal").read_bytes())
        assert sidecar["oauthAccount"]["emailAddress"] == "personal@example.com"
        assert sidecar["stashed_at"] == NOW
    account = next(a for g in done[0].snapshot.groups for a in g.accounts)
    assert account.email == "personal@example.com"
    assert account.needs_login is False
    assert "new-credential" not in str(done[0].to_dict())


def test_login_success_is_preserved_when_final_snapshot_fails(
        paths, deferred_login, monkeypatch):
    make_profile(paths, "codex", "Personal", token=False)
    app, done = service(paths), []
    handle = app.start_login("codex", "Personal", lambda line: None, done.append)
    live_path = make_live_codex_login(paths)

    def broken_snapshot():
        raise ValueError("snapshot-private-sentinel")

    monkeypatch.setattr(app, "snapshot", broken_snapshot)
    deferred_login[0].finish()

    assert handle.wait(timeout=1)
    assert done[0].ok is True
    assert done[0].snapshot is None
    assert done[0].warnings
    assert paths.credentials("codex", "Personal").read_bytes() == live_path.read_bytes()


def test_login_handle_cancel_finishes_and_stops_running(paths, deferred_login):
    make_profile(paths, "codex", "Personal", token=False)
    done = []
    handle = service(paths).start_login("codex", "Personal",
                                        lambda line: None, done.append)
    assert handle.running is True
    assert handle.wait(timeout=0) is False

    handle.cancel()

    assert handle.wait(timeout=1)
    assert handle.running is False
    assert len(done) == 1
    assert done[0].error.code == "login_failed"


@pytest.mark.parametrize("failure", [OSError, ConfigUnreadableError, ValueError])
def test_login_validation_error_still_completes_safely(
        paths, deferred_login, monkeypatch, failure):
    make_profile(paths, "codex", "Personal", token=False)
    app, done = service(paths), []
    handle = app.start_login("codex", "Personal", lambda line: None, done.append)
    make_live_codex_login(paths)

    def broken_read(self):
        raise failure("credential-private-sentinel")

    monkeypatch.setattr("shambles.stores.FileStore.read", broken_read)
    deferred_login[0].finish()

    assert handle.wait(timeout=1)
    assert len(done) == 1
    assert done[0].ok is False
    assert "credential-private-sentinel" not in str(done[0].to_dict())


@posix_only
def test_login_output_callback_failure_does_not_strand_completion(
        paths, fake_vendor):
    make_profile(paths, "codex", "Personal", token=False)
    fake_vendor("codex")
    done = []

    def broken_callback(line):
        raise RuntimeError("callback-private-sentinel")

    handle = service(paths).start_login("codex", "Personal", broken_callback,
                                        done.append)
    assert handle.wait(timeout=1)
    assert len(done) == 1


def test_login_done_callback_failure_does_not_strand_completion(
        paths, deferred_login):
    make_profile(paths, "codex", "Personal", token=False)
    done = []

    def broken_callback(result):
        done.append(result)
        raise RuntimeError("callback-private-sentinel")

    handle = service(paths).start_login("codex", "Personal", lambda line: None,
                                        broken_callback)
    deferred_login[0].finish(1)
    assert handle.wait(timeout=1)
    assert len(done) == 1


def test_service_login_passes_its_home_to_the_child(paths, monkeypatch):
    from io import StringIO
    from shambles import login

    make_profile(paths, "codex", "Personal", token=False)
    done, launches = [], []
    original_process = login.LoginProcess
    monkeypatch.setattr("shambles.login.shutil.which",
                        lambda binary, **kwargs: "/fake/vendor/bin/codex")

    class Child:
        stdout = StringIO("")

        def poll(self):
            return 0

        def wait(self):
            return 0

    def popen(argv, **kwargs):
        launches.append(kwargs)
        return Child()

    monkeypatch.setattr(login, "LoginProcess", lambda argv, **kwargs:
                        original_process(argv, popen=popen, **kwargs))
    handle = service(paths).start_login("codex", "Personal", lambda line: None,
                                        done.append)

    assert handle.wait(timeout=1)
    assert launches[0]["env"]["HOME"] == str(paths.home.resolve())
    assert launches[0]["env"]["USERPROFILE"] == str(paths.home.resolve())
    assert done[0].error.code == "login_not_written"


def test_rename_summary_uses_the_saved_normalized_name(paths):
    make_profile(paths, "codex", "Work", active=True)

    result = service(paths).rename("codex", "Work", "  Job  ")

    assert state.read_active(paths, "codex") == "Job"
    assert result.summary == "Renamed to Job."


@pytest.mark.parametrize("action", ["save_current", "add"])
def test_already_managed_recovery_is_not_removal_advice(paths, action):
    if action == "save_current":
        make_profile(paths, "codex", "Work", active=True)
    make_live_codex_login(paths)

    result = getattr(service(paths), action)("codex", "Personal")

    assert result.ok is False
    assert result.error.recovery
    assert "remov" not in result.error.recovery.casefold()


@pytest.mark.parametrize("stage", ["environment", "switch", "start"])
def test_login_preparation_errors_complete_safely(paths, deferred_login,
                                                monkeypatch, stage):
    make_profile(paths, "codex", "Personal", token=False)
    done = []

    def broken(*args, **kwargs):
        raise OSError("preparation-private-sentinel")

    target = {
        "environment": "shambles.app.service.login.environment",
        "switch": "shambles.app.service.switcher.switch",
        "start": "shambles.app.service.login.LoginProcess.start",
    }[stage]
    monkeypatch.setattr(target, broken)
    handle = service(paths).start_login("codex", "Personal",
                                        lambda line: None, done.append)

    assert handle.wait(timeout=1)
    assert handle.running is False
    handle.cancel()
    assert len(done) == 1
    assert done[0].ok is False
    assert "preparation-private-sentinel" not in str(done[0].to_dict())
    if stage == "environment":
        assert state.read_active(paths, "codex") is None


@pytest.mark.parametrize("provider_id", ["claude", "codex"])
def test_login_cannot_succeed_with_an_expired_live_token(
        paths, deferred_login, provider_id):
    make_profile(paths, provider_id, "Personal", token=False)
    done = []
    handle = service(paths).start_login(provider_id, "Personal",
                                        lambda line: None, done.append)
    if provider_id == "claude":
        make_live_claude_login(paths, refresh_expires_ms=NOW - 1)
    else:
        make_live_codex_login(paths, exp_ms=NOW - 1)
    deferred_login[0].finish()

    assert handle.wait(timeout=1)
    assert done[0].error.code == "login_not_written"
    assert not paths.credentials(provider_id, "Personal").exists()


def test_login_stash_failure_preserves_the_live_login_and_completes(
        paths, deferred_login, monkeypatch):
    from shambles.stores import FileStore
    from shambles.stores.base import StoreUnavailableError

    make_profile(paths, "codex", "Personal", token=False)
    done = []
    handle = service(paths).start_login("codex", "Personal",
                                        lambda line: None, done.append)
    live = make_live_codex_login(paths)
    original = live.read_bytes()
    write = FileStore.write

    def refuse_stash(store, blob):
        if store.path == paths.credentials("codex", "Personal"):
            raise StoreUnavailableError("stash-private-sentinel")
        return write(store, blob)

    monkeypatch.setattr(FileStore, "write", refuse_stash)
    deferred_login[0].finish()

    assert handle.wait(timeout=1)
    assert done[0].ok is False
    assert done[0].error.code == "store_unavailable"
    assert "stash-private-sentinel" not in str(done[0].to_dict())
    assert live.read_bytes() == original
    assert not paths.credentials("codex", "Personal").exists()
