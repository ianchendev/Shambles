# TUI Visual Refresh Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restyle the existing Textual TUI to the visual refresh spec: README lockup header, grouped list, hero inspector, Switch/Add/Eject footer, and matching overlays — without changing switch, login, or eject behaviour.

**Architecture:** Presentation-only. `ShamblesService` and snapshots stay the data source. `brand.py` gains a framed lockup and a height-aware header choice. `widgets.py` gains a hero renderer and grouped list rows. `theme.tcss` owns chrome (unicode borders, spine, overlay title bars, footer). `application.py` binds top-level `a` to an Add overlay and drops the onboarding box-draw.

**Tech Stack:** Python 3.10+, Textual 8.2.x, Rich, pytest, pytest-asyncio, pytest-textual-snapshot

**Spec:** `docs/superpowers/specs/2026-09-08-tui-visual-refresh-design.md`

## File map

| File | Responsibility after this work |
|---|---|
| `shambles/app/tui/brand.py` | Wordmark rows, framed README lockup, compact mark, `header_kind(width, height)` |
| `shambles/app/tui/widgets.py` | Grouped `AccountList`, one-line rows, `render_account_details` hero, usage bars |
| `shambles/app/tui/dashboard.py` | Lockup/compact header, footer, `BANNER_MIN_HEIGHT`, drop surface-pills title |
| `shambles/app/tui/theme.tcss` | Palette, unicode pane borders, spine, overlay chrome, footer |
| `shambles/app/tui/application.py` | Empty welcome uses lockup (no `OnboardingFrame`); top-level `a`; help copy |
| `shambles/app/tui/overlays.py` | Shared overlay title-bar markup; danger class |
| `shambles/app/tui/workflows.py` | `AddAccountScreen` (provider + name); overlay chrome classes |
| `tests/tui/test_brand.py` | Lockup matches README; height gate; ASCII lockup |
| `tests/tui/test_dashboard.py` | Grouped rows, hero copy, footer, wide-but-short uses inline inspector |
| `tests/tui/test_application.py` | No box-draw; `a` add; empty-state add; help lists `a`/`x` |
| `tests/tui/test_snapshots.py` | Existing sizes plus wide-but-short; overlay snapshots |
| `README.md` / `CHANGELOG.md` | Shortcut table and unreleased notes |

Do not split `application.py` in this pass unless a task cannot land without it. Do not touch `theme.py` (Tk) or `service.py`.

## Global Constraints

- TUI modules must not import `switcher`, `login`, or `eject`.
- Terracotta `#e07a5f`, gold `#d9a441`, navy `#0b1020`, pane `#11182b`, selected wash `#1a2238`, cream `#f4f1de`, muted `#8b90a0`.
- Wide split requires width ≥ 78 **and** height ≥ 24 (`BANNER_MIN_HEIGHT`). `MINIMUM_HEIGHT` stays 16.
- Compact header is `>_ ⇄ SHAMBLES` / `>_ <-> SHAMBLES` whenever the lockup does not fit — including medium width and wide-but-short.
- Unicode box drawing when `unicode=True`; ASCII `+ - |` and `#`/`-` bars otherwise.
- `OFFLINE` on the lockup is brand copy, not a network probe.
- Never display credentials. Snapshot tests stay on `tests/tui/snapshot_app.py` fixtures.
- Add still calls `service.add(provider, name)` only. Do not start vendor login automatically (current TUI behaviour).
- `AccountList.highlighted` remains an **account** index (0..n-1), not a widget index. Group headers are not selectable.
- No new dependencies.

---

### Task 1: Framed README lockup

**Files:**
- Modify: `shambles/app/tui/brand.py`
- Modify: `tests/tui/test_brand.py`
- Modify: `shambles/app/tui/dashboard.py` (export `BANNER_MIN_HEIGHT = 24` only; composition in Task 4)

