# Shambles Application Service Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create one typed, tested application-service boundary for snapshots, account lifecycle operations, confirmations, and stable failures.

**Architecture:** A stateless `ShamblesService` receives injected paths, providers, platform, and time. It delegates all credential work to the existing switcher/login/eject modules, then rereads the immutable snapshot from disk. Presentation clients consume structured plans and results and never parse exception text to decide recovery.

**Tech Stack:** Python 3.10+, dataclasses, existing Shambles core, pytest

**Spec:** `docs/superpowers/specs/2026-09-06-terminal-ui-design.md`

## Global Constraints

- Never read or write the real user home in automated tests.
- Never include credential bytes in results, errors, logs, or snapshots.
- Keep provider and platform behavior delegated to existing adapters and stores.
- Preserve the existing switch ordering in `shambles/switcher.py`.
- No networking imports in the `shambles` package.
- Every mutating result is followed by a fresh disk snapshot when readable.
- Python 3.10 remains the minimum runtime.

---

### Task 1: Structured service types

**Files:**
- Create: `shambles/app/service.py`
- Create: `tests/test_service.py`

**Interfaces:**
- Consumes: `shambles.app.snapshot.Snapshot`
- Produces: `ActionError`, `ActionPlan`, `ActionResult`, and `ShamblesService`

- [ ] **Step 1: Write failing type tests**

```python
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
```

- [ ] **Step 2: Run the tests and confirm the missing module failure**

Run: `.venv/bin/python -m pytest tests/test_service.py -v`
Expected: FAIL with `ModuleNotFoundError: shambles.app.service`.

- [ ] **Step 3: Implement immutable result types**

```python
@dataclass(frozen=True)
class ActionError:
    code: str
    message: str
    recovery: str = ""

@dataclass(frozen=True)
class ActionPlan:
    action: str
    provider: str | None
    account: str | None
    requires_confirmation: bool
    prompt: str
    warnings: tuple[str, ...] = ()

@dataclass(frozen=True)
class ActionResult:
    ok: bool
    action: str
    summary: str = ""
    warnings: tuple[str, ...] = ()
    snapshot: Snapshot | None = None
    error: ActionError | None = None

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "action": self.action,
            "summary": self.summary,
            "warnings": list(self.warnings),
            "snapshot": (snapshot_mod.to_dict(self.snapshot)
                         if self.snapshot else None),
            "error": (asdict(self.error) if self.error else None),
        }
```

- [ ] **Step 4: Run the focused tests**

Run: `.venv/bin/python -m pytest tests/test_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shambles/app/service.py tests/test_service.py
git commit -m "feat: add structured application service types"
```

### Task 2: Snapshot and switch service operations

**Files:**
- Modify: `shambles/app/service.py`
- Modify: `tests/test_service.py`
- Modify: `shambles/app/snapshot.py`
- Modify: `tests/test_snapshot.py`

**Interfaces:**
- Consumes: `snapshot.build(...)`, `switcher.switch(...)`
- Produces: `ShamblesService.snapshot()`, `plan_switch()`, and `switch()`

- [ ] **Step 1: Write failing service tests**

```python
def service(paths):
    return ShamblesService(paths=paths, providers=providers.all_providers(),
                           platform="linux", clock_ms=lambda: NOW)

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
```

- [ ] **Step 2: Verify the new methods are missing**

Run: `.venv/bin/python -m pytest tests/test_service.py -k 'switch' -v`
Expected: FAIL with missing `plan_switch` or `switch`.

- [ ] **Step 3: Implement the service shell and switch delegation**

