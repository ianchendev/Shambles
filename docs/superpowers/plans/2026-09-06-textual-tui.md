# Shambles Textual TUI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the responsive, keyboard-driven Shambles terminal interface, including lifecycle workflows, adaptive branding, safe error states, and optional same-terminal vendor launch.

**Architecture:** A Textual `App` renders immutable snapshots supplied by `ShamblesService`. Focus and overlays are TUI-only state; all mutations run through exclusive workers and end by rendering the service's fresh snapshot. The app returns a launch request only after Textual has restored the terminal, and the entrypoint then replaces the process with the vendor CLI.

**Tech Stack:** Python 3.10+, Textual 8.2.x, Rich, pytest, pytest-asyncio, pytest-textual-snapshot

**Spec:** `docs/superpowers/specs/2026-09-06-terminal-ui-design.md`

## Global Constraints

- Complete `docs/superpowers/plans/2026-09-06-application-service.md` first.
- Use `ShamblesService`; TUI modules must not import `switcher`, `login`, or `eject`.
- Terracotta is `#e07a5f`, gold is `#d9a441`, and the dark brand ground is `#0b1020`.
- Wide layout starts at 78 cells; medium at 48; below 48 uses compact layout.
- Never display, log, copy, or include credentials in snapshots.
- Respect `NO_COLOR`; retain a strict-ASCII branding fallback.
- Reuse the README's approved ANSI wordmark for wide onboarding. Animate only
  its surrounding frame once (corners, horizontal borders, vertical borders,
  then settle); never fade, move, or loop the wordmark itself. `Enter` and
  `Esc` skip it. Disable nonessential motion for `NO_COLOR`,
  `SHAMBLES_NO_MOTION=1`, `--no-motion`, and narrow terminals.
- Keep script commands usable without constructing a Textual app.

---

### Task 1: Add and isolate Textual dependencies

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/test_packaging.py`

**Interfaces:**
- Consumes: Python package metadata
- Produces: runtime `textual>=8.2,<9`; dev `pytest-asyncio` and
  `pytest-textual-snapshot`

- [ ] **Step 1: Add a failing metadata test**

```python
def test_tui_dependencies_are_declared():
    data = tomllib.loads(Path("pyproject.toml").read_text())
    assert "textual>=8.2,<9" in data["project"]["dependencies"]
    dev = data["project"]["optional-dependencies"]["dev"]
    assert "pytest-asyncio>=0.24" in dev
    assert "pytest-textual-snapshot>=1.1" in dev
```

- [ ] **Step 2: Confirm the metadata test fails**

Run: `.venv/bin/python -m pytest tests/test_packaging.py::test_tui_dependencies_are_declared -v`
Expected: FAIL because dependencies are absent.

- [ ] **Step 3: Update package metadata**

```toml
dependencies = ["textual>=8.2,<9"]

[project.optional-dependencies]
dev = [
  "pytest>=8",
  "pytest-asyncio>=0.24",
  "pytest-textual-snapshot>=1.1",
]

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

Retain the existing test paths, file patterns, and quiet option in the same
`tool.pytest.ini_options` table. Replace
`test_declares_no_runtime_dependencies` with an assertion that Textual is the
only direct runtime dependency; Tkinter remains absent because it is not a
PyPI package.

- [ ] **Step 4: Install and verify metadata**

Run: `.venv/bin/pip install -e ".[dev]" && .venv/bin/python -m pytest tests/test_packaging.py -v`
Expected: installation succeeds and packaging tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tests/test_packaging.py
git commit -m "build: add Textual TUI dependencies"
```

### Task 2: Terminal-native brand variants

**Files:**
- Create: `shambles/app/tui/__init__.py`
- Create: `shambles/app/tui/brand.py`
- Create: `tests/tui/test_brand.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: terminal width, Unicode capability, `NO_COLOR`
- Produces: `BrandVariant`, `variant_for(width, unicode=True)`, and
  `brand_text(variant, unicode=True)`