**Interfaces:**
- Consumes: existing `BrandVariant`, `WIDE_UNICODE_ROWS`, `variant_for(width)`
- Produces:
  - `BANNER_MIN_HEIGHT = 24` in `dashboard.py` (Task 4 imports it; define the constant here in brand or dashboard — **put it in `dashboard.py` next to `MINIMUM_HEIGHT`**, and a copy-free import in tests)
  - `LOCKUP_MIN_HEIGHT = 24` in `brand.py` as the single source, re-exported from dashboard as `BANNER_MIN_HEIGHT = LOCKUP_MIN_HEIGHT`
  - `def lockup_text(*, unicode: bool = True) -> str`
  - `def header_kind(width: int, height: int) -> str` returning `"lockup"` or `"compact"`
  - `def header_text(width: int, height: int, *, unicode: bool = True) -> str`
  - `brand_text(BrandVariant.WIDE)` still returns the six wordmark rows only (interior of the lockup)

- [ ] **Step 1: Write failing brand tests**

Add to `tests/tui/test_brand.py`:

```python
from shambles.app.tui.brand import header_kind, header_text, lockup_text

README_LOCKUP_START = "╔═[ >_ ⇄ ]"
README_TAGLINE = "Switch Claude and Codex accounts safely."
OFFLINE_CHIP = "OFFLINE"


def test_lockup_contains_readme_wordmark_frame_and_tagline():
    text = lockup_text(unicode=True)
    assert README_LOCKUP_START in text.splitlines()[0]
    assert OFFLINE_CHIP in text
    assert README_TAGLINE in text
    for row in README_WORDMARK:
        assert row in text
    assert "\x1b" not in text


def test_ascii_lockup_is_strict_ascii_and_names_shambles():
    text = lockup_text(unicode=False)
    assert text.isascii()
    assert ">_ <->" in text
    assert "OFFLINE" in text
    assert "SHAMBLES" in text
    assert "\x1b" not in text


@pytest.mark.parametrize(
    ("width", "height", "kind"),
    [
        (100, 32, "lockup"),
        (78, 24, "lockup"),
        (78, 23, "compact"),
        (77, 32, "compact"),
        (40, 24, "compact"),
    ],
)
def test_header_kind_requires_wide_and_tall(width, height, kind):
    assert header_kind(width, height) == kind


def test_header_text_lockup_vs_compact():
    assert "OFFLINE" in header_text(80, 32, unicode=True)
    assert header_text(80, 16, unicode=True) == ">_ ⇄ SHAMBLES"
    assert header_text(80, 16, unicode=False) == ">_ <-> SHAMBLES"
```

Keep `test_wide_brand_preserves_the_readme_wordmark_without_its_frame` — `brand_text(WIDE)` must stay the unframed six lines. Extend `test_fixed_brand_rows_fit_their_variant` so `lockup_text` rows also have `cell_len <= 78`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/tui/test_brand.py -v`

Expected: FAIL on missing `lockup_text` / `header_kind`.

- [ ] **Step 3: Implement lockup and header choice**

In `brand.py`:

- `LOCKUP_MIN_HEIGHT = 24`
- Copy the README `<details>` ASCII banner into `LOCKUP_UNICODE_ROWS` (verbatim, including the `>_ ⇄` and `OFFLINE` chips and the tagline). Interior wordmark rows must equal `WIDE_UNICODE_ROWS`.
- `LOCKUP_ASCII_ROWS`: a `+ - |` frame of width ≤ 78 containing `>_ <->`, `OFFLINE`, `SHAMBLES`, and `Claude + Codex account switcher`.
- `lockup_text(unicode=True/False)` joins those tuples.
- `header_kind(width, height)`: `"lockup"` iff `width >= 78 and height >= LOCKUP_MIN_HEIGHT`, else `"compact"`.
- `header_text(...)`: lockup or compact mark.

Do not animate. Do not embed ANSI colour in the strings.

- [ ] **Step 4: Run brand tests**

Run: `.venv/bin/python -m pytest tests/tui/test_brand.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add shambles/app/tui/brand.py tests/tui/test_brand.py
git commit -m "$(cat <<'EOF'
feat: add framed README lockup for the TUI header

