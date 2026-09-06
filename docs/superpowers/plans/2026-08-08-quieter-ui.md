# Quieter UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Quieter profile cards (state chips, no ACTIVE text) and expandable rare banners, plus shorter Add Account copy.

**Architecture:** Change face copy in `profiles.expiry_label` / `expiry_severity`; keep date prose in `gui.expiry_tooltip` / chip tooltip selection; add a small expand/collapse helper in `gui.py` for the two banners. Stay on Tkinter.

**Tech Stack:** Python 3, Tkinter/ttk, pytest

**Spec:** [`docs/superpowers/specs/2026-08-08-quieter-ui-design.md`](../specs/2026-08-08-quieter-ui-design.md)

## Global Constraints

- No new UI toolkit; no theme palette rewrite; no group-header changes.
- Healthy cards: name + email only; active = blue spine only.
- Face chips: `soon` / `needs login` only — never countdown numbers.
- Banners start collapsed on every `refresh()`; no preference file.
- No separate ⚠ badge when the chip already says `needs login`.

## File map

| File | Responsibility |
|---|---|
| `shambles/profiles.py` | Face labels + severity keyed on liveness state |
| `shambles/gui.py` | Cards, chip tooltips, expandable banners, Add Account copy |
| `tests/test_profiles.py` | Label/severity expectations |
| `tests/test_gui_import.py` | Card quietness, banner expand, Add Account copy |

---

### Task 1: State-word face labels

**Files:**
- Modify: `shambles/profiles.py` (`expiry_label`, `expiry_severity`)
- Test: `tests/test_profiles.py`

**Produces:** `expiry_label` → `"soon"` | `"needs login"` | `None`; `expiry_severity` → soon/gone for closing/closed/absent even when `days_left` is None.

- [ ] **Step 1: Update the failing test expectations**

In `test_the_countdown_reads_from_the_token`, change expected labels to state words; rename if helpful. Expect:

| offset | state | label |
|---|---|---|
| 30d | LIVE | `None` |
| 1d+1h | CLOSING | `"soon"` |
| 6h | CLOSING | `"soon"` |
| -3d | CLOSED | `"needs login"` |

Change `test_a_profile_with_no_token_is_absent_not_expired` so `expiry_label` is `"needs login"` (warning text may still exist for tooltips).

Add:

```python
def test_expiry_severity_covers_absent_without_days(paths, claude):
    make_profile(paths, "claude", "Work", token=False)
    found = profiles.discover(paths, claude, None, NOW, platform="linux")[0]
    assert profiles.expiry_severity(found) == profiles.EXPIRY_GONE
```

- [ ] **Step 2: Run tests — expect FAIL**

`pytest tests/test_profiles.py::test_the_countdown_reads_from_the_token tests/test_profiles.py::test_a_profile_with_no_token_is_absent_not_expired -v`

- [ ] **Step 3: Implement**

```python
FACE_LABELS = {
    CLOSING: "soon",
    CLOSED: "needs login",
    ABSENT: "needs login",
}
SEVERITY = {CLOSING: EXPIRY_SOON, CLOSED: EXPIRY_GONE, ABSENT: EXPIRY_GONE}

def expiry_label(profile):
    return FACE_LABELS.get(profile.liveness.state)

def expiry_severity(profile):
    return SEVERITY.get(profile.liveness.state)
```

- [ ] **Step 4: Run tests — expect PASS**

- [ ] **Step 5: Commit** `feat: show soon/needs-login chips instead of countdowns`

---

### Task 2: Quiet cards + chip tooltips

**Files:**
- Modify: `shambles/gui.py` (`_render_card`, `expiry_tooltip` callers)
- Test: `tests/test_gui_import.py`

**Consumes:** Task 1 labels/severity.

- [ ] **Step 1: Failing GUI tests**

```python
def test_a_healthy_active_card_has_no_active_label_or_countdown(paths, make_app):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True,
                 refresh_expires_ms=NOW + 30 * DAY_MS)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)
    app = make_app(paths)
    app.refresh()
    text = _all_text(app.rows)
    assert "ACTIVE" not in text
    assert "30d" not in text
    assert "Work" in text and "w@example.com" in text

def test_a_closed_card_shows_needs_login_not_a_warning_glyph(paths, make_app):
    make_profile(paths, "claude", "Old", email="o@example.com",
                 refresh_expires_ms=NOW - 3 * DAY_MS)
    app = make_app(paths)
    app.refresh()
    text = _all_text(app.rows)
    assert "needs login" in text
    assert "⚠" not in text.split("Claude")[0]  # prefer: no ⚠ on the card row
```

Use a tighter assertion: walk card labels and assert no lone `⚠` badge text if easier — or assert `"needs login" in text` and that warning glyph is not packed beside the chip (inspect that `_render_card` no longer creates the badge).

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement**

- Remove `ACTIVE` label from `_render_card`.
- Chip tooltip: if `profile.liveness.expires_at_ms` is set, use `expiry_tooltip(profile)`; else use `profiles.warning(profile)` (or empty).
- Remove the separate ⚠ badge block.
- Keep `expiry_tooltip` working when `days_left` is negative/positive (date from `expires_at_ms`).

- [ ] **Step 4: PASS + commit** `feat: quiet profile cards — spine for active, state chip tooltips`

---

### Task 3: Expandable banners + Add Account copy

**Files:**
- Modify: `shambles/gui.py` (`_render_missing_vendor`, `_render_override_banner`, `AddAccountDialog`, new helper)
- Test: `tests/test_gui_import.py`

- [ ] **Step 1: Failing tests**

```python
def test_missing_vendor_banner_starts_collapsed(paths, make_app, fake_vendor):
    make_profile(paths, "claude", "Work", email="w@example.com")
    # only claude binary missing — or both; ensure found profiles so banner shows
    app = make_app(paths)
    app.refresh()
    text = _all_text(app.rows)
    assert "not on PATH — can't add accounts" in text or "not on PATH" in text
    assert "Switching between accounts you already saved still works" not in text

def test_missing_vendor_banner_expands_on_details(paths, make_app):
    # find Details button, invoke, assert expanded phrase present

def test_add_account_dialog_omits_shared_history_paragraph(paths, make_app, monkeypatch):
    # Instantiate AddAccountDialog briefly or inspect constructed labels —
    # or open dialog with fake and check text via a test harness that builds dialog without wait_window
```

Note: `AddAccountDialog` calls `wait_window` — may need to `after(0, destroy)` or extract body-building; follow existing patterns. If none, monkeypatch `wait_window`/`grab_set` no-ops and destroy after assert.

Update `test_a_missing_vendor_placeholder_says_so...` if it still looks for `"not on your PATH"` on empty groups (placeholder copy is separate — leave unless it breaks).

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement** `_expandable_banner(parent, *, bg, summary, detail, theme, summary_font=..., detail_fg=...)` with Details/Hide toggling a detail `Label`. Wire missing-vendor and override. Add Account: replace long paragraph with `Browser will open to sign in`.

- [ ] **Step 4: PASS + commit** `feat: collapse rare banners; shorten Add Account copy`

- [ ] **Step 5: Full suite** `pytest -q` — green. Update spec status to IMPLEMENTED if desired.