- [ ] **Step 1: Write breakpoint and fallback tests**

```python
@pytest.mark.parametrize(("width", "expected"), [
    (100, BrandVariant.WIDE),
    (78, BrandVariant.WIDE),
    (77, BrandVariant.MEDIUM),
    (48, BrandVariant.MEDIUM),
    (47, BrandVariant.COMPACT),
])
def test_brand_variant_uses_cell_breakpoints(width, expected):
    assert variant_for(width) is expected

def test_ascii_brand_has_no_non_ascii_character():
    assert brand_text(BrandVariant.COMPACT, unicode=False).isascii()
    assert brand_text(BrandVariant.COMPACT, unicode=False) == ">_ <-> SHAMBLES"
```

- [ ] **Step 2: Confirm the brand module is missing**

Run: `.venv/bin/python -m pytest tests/tui/test_brand.py -v`
Expected: FAIL with missing `shambles.app.tui.brand`.

- [ ] **Step 3: Implement fixed compositions**

```python
class BrandVariant(Enum):
    WIDE = "wide"
    MEDIUM = "medium"
    COMPACT = "compact"

def variant_for(width: int) -> BrandVariant:
    if width >= 78:
        return BrandVariant.WIDE
    if width >= 48:
        return BrandVariant.MEDIUM
    return BrandVariant.COMPACT

def brand_text(variant: BrandVariant, *, unicode: bool = True) -> str:
    if variant is BrandVariant.COMPACT:
        return ">_ ⇄ SHAMBLES" if unicode else ">_ <-> SHAMBLES"
    return UNICODE_ART[variant] if unicode else ASCII_ART[variant]
```

Store the approved wide art and its medium composition as tuple constants so
their line widths can be asserted. Add tests that no row exceeds its
breakpoint width.

The wide art must preserve the approved README ANSI wordmark; the onboarding
animation draws only a separately composed frame around it. Do not substitute
the compact `>_ ⇄ SHAMBLES` mark for the wide wordmark.

- [ ] **Step 4: Include TUI styles as package data**

```toml
"shambles.app.tui" = ["*.tcss"]
```

- [ ] **Step 5: Run focused tests**

Run: `.venv/bin/python -m pytest tests/tui/test_brand.py tests/test_packaging.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add shambles/app/tui pyproject.toml tests/tui tests/test_packaging.py
git commit -m "feat: add responsive terminal branding"
```

### Task 3: Dashboard widgets and responsive layouts

**Files:**
- Create: `shambles/app/tui/widgets.py`
- Create: `shambles/app/tui/dashboard.py`
- Create: `shambles/app/tui/theme.tcss`
- Create: `tests/tui/test_dashboard.py`

**Interfaces:**
- Consumes: `snapshot.Snapshot`, `Group`, `Account`, `Window`
- Produces: `AccountList`, `AccountDetails`, `Dashboard`, and
  `Dashboard.AccountSelected`

- [ ] **Step 1: Write headless responsive tests**

```python
async def test_wide_dashboard_has_list_and_detail_panes(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)):
        assert app.query_one(Dashboard).has_class("wide")
        assert app.query_one("#account-list").display
        assert app.query_one("#account-details").display

async def test_medium_dashboard_expands_selected_row(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(60, 32)):
        assert app.query_one(Dashboard).has_class("medium")
        assert app.query_one("#inline-details").display

async def test_narrow_dashboard_hides_decoration(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(40, 24)):
        assert app.query_one(Dashboard).has_class("compact")
        assert not app.query_one("#surface-pills").display

async def test_too_short_terminal_shows_a_safe_size_message(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(80, 8)):
        assert app.query_one("#terminal-too-small").display
```

- [ ] **Step 2: Confirm dashboard types are missing**

Run: `.venv/bin/python -m pytest tests/tui/test_dashboard.py -v`
Expected: FAIL on missing dashboard imports.

- [ ] **Step 3: Implement focused widgets**