EOF
)"
```

---

### Task 2: Hero inspector renderer

**Files:**
- Modify: `shambles/app/tui/widgets.py`
- Modify: `tests/tui/test_dashboard.py`

**Interfaces:**
- Consumes: `Account`, `Group`, `Window`
- Produces:
  - `def usage_bar(percent: int | None, width: int = 20, *, unicode: bool = True) -> str`
  - `def render_account_details(group, account, *, width: int = 80, unicode: bool = True, compact: bool = False) -> Table`
  - Chip labels: `Active` / `needs login` / `Saved` via existing `_state_copy` renamed or replaced by `_chip(account)` returning those three strings (`Active` if `active`, `needs login` if `needs_login`, else `Saved`)

Hero (wide, `compact=False`) must include, in order: title (name + chip), identity heading, plan/provider pills when present, `USAGE` meters, `SWITCHES` (surface label + detail), login callout when `needs_login`, context line.

Compact hero (`compact=True`): title, identity, plan pill, first usage meter only, login callout. No SWITCHES, no extra meters.

Usage: `█`/`░` or `#`/`-`. `None` percent → empty muted bar + `unavailable`. Stale → keep bar, show `stale` and `age_label`.

Context lines exactly:

- active: `Already active · m for actions · running sessions keep their login`
- needs_login: `l to log in · cannot switch until this account is signed in`
- else: `Enter to switch · m for actions`

- [ ] **Step 1: Write failing renderer tests**

In `tests/tui/test_dashboard.py` replace copy assertions that mention `session: 22% used`, `Claude / Work`, `Login required`, `Resets Unavailable` with hero copy. Add:

```python
from shambles.app.tui.widgets import render_account_details, usage_bar


def test_usage_bar_fills_and_falls_back_to_ascii():
    assert "█" in usage_bar(22, width=10, unicode=True)
    assert usage_bar(None, width=4, unicode=True) == "░░░░"
    assert usage_bar(50, width=4, unicode=False) == "##--"
    assert usage_bar(None, width=4, unicode=False) == "----"


def test_hero_details_use_meters_pills_and_context(snapshot):
    group, account = snapshot.groups[0], snapshot.groups[0].accounts[0]
    table = render_account_details(group, account, width=60, unicode=True)
    # Render through the existing rendered_text helper by wrapping in AccountDetails
    # or print the Table. Prefer mounting through DashboardHarness at (100, 32):
```

Use `DashboardHarness` at `(100, 32)`:

```python
async def test_wide_hero_shows_identity_meter_and_surfaces(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        screen = screen_text(app)
        assert "work@example.test" in screen
        assert "Max 5x" in screen
        assert "USAGE" in screen
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
        await pilot.pause()
        screen = screen_text(app)
        assert "needs login" in screen
        assert "Run claude login" in screen
        assert "l to log in" in screen
```

Update `test_compact_dashboard_keeps_usage_percentage_readable` to assert `22%` (not `session: 22% used`).
Update `test_usage_percentage_and_stale_copy_remain_visible` to assert `22%`, `stale`, `just now`.
Update `test_account_details_use_snapshot_labels_and_safe_unavailable_copy`: Personal week with `used_percent=33` but `resets_at_ms=None` should show `unavailable` for reset, not `Resets Unavailable`.
Update `test_wide_account_headers_keep_identity_separate_from_login_state` to look for row `Personal` and chip `needs login` without `Claude / Personal`.
Update `test_narrow_dashboard_hides_decoration` to drop `#surface-pills` (widget removed in Task 4 — if this task still has the widget, skip that line until Task 4). For this task, only change detail-copy assertions.

`test_no_color_account_copy_is_strict_ascii` must still pass: pass `unicode=False` into `render_account_details` from `AccountDetails` when `app.unicode` is false. `DashboardHarness` has no unicode flag — default hero unicode True in harness. ASCII assertion on the Table: `AccountDetails.show_account` should take unicode from `self.app.unicode` if present, else `True`. For `DashboardHarness`, keep unicode True; the ascii test currently expects the whole screen to be ascii, which **will fail** once the lockup uses box drawing. Change that test to: details table is ascii when `AccountDetails(unicode=False)` / compact widths still ascii for `#` bars. Split: `rendered_text` of details with unicode False is ascii; do not require the full screen to be ascii on Unicode dashboards.

- [ ] **Step 2: Run the new tests**

Run: `.venv/bin/python -m pytest tests/tui/test_dashboard.py::test_usage_bar_fills_and_falls_back_to_ascii tests/tui/test_dashboard.py::test_wide_hero_shows_identity_meter_and_surfaces tests/tui/test_dashboard.py::test_hero_needs_login_callout -v`

Expected: FAIL (`usage_bar` missing / old table copy).