```python
class ShamblesService:
    def __init__(self, *, paths, providers, platform, clock_ms=switcher.now_ms):
        self.paths = paths
        self.providers = tuple(providers)
        self.platform = platform
        self.clock_ms = clock_ms

    def _provider(self, provider_id):
        try:
            return next(p for p in self.providers if p.id == provider_id)
        except StopIteration:
            raise KeyError(provider_id)

    def snapshot(self):
        return snapshot_mod.build(paths=self.paths, providers=self.providers,
                                  platform=self.platform,
                                  now_ms=self.clock_ms())

    def plan_switch(self, provider_id, account):
        return ActionPlan("switch", provider_id, account, False,
                          f"Switch to {account}?")

    def switch(self, provider_id, account):
        try:
            switcher.switch(self.paths, self._provider(provider_id), account,
                            platform=self.platform)
            return ActionResult(True, "switch",
                                f"Switched to {account}.",
                                snapshot=self.snapshot())
        except ShamblesError as exc:
            return self._failure("switch", exc)
```

Extend `snapshot.Window` with `resets_label: str | None` and
`age_label: str | None`. Populate them in `snapshot._windows()` with
`bar.resets_label()` and `profile.usage.age_label(now_ms)`, and serialize
both fields in `to_dict()`. These are presentation labels computed in the
tested Python contract; TUI and native clients perform no date arithmetic.

Implement `_failure()` with an explicit exception-to-code mapping. Unknown
`ShamblesError` subclasses use `operation_refused`; never include `repr`
or exception attributes in the result.

```python
ERROR_CODES = {
    ProfileNotFoundError: (
        "profile_missing", "Choose an account that still exists."),
    AlreadyManagedError: (
        "active_profile_protected", "Switch away before removing it."),
    ConfigUnreadableError: (
        "companion_unreadable", "Repair the vendor configuration and retry."),
    StoreUnavailableError: (
        "store_unavailable", "Unlock or restore the credential store."),
}

def _failure(self, action, exc):
    code, recovery = ERROR_CODES.get(
        type(exc), ("operation_refused", "Review the message and retry."))
    return ActionResult(
        False, action,
        snapshot=self.snapshot(),
        error=ActionError(code, str(exc), recovery),
    )
```

- [ ] **Step 4: Test success, refusal, and provider errors**

Run: `.venv/bin/python -m pytest tests/test_service.py tests/test_snapshot.py -v`
Expected: PASS, including an assertion that a missing profile returns
`ok=False` and code `profile_missing`.

- [ ] **Step 5: Run the original switch contract**

Run: `.venv/bin/python -m pytest tests/test_switch.py tests/test_snapshot.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add shambles/app/service.py tests/test_service.py
git commit -m "feat: route account switching through application service"
```

### Task 3: Account lifecycle service operations

**Files:**
- Modify: `shambles/app/service.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Consumes: existing `switcher.save_current_account`,
  `add_empty_account`, `rename_profile`, `remove_profile`,
  `restash_active`, `eject.survey`, and `eject.run`
- Produces: matching plan and execute methods on `ShamblesService`

- [ ] **Step 1: Add failing lifecycle tests**

```python
def test_remove_requires_a_plan_and_confirmation(paths):
    make_profile(paths, "claude", "Old")
    app = service(paths)
    plan = app.plan_remove("claude", "Old")
    assert plan.requires_confirmation is True
    assert paths.profile_dir("claude", "Old").exists()
    result = app.remove(plan)
    assert result.ok is True
    assert not paths.profile_dir("claude", "Old").exists()

def test_rename_returns_the_new_profile_selected(paths):
    make_profile(paths, "claude", "Work", active=True)
    result = service(paths).rename("claude", "Work", "Job")
    assert result.ok is True
    assert state.read_active(paths, "claude") == "Job"

def test_eject_plan_lists_profiles_without_mutation(paths):
    make_profile(paths, "claude", "Work", active=True)
    plan = service(paths).plan_eject()
    assert plan.requires_confirmation is True
    assert state.read_active(paths, "claude") == "Work"