```python
class AccountList(OptionList):
    class Selected(Message):
        def __init__(self, provider: str, account: str):
            self.provider = provider
            self.account = account
            super().__init__()

class AccountDetails(Static):
    def show_account(self, group: Group, account: Account) -> None:
        self.update(render_account_details(group, account))
```

Use Rich `Text` and `Table.grid()` to render usage and states. Render
`resets_at_ms=None` as unavailable. Never perform date arithmetic in widgets;
extend the snapshot/service first if formatted reset copy is needed.

- [ ] **Step 4: Apply layout class on resize**

```python
def on_resize(self, event: events.Resize) -> None:
    variant = variant_for(event.size.width)
    self.set_class(variant is BrandVariant.WIDE, "wide")
    self.set_class(variant is BrandVariant.MEDIUM, "medium")
    self.set_class(variant is BrandVariant.COMPACT, "compact")
```

Define the pane geometry and palette in `theme.tcss`. Do not duplicate
breakpoint numbers in TCSS.

- [ ] **Step 5: Run dashboard tests**

Run: `.venv/bin/python -m pytest tests/tui/test_dashboard.py tests/tui/test_brand.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add shambles/app/tui tests/tui
git commit -m "feat: add responsive TUI dashboard"
```

### Task 4: Application shell, navigation, and refresh

**Files:**
- Create: `shambles/app/tui/application.py`
- Create: `tests/tui/test_application.py`

**Interfaces:**
- Consumes: `ShamblesService.snapshot()`, `refresh()`, dashboard messages
- Produces: `ShamblesTUI(App[LaunchRequest | None])` and `run_tui(service)`

- [ ] **Step 1: Write navigation and refresh tests**

```python
async def test_j_and_k_move_account_selection(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        first = app.selected_account
        await pilot.press("j")
        assert app.selected_account != first
        await pilot.press("k")
        assert app.selected_account == first

async def test_refresh_preserves_selection(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "r")
        await pilot.pause()
        assert app.selected_account == "Work"

async def test_first_run_shows_onboarding(service_without_accounts):
    app = ShamblesTUI(service_without_accounts)
    async with app.run_test(size=(100, 32)):
        assert app.query_one("#onboarding").display
        assert "SHAMBLES" in app.query_one("#onboarding-brand").render().plain

async def test_onboarding_box_loop_can_be_skipped(service_without_accounts):
    app = ShamblesTUI(service_without_accounts, motion=True)
    async with app.run_test(size=(100, 32)) as pilot:
        assert app.query_one("#onboarding-frame").has_class("drawing")
        await pilot.press("enter")
        assert app.query_one("#onboarding-frame").has_class("settled")

async def test_onboarding_motion_is_disabled_by_configuration(service_without_accounts):
    app = ShamblesTUI(service_without_accounts, motion=False)
    async with app.run_test(size=(100, 32)):
        assert app.query_one("#onboarding-frame").has_class("settled")
```

- [ ] **Step 2: Confirm the application class is missing**

Run: `.venv/bin/python -m pytest tests/tui/test_application.py -v`
Expected: FAIL on missing `ShamblesTUI`.

- [ ] **Step 3: Implement bindings and immutable refresh**

```python
class ShamblesTUI(App["LaunchRequest | None"]):
    CSS_PATH = "theme.tcss"
    BINDINGS = [
        Binding("j,down", "next_account", "Next", show=False),
        Binding("k,up", "previous_account", "Previous", show=False),
        Binding("r", "refresh_snapshot", "Refresh"),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def action_refresh_snapshot(self) -> None:
        result = self.service.refresh()
        self.render_snapshot(result.snapshot, preserve_selection=True)
```

Use Textual messages rather than calling parent widget methods directly.
Keep the box-loop deterministic: model its phases as explicit state rather
than asserting wall-clock timing in tests. It runs only during onboarding,
surrounds the static wide ANSI wordmark, and immediately settles for motion
disabled or narrow layouts. Add `--no-motion` to the entrypoint work in Task 7.

- [ ] **Step 4: Run application tests**