- [ ] **Step 3: Rewrite `render_account_details` and `_account_row`**

`_account_row` becomes one line (name + chip) — grouping headers land in Task 3, but the row itself should already be one line so Task 3 can wrap it.

`AccountDetails.show_account` calls `render_account_details(..., unicode=..., compact=not self.has_class / parent Dashboard.wide)`. Until Task 4, pass `compact=False` for `#account-details` and `compact=True` for `#inline-details`.

- [ ] **Step 4: Run dashboard unit tests**

Run: `.venv/bin/python -m pytest tests/tui/test_dashboard.py -v`

Expected: PASS (adjust any leftover `Claude /` or `session: 22% used` assertions in this same task).

- [ ] **Step 5: Commit**

```bash
git add shambles/app/tui/widgets.py tests/tui/test_dashboard.py
git commit -m "$(cat <<'EOF'
feat: render TUI account details as a hero inspector

EOF
)"
```

---

### Task 3: Grouped list with spine

**Files:**
- Modify: `shambles/app/tui/widgets.py`
- Modify: `shambles/app/tui/theme.tcss`
- Modify: `tests/tui/test_dashboard.py`

**Interfaces:**
- Consumes: Task 2 one-line `_account_row`
- Produces: `AccountList` children are `Static` group headers (class `group-header`, not `ListItem`) **or** disabled `ListItem`s that `highlighted` skips. Prefer: only `AccountRow` ListItems; draw the section header as a `Static` mounted **inside** the first `AccountRow` of each group via a `group-header` child so ListView indices stay 0..n-1.

Chosen approach (keeps `highlighted` as account index):

```python
# First account of a group:
AccountRow(group, account, Static(group.display_name, classes="group-header"), details?)
# Later accounts in the group:
AccountRow(group, account)
```

CSS: `.group-header { color: #d9a441; text-style: bold; }`
Selected row: terracotta 1-cell left border + `#1a2238` wash, **not** full `#e07a5f` fill. Update:

```css
#account-list > AccountRow.-highlight .account-row {
    background: #1a2238;
    color: #f4f1de;
    border-left: tall #e07a5f;
    text-style: none;
}
```

Drop the old terracotta fill + navy text.

- [ ] **Step 1: Failing tests for grouping**

```python
async def test_list_groups_by_provider_and_keeps_one_line_rows(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        screen = screen_text(app)
        assert "Claude" in screen  # Group.display_name in fixture
        assert "Codex" in screen
        assert "Claude / Work" not in screen
        accounts = app.query_one(AccountList)
        assert accounts.highlighted == 0  # Work is active
        await pilot.press("down")
        assert accounts.highlighted == 1
```

- [ ] **Step 2: Run it**

Run: `.venv/bin/python -m pytest tests/tui/test_dashboard.py::test_list_groups_by_provider_and_keeps_one_line_rows -v`

Expected: FAIL (`Claude / Work` still present or no group header).

- [ ] **Step 3: Implement grouped rows + CSS spine**

- [ ] **Step 4: Run dashboard tests plus navigation tests**

Run: `.venv/bin/python -m pytest tests/tui/test_dashboard.py tests/tui/test_application.py::test_cursor_keys_update_selection_and_visible_details tests/tui/test_application.py::test_navigation_stops_at_list_edges -v`

Expected: PASS. If `highlighted` mapping broke, fix `AccountList.highlighted` before continuing.

- [ ] **Step 5: Commit**

```bash
git add shambles/app/tui/widgets.py shambles/app/tui/theme.tcss tests/tui/test_dashboard.py
git commit -m "$(cat <<'EOF'
feat: group TUI accounts by provider with a selection spine

EOF
)"
```

---

### Task 4: Dashboard header, footer, and height gate

**Files:**
- Modify: `shambles/app/tui/dashboard.py`
- Modify: `shambles/app/tui/theme.tcss`
- Modify: `shambles/app/tui/application.py` (footer may live on `ShamblesTUI` so empty welcome can reuse it — if so, put `#shortcut-footer` in the App, not only Dashboard)
- Modify: `tests/tui/test_dashboard.py`