```

- [ ] **Step 2: Confirm lifecycle methods are missing**

Run: `.venv/bin/python -m pytest tests/test_service.py -k 'remove or rename or eject' -v`
Expected: FAIL on missing methods.

- [ ] **Step 3: Implement lifecycle delegation**

Add `save_current(provider_id, name)`, `add(provider_id, name)`,
`rename(provider_id, old_name, new_name)`, `refresh()`,
`plan_remove(provider_id, name)`, `remove(plan)`, `plan_eject()`, and
`eject(plan)`. Validate that execution plans have the expected action before
using their fields:

```python
def remove(self, plan):
    if plan.action != "remove" or not plan.provider or not plan.account:
        return ActionResult(False, "remove",
            error=ActionError("invalid_plan", "The removal plan is invalid."))
    try:
        switcher.remove_profile(
            self.paths, self._provider(plan.provider), plan.account,
            platform=self.platform)
        return ActionResult(True, "remove", f"Removed {plan.account}.",
                            snapshot=self.snapshot())
    except ShamblesError as exc:
        return self._failure("remove", exc)

def rename(self, provider_id, old_name, new_name):
    try:
        switcher.rename_profile(
            self.paths, self._provider(provider_id), old_name, new_name)
        return ActionResult(True, "rename", f"Renamed to {new_name}.",
                            snapshot=self.snapshot())
    except ShamblesError as exc:
        return self._failure("rename", exc)

def refresh(self):
    for provider in self.providers:
        switcher.restash_active(
            self.paths, provider, platform=self.platform)
    return ActionResult(True, "refresh", snapshot=self.snapshot())
```

Implement Save and Add with the same delegation pattern. `plan_eject()` wraps
`eject.survey()` in an `ActionPlan` whose warnings contain
`eject.summary()`; confirmed execution calls `eject.run()`.

- [ ] **Step 4: Run lifecycle and original core tests**

Run: `.venv/bin/python -m pytest tests/test_service.py tests/test_switch.py tests/test_eject.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shambles/app/service.py tests/test_service.py
git commit -m "feat: expose account lifecycle service"
```

### Task 4: Asynchronous login handle

**Files:**
- Modify: `shambles/app/service.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Consumes: `login.command()`, `login.LoginProcess`, service snapshots
- Produces: `LoginHandle.cancel()` and
  `ShamblesService.start_login(provider_id, account, on_line, on_done)`

- [ ] **Step 1: Write failing login tests with the existing fake vendor**

```python
def test_login_rechecks_disk_instead_of_trusting_exit_zero(
        paths, fake_vendor):
    fake_vendor("codex", lines=("Signed in",))
    done = []
    handle = service(paths).start_login(
        "codex", "Personal", on_line=lambda line: None,
        on_done=done.append)
    handle.wait(timeout=10)
    assert done[0].ok is False
    assert done[0].error.code == "login_not_written"

def test_login_output_is_sanitized(paths, fake_vendor):
    fake_vendor("codex", lines=('{"access_token":"secret"}', "Signed in"))
    lines = []
    handle = service(paths).start_login(
        "codex", "Personal", on_line=lines.append,
        on_done=lambda result: None)
    handle.wait(timeout=10)
    assert "secret" not in "\n".join(lines)
```

- [ ] **Step 2: Confirm login service methods are missing**

Run: `.venv/bin/python -m pytest tests/test_service.py -k login -v`
Expected: FAIL on missing `start_login`.

- [ ] **Step 3: Implement the handle and completion validation**

```python
class LoginHandle:
    def __init__(self, process, completed):
        self._process = process
        self._completed = completed
    def cancel(self):
        self._process.cancel()
    def wait(self, timeout=None):
        return self._completed.wait(timeout)
    @property
    def running(self):
        return self._process.running

def _safe_login_line(line):
    lowered = line.casefold()
    if any(word in lowered for word in
           ("access_token", "refresh_token", "id_token")):
        return "[credential output hidden]"
    return line
```

Create a `threading.Event` for each handle and set it after `on_done` has
received its result. On exit zero, call `snapshot()` and find the requested
account. Return success only if it exists and `needs_login` is false. On
nonzero exit return `login_failed`; on missing credential return
`login_not_written`.