Run: `.venv/bin/python -m pytest tests/tui/test_application.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shambles/app/tui/application.py tests/tui/test_application.py
git commit -m "feat: add TUI navigation and refresh"
```

### Task 5: Switch worker and result overlay

**Files:**
- Create: `shambles/app/tui/overlays.py`
- Modify: `shambles/app/tui/application.py`
- Modify: `tests/tui/test_application.py`

**Interfaces:**
- Consumes: service `plan_switch()`, `switch()`, `ActionResult`
- Produces: `ResultScreen`, exclusive switch worker, and launch choice

- [ ] **Step 1: Write switch and duplicate-input tests**

```python
async def test_enter_switches_selected_account(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("j", "enter")
        await pilot.pause()
        assert service.switch_calls == [("claude", "Work")]
        assert app.query_one(ResultScreen).result.ok

async def test_switch_worker_is_exclusive(service):
    service.block_switch = True
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("enter", "enter", "enter")
        await pilot.pause()
        assert len(service.switch_calls) == 1
```

- [ ] **Step 2: Confirm Enter has no switch action**

Run: `.venv/bin/python -m pytest tests/tui/test_application.py -k switch -v`
Expected: FAIL.

- [ ] **Step 3: Implement an exclusive thread worker**

```python
@work(thread=True, exclusive=True, group="mutation")
def perform_switch(self, provider: str, account: str) -> None:
    result = self.service.switch(provider, account)
    self.post_message(SwitchFinished(result))
```

Disable mutation bindings while the worker group is active. On
`SwitchFinished`, render the returned snapshot and push `ResultScreen`.
Errors stay open until Escape or an explicit recovery action.

- [ ] **Step 4: Run switch tests**

Run: `.venv/bin/python -m pytest tests/tui/test_application.py -k switch -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shambles/app/tui/application.py shambles/app/tui/overlays.py tests/tui/test_application.py
git commit -m "feat: switch accounts from terminal UI"
```

### Task 6: Lifecycle and confirmation workflows

**Files:**
- Create: `shambles/app/tui/workflows.py`
- Modify: `shambles/app/tui/application.py`
- Modify: `tests/tui/test_application.py`

**Interfaces:**
- Consumes: lifecycle plans and results from `ShamblesService`
- Produces: name input, account action menu, confirmation, login progress, and
  eject screens

- [ ] **Step 1: Write representative workflow tests**

```python
async def test_remove_needs_explicit_confirmation(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "d")
        assert app.screen.id == "confirm-action"
        assert service.remove_calls == []
        await pilot.press("escape")
        assert service.remove_calls == []

async def test_login_can_be_cancelled(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("l")
        await pilot.press("escape")
        assert service.login_handle.cancelled is True
```

- [ ] **Step 2: Confirm workflow screens are absent**

Run: `.venv/bin/python -m pytest tests/tui/test_application.py -k 'remove or login' -v`
Expected: FAIL.

- [ ] **Step 3: Implement workflows against plans**

```python
class ConfirmAction(Screen[bool]):
    BINDINGS = [
        Binding("enter", "confirm", "Confirm"),
        Binding("escape", "cancel", "Cancel"),
    ]
    def action_confirm(self):
        self.dismiss(True)
    def action_cancel(self):
        self.dismiss(False)
```

Add Save, Add, Rename, Remove, Login, and Eject screens. Pass confirmed
`ActionPlan` objects back to the matching service method. Validate names in
the service and display its error rather than duplicating naming rules.

- [ ] **Step 4: Run workflow and service tests**

Run: `.venv/bin/python -m pytest tests/tui/test_application.py tests/test_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shambles/app/tui tests/tui/test_application.py
git commit -m "feat: add TUI account workflows"
```

### Task 7: Entrypoint dispatch and same-terminal launch

**Files:**
- Modify: `shambles/__main__.py`
- Modify: `shambles/app/cli.py`
- Create: `shambles/app/launch.py`
- Create: `tests/tui/test_launch.py`
- Modify: `tests/test_gui_import.py`