**Interfaces:**
- Consumes: `header_text`, `header_kind`, `LOCKUP_MIN_HEIGHT`
- Produces:
  - `BANNER_MIN_HEIGHT = LOCKUP_MIN_HEIGHT` in `dashboard.py`
  - Dashboard classes: `wide` only when `header_kind == "lockup"` (width≥78 **and** height≥24). `medium` when width≥48 and not wide. `compact` when width<48. `too-short` when height<16.
  - Remove `#surface-pills` and the centered `#dashboard-title`.
  - `#dashboard-header` Static showing `header_text(width, height, unicode=app.unicode)`.
  - `#shortcut-footer` Static. Full: `j/k move · ⏎ switch · a add · x eject · m menu · l login · r refresh · ? help · q quit`. Compact width (`medium` or `compact` class): `⏎ switch · a add · x eject · m menu · ? help · q quit`.
  - `theme.tcss`: list border gold unicode (`tall` or `heavy`), details terracotta; footer gold/terracotta keys; `#dashboard-header` terracotta lockup / compact mark, left-aligned (lockup can be full width, not centered title).

Wide-but-short `(78, 16)`: **not** `wide` — inline inspector, compact header, footer visible (`too-short` is height<16 only).

Rewrite `test_short_wide_details_are_accessible_by_keyboard`: at `(78, 16)` assert compact header (`OFFLINE` not in screen), inline details contain `22%` and `week` / `88%`, `j` still moves selection. Do not require `#account-details` focus/scroll.

Rewrite `test_narrow_dashboard_hides_decoration`: no `#surface-pills`; assert `#account-details` hidden; footer present.

Add:

```python
from shambles.app.tui.brand import LOCKUP_MIN_HEIGHT

async def test_wide_dashboard_shows_lockup_and_footer(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        screen = screen_text(app)
        assert "OFFLINE" in screen
        assert "a add" in screen
        assert "x eject" in screen
        assert app.query_one(Dashboard).has_class("wide")


async def test_wide_but_short_drops_lockup_and_uses_inline_details(snapshot):
    app = DashboardHarness(snapshot)
    async with app.run_test(size=(78, 16)) as pilot:
        await pilot.pause()
        dash = app.query_one(Dashboard)
        assert not dash.has_class("wide")
        assert "OFFLINE" not in screen_text(app)
        assert ">_ ⇄ SHAMBLES" in screen_text(app) or ">_ <-> SHAMBLES" in screen_text(app)
        assert not app.query_one("#account-details").display
        assert app.query_one("#inline-details").display
```

`DashboardHarness` must set `unicode=True` by default. `on_resize` must pass height into `header_kind`.

Footer: if it is easier to share with onboarding, yield it from `ShamblesTUI.compose` outside `#app-body`. Dashboard-only is acceptable for this task if Task 5 adds the same widget on Onboarding.

- [ ] **Step 1: Write the failing layout tests above**
- [ ] **Step 2: Run them** — Expected: FAIL
- [ ] **Step 3: Implement header/footer/CSS/height classes; delete surface pills**
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/tui/test_dashboard.py tests/tui/test_brand.py -v` — PASS
- [ ] **Step 5: Commit** `feat: add TUI lockup header and shortcut footer`

---

### Task 5: Empty welcome without box-draw

**Files:**
- Modify: `shambles/app/tui/application.py`
- Modify: `tests/tui/test_application.py`
- Modify: `tests/tui/test_snapshots.py` (only if onboarding snapshots fail later — prefer Task 7)

**Interfaces:**
- Consumes: `header_text`, `lockup_text`
- Produces: `Onboarding` shows `#dashboard-header`-equivalent lockup/compact mark, copy `No saved accounts yet.`, footer `a add · x eject · r refresh · ? help · q quit`. Remove `BoxPhase`, `OnboardingFrame`, `advance_phase`, `action_settle_onboarding` (keep the binding as a no-op or drop it; `Esc` still closes overlays). `--no-motion` remains accepted in `__init__` and does nothing visible.

- [ ] **Step 1: Replace onboarding tests**

Delete or rewrite tests that import `BoxPhase` / `OnboardingFrame` (`test_onboarding_draws_each_border_phase_then_stays_settled`, `test_enter_and_escape_immediately_settle_every_phase`, `test_motion_opt_out_starts_with_a_complete_frame`, `test_narrow_resize_settles_and_widening_does_not_replay`, `test_refresh_does_not_replay_onboarding`).