- [ ] **Step 4: Run login and network-boundary tests**

Run: `.venv/bin/python -m pytest tests/test_service.py tests/test_login.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shambles/app/service.py tests/test_service.py
git commit -m "feat: add validated login service"
```

### Task 5: Migrate the script CLI to the service

**Files:**
- Modify: `shambles/app/cli.py`
- Modify: `tests/test_snapshot.py`
- Modify: `tests/test_service.py`

**Interfaces:**
- Consumes: `ShamblesService.snapshot()`, `switch()`,
  `ActionResult.to_dict()`
- Produces: unchanged `list` and `switch` command behavior

- [ ] **Step 1: Add a delegation regression test**

```python
def test_cli_switch_calls_application_service(paths, monkeypatch):
    called = []
    monkeypatch.setattr(
        "shambles.app.cli.ShamblesService.switch",
        lambda self, provider, account:
            called.append((provider, account)) or ActionResult(True, "switch"))
    assert cli.main(["--home", str(paths.home), "switch",
                     "claude", "Work"]) == 0
    assert called == [("claude", "Work")]
```

- [ ] **Step 2: Confirm the test fails because CLI calls the switcher**

Run: `.venv/bin/python -m pytest tests/test_snapshot.py::test_cli_switch_calls_application_service -v`
Expected: FAIL with an empty `called` list.

- [ ] **Step 3: Replace direct CLI orchestration**

```python
def _service(args):
    return ShamblesService(paths=_paths(args),
                           providers=registry.all_providers(),
                           platform=sys.platform)

def cmd_switch(args):
    result = _service(args).switch(args.provider, args.account)
    if args.json:
        json.dump(result.to_dict(), sys.stdout)
        sys.stdout.write("\n")
    elif result.ok:
        print(result.summary)
    else:
        sys.stderr.write(result.error.message.rstrip() + "\n")
    return EXIT_OK if result.ok else EXIT_FAILED
```

Use the service snapshot in `cmd_list`. Preserve the existing JSON snapshot
shape for `list --json` and existing exit codes.

- [ ] **Step 4: Run CLI and contract tests**

Run: `.venv/bin/python -m pytest tests/test_snapshot.py tests/test_service.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full Python suite**

Run: `.venv/bin/python -m pytest`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add shambles/app/cli.py tests/test_snapshot.py tests/test_service.py
git commit -m "refactor: route CLI through application service"
```

### Task 6: Document the service contract

**Files:**
- Modify: `TECH_SPEC.md`
- Modify: `docs/design-decisions.md`
- Test: `tests/test_service.py`

**Interfaces:**
- Consumes: final service types and methods
- Produces: authoritative service-boundary documentation

- [ ] **Step 1: Add a contract completeness test**

```python
def test_public_service_operations_are_present():
    expected = {
        "snapshot", "plan_switch", "switch", "save_current", "add",
        "rename", "refresh", "plan_remove", "remove", "start_login",
        "plan_eject", "eject",
    }
    assert expected <= set(dir(ShamblesService))
```

- [ ] **Step 2: Run the completeness test**

Run: `.venv/bin/python -m pytest tests/test_service.py::test_public_service_operations_are_present -v`
Expected: PASS.

- [ ] **Step 3: Document ownership and invariants**

Add a service-boundary section to `TECH_SPEC.md` and a design decision to
`docs/design-decisions.md` stating that interfaces may render results but
must not call `switcher`, `login`, or `eject` directly.

- [ ] **Step 4: Verify documentation and suite**

Run: `git diff --check && .venv/bin/python -m pytest`
Expected: no diff errors and all tests pass.

- [ ] **Step 5: Commit**

```bash
git add TECH_SPEC.md docs/design-decisions.md tests/test_service.py
git commit -m "docs: define application service boundary"
```