**Interfaces:**
- Consumes: `run_tui(service) -> LaunchRequest | None`,
  `login.binary(provider)`
- Produces: `launch.replace_process(request, execvp=os.execvp)`, `tui` and
  `gui` dispatch

- [ ] **Step 1: Write dispatch and launch tests**

```python
def test_launch_replaces_process_with_vendor_command(monkeypatch, claude):
    calls = []
    replace_process(LaunchRequest("claude"), providers=[claude],
                    execvp=lambda file, argv: calls.append((file, argv)))
    assert calls == [("claude", ["claude"])]

def test_bare_command_uses_tui_only_on_a_tty(monkeypatch):
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert selected_frontend([]) == "tui"
```

- [ ] **Step 2: Confirm dispatch helpers are missing**

Run: `.venv/bin/python -m pytest tests/tui/test_launch.py tests/test_gui_import.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement safe process replacement**

```python
@dataclass(frozen=True)
class LaunchRequest:
    provider: str

def replace_process(request, *, providers, execvp=os.execvp):
    provider = next(p for p in providers if p.id == request.provider)
    argv = [login.binary(provider)]
    execvp(argv[0], argv)
```

Call this only after `run_tui()` returns, which proves Textual has left
application mode. Do not pass credential-derived environment variables.

- [ ] **Step 4: Add explicit frontend dispatch**

```python
COMMANDS = ("list", "switch", "tui", "gui")

def selected_frontend(argv):
    if "gui" in argv:
        return "gui"
    if "tui" in argv:
        return "tui"
    if not argv and sys.stdin.isatty() and sys.stdout.isatty():
        return "tui"
    return "cli"
```

Noninteractive bare invocation prints help and exits with `EXIT_USAGE`.

- [ ] **Step 5: Run entrypoint and launch tests**

Run: `.venv/bin/python -m pytest tests/tui/test_launch.py tests/test_gui_import.py tests/test_snapshot.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add shambles/__main__.py shambles/app/cli.py shambles/app/launch.py tests
git commit -m "feat: dispatch TUI and launch vendor in place"
```

### Task 8: Visual snapshots, security, and documentation

**Files:**
- Create: `tests/tui/test_snapshots.py`
- Create: `tests/tui/snapshot_app.py`
- Create: `tests/tui/snapshots/`
- Modify: `tests/test_login.py`
- Modify: `README.md`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: completed TUI
- Produces: visual regression fixtures and user documentation

- [ ] **Step 1: Add snapshot cases**

```python
@pytest.mark.parametrize("terminal_size", [
    (100, 32), (78, 28), (60, 28), (48, 24), (40, 24),
])
def test_dashboard_layouts(snap_compare, terminal_size):
    assert snap_compare(
        "tests/tui/snapshot_app.py",
        terminal_size=terminal_size,
    )
```

Add separate fixtures with `NO_COLOR=1` and ASCII branding forced. Review the
generated SVG changes manually before accepting them.

- [ ] **Step 2: Run snapshots and confirm they are unapproved**

Run: `.venv/bin/python -m pytest tests/tui/test_snapshots.py -v`
Expected: FAIL until the intended snapshots are accepted.

- [ ] **Step 3: Extend the security boundary test**

Keep networking imports banned in first-party `shambles/**/*.py`. Add an AST
test that TUI modules do not import `switcher`, `login`, or `eject`
directly, except `app/launch.py`, which may use `login.binary`.

- [ ] **Step 4: Document installation and operation**

Update README usage with `shambles`, `shambles tui`, `shambles gui`,
shortcuts, affected applications, same-terminal launch, restart requirements,
`NO_COLOR`, and the absence of update checks.

- [ ] **Step 5: Run complete verification**

Run: `.venv/bin/python -m pytest && git diff --check`
Expected: all tests pass and no whitespace errors.

- [ ] **Step 6: Commit**

```bash
git add tests/tui tests/test_login.py README.md CHANGELOG.md
git commit -m "test: verify terminal UI across layouts"
```