Replace with:

```python
async def test_empty_welcome_shows_lockup_and_add_footer(empty_service):
    app = ShamblesTUI(empty_service, motion=True)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.pause()
        screen = screen_text(app)
        assert "No saved accounts yet." in screen
        assert "OFFLINE" in screen
        assert "a add" in screen
        assert "x eject" in screen
        for row in brand_text(BrandVariant.WIDE).splitlines():
            assert row in screen


async def test_empty_welcome_compact_header_when_short(empty_service):
    app = ShamblesTUI(empty_service)
    async with app.run_test(size=(78, 16)) as pilot:
        await pilot.pause()
        screen = screen_text(app)
        assert "OFFLINE" not in screen
        assert "No saved accounts yet." in screen
        assert "a add" in screen


async def test_ascii_onboarding_fallback_is_readable(empty_service):
    app = ShamblesTUI(empty_service, unicode=False)
    async with app.run_test(size=(100, 32)):
        assert screen_text(app).isascii()
        assert "SHAMBLES" in screen_text(app)
        assert "OFFLINE" in screen_text(app)
```

Update `test_wide_onboarding_keeps_controls_visible_at_minimum_height`: at height 16 lockup is **not** shown; assert compact mark + `a add` + copy, not every wordmark row.

Remove `stepped_motion` fixture uses if `OnboardingFrame.set_interval` is gone.

- [ ] **Step 2: Run** `tests/tui/test_application.py` onboarding tests — FAIL
- [ ] **Step 3: Rewrite `Onboarding.compose`; delete `OnboardingFrame` / `BoxPhase`**
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/tui/test_application.py tests/tui/test_dashboard.py -v` — PASS
- [ ] **Step 5: Commit** `feat: show README lockup on empty TUI welcome`

---

### Task 6: Overlay chrome and top-level Add

**Files:**
- Modify: `shambles/app/tui/theme.tcss`
- Modify: `shambles/app/tui/overlays.py`
- Modify: `shambles/app/tui/workflows.py`
- Modify: `shambles/app/tui/application.py`
- Modify: `tests/tui/test_application.py`

**Interfaces:**
- Consumes: existing `service.add(provider, name)`, `NameInputScreen` for rename/save
- Produces:
  - CSS classes `.overlay-panel` (gold border `#d9a441`, pane `#11182b`) and `.overlay-panel.danger` (terracotta border). Title bar widget or first Static with class `overlay-title`.
  - `AddAccountScreen(ModalScreen[tuple[str, str] | None])` id `add-account`: provider list from `snapshot.groups` (display_name, provider id), name `Input`. `j`/`k` move provider when input is not capturing… **Problem:** `Input` eats keys. Match Tk: radio-style lines above the input; `up`/`down` change provider while focus can start on the provider list, `tab` to Input. Simpler: one `OptionList` or labelled `Static` lines with `j`/`k` Bindings on the screen (`priority=True` when focus is not the Input). Bind `up`/`down`/`j`/`k` on the screen to change provider index; Input still used for the name.
  - Preselect `selected_provider` if set, else first group.
  - `Enter` on Input submits `(provider_id, name)`; `Esc` dismisses `None`.
  - `ShamblesTUI` binding `a` → `action_add_account` (gated like other mutations). Empty welcome: `a` works (`check_action` must **not** require a selected account for add). `m` still requires selection.
  - Menu `a` pushes the same `AddAccountScreen` (not `NameInputScreen`).
  - Help copy lists `a` Add and `x` Eject.

Update tests:

```python
async def test_add_prompts_for_a_name_and_creates_an_empty_profile(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("a")  # top-level
        assert app.screen.id == "add-account"
        await pilot.press(*"fresh", "enter")
        await pilot.pause()
        assert service.add_calls == [("claude", "fresh")]


async def test_menu_a_uses_the_same_add_overlay(service):
    app = ShamblesTUI(service)
    async with app.run_test() as pilot:
        await pilot.press("m", "a")
        assert app.screen.id == "add-account"


async def test_empty_welcome_can_add(empty_service):
    empty_service.add_calls = []
    # SnapshotService needs add(); extend the fake if missing
    app = ShamblesTUI(empty_service)
    async with app.run_test(size=(100, 32)) as pilot:
        await pilot.press("a")
        assert app.screen.id == "add-account"
```

Extend `SnapshotService` with `add` if empty tests use it — `empty_service` already used for refresh; add `add_calls` / `add` like the populated fake.

`test_add_can_be_cancelled_without_calling_the_service`: press `a` then `escape`.

`test_help_lists_lifecycle_shortcuts`: assert `a` / `Add` and `x` / `Eject`.

Confirm/result/menu/name-input/login/help: add `overlay-panel` (confirm/remove/eject/fail: also `danger`). No six-line wordmark on dialogs.

- [ ] **Step 1: Write failing add/help tests**
- [ ] **Step 2: Run** — FAIL
- [ ] **Step 3: Implement `AddAccountScreen`, bindings, CSS**
- [ ] **Step 4: Run** `.venv/bin/python -m pytest tests/tui/test_application.py -v` — PASS
- [ ] **Step 5: Commit** `feat: add TUI footer Add overlay and overlay chrome`

---

### Task 7: Snapshots, README, changelog

**Files:**
- Modify: `tests/tui/test_snapshots.py`
- Modify: `tests/tui/snapshot_app.py` (only if extra apps needed)
- Modify: `tests/tui/__snapshots__/test_snapshots/` (via `--snapshot-update` after visual check)
- Modify: `README.md` (keyboard table)
- Modify: `CHANGELOG.md` Unreleased

**Interfaces:**
- Consumes: completed TUI
- Produces: snapshots for `(100, 32)`, `(78, 28)`, `(78, 16)` wide-but-short, `(60, 28)`, `(48, 24)`, `(40, 24)`; empty unicode lockup; empty ASCII; `NO_COLOR` empty. Optional: help overlay snapshot via a tiny `snapshot_app.py:help_app` that pushes HelpScreen — skip if plugging HelpScreen needs a running service; unit tests already cover help copy.

- [ ] **Step 1: Extend `test_snapshots.py`**

```python
@pytest.mark.parametrize("terminal_size", [
    (100, 32),
    (78, 28),
    (78, 16),  # wide-but-short: compact header, inline details
    (60, 28),
    (48, 24),
    (40, 24),
])
def test_dashboard_layouts(snap_compare, terminal_size):
    assert snap_compare("snapshot_app.py", terminal_size=terminal_size)
```

Keep ascii and no_color empty-welcome tests.

- [ ] **Step 2: Run snapshots (expect fail)**

Run: `.venv/bin/python -m pytest tests/tui/test_snapshots.py -v`

Expected: FAIL (SVG mismatch).

- [ ] **Step 3: Review SVGs and update**

Run: `.venv/bin/python -m pytest tests/tui/test_snapshots.py -v --snapshot-update`

Open the new SVGs. Confirm lockup, spine (not full terracotta fill), hero USAGE/SWITCHES, footer `a add` / `x eject`. Then re-run without `--snapshot-update` — PASS.

- [ ] **Step 4: README + CHANGELOG**

README keyboard table: add `a` Add (provider + name overlay); keep `x` Eject; note footer. `Esc` no longer “skip onboarding animation”. Menu: `s`/`n`/`d`; `a` add also from the dashboard.

CHANGELOG Unreleased: TUI visual refresh — lockup, grouped list, hero inspector, footer Add/Eject.

- [ ] **Step 5: Full TUI suite**

Run: `.venv/bin/python -m pytest tests/tui -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/tui README.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
test: refresh TUI snapshots and document footer shortcuts

EOF
)"
```

---

## Spec coverage

| Spec section | Task |
|---|---|
| Palette / unicode borders / overlay CSS | 3, 4, 6 |
| README lockup + compact fallback + height 24 | 1, 4, 5 |
| Grouped list, chips, spine | 3 |
| Hero inspector + compact inline | 2, 4 |
| Footer Switch / Add / Eject | 4, 6 |
| Empty welcome add/eject, no box-draw | 5, 6 |
| Add overlay provider + name | 6 |
| Overlays restyle, no wordmark on dialogs | 6 |
| Snapshots + ASCII + NO_COLOR | 1, 5, 7 |
| No service/Tk/shortcut-meaning changes except `a` | 6 |
| `--no-motion` no-op | 5 |
