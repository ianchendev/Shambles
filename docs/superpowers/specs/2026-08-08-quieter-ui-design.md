# Shambles — Quieter UI Design

**Date:** 2026-08-08
**Status:** APPROVED — awaiting implementation plan

Reduce day-to-day text on profile cards and long banners/dialogs, without
changing the Tkinter layout model or the product’s switching behaviour. Group
headers are left alone.

Implements the face of [DD-1](../../design-decisions.md#dd-1--token-lifetime-is-system-state-not-a-user-facing-number):
healthy accounts carry no expiry annotation; attention states use short words,
not countdown numbers.

---

## 1. Problem

The main window is compact and works, but it talks too much for a tool whose
primary job is “pick a row, click Switch.”

**Profile cards** show name, email, an `ACTIVE` label, a countdown chip
(`29d`, `today`, `expired Nd ago`), and sometimes a ⚠ — all at once. Healthy
accounts do not need a duration on their face; DD-1 already decided that.

**Banners and dialogs** dump multi-sentence explanations for rare conditions
(missing vendor binary, config-dir env override) and for Add Account (shared
settings / plugins / history). That teaching belongs behind a short summary,
not in the default view.

---

## 2. Goals and non-goals

### Goals

- Quieter healthy cards: name + email only; active marked by the blue spine.
- Attention chips only when the refresh window is closing or closed / absent.
- Collapsed one-line banners with an explicit expand for the current prose.
- Shorter Add Account copy; browser hint stays.

### Non-goals

- Group header wording or layout.
- Theme / palette / dark mode.
- Retuning per-provider `CLOSING` thresholds (DD-1’s “1–1.5 days” note).
- Rewriting one-shot migration `messagebox` text or Eject confirmations.
- Leaving Tkinter or adding a new UI toolkit.

---

## 3. Profile cards

### 3.1 Face content

| Situation | Visible on the card |
|---|---|
| Healthy / live | **Name** + **email** |
| Active | Blue left spine only — **no** `ACTIVE` label |
| Closing soon | Amber chip: `soon` |
| Closed or absent | Red chip: `needs login` — **no** separate ⚠ glyph; put today’s warning prose on the chip tooltip |
| Inactive | Switch + ✕ unchanged |

Email stays on the face so generically named profiles (`work`, `personal`)
remain distinguishable without hovering.

### 3.2 Labels and tooltips

- `profiles.expiry_label(profile)` returns a **face** string only for attention
  states, keyed off liveness / `needs_login`, not off whether `days_left` is set:
  - closing → `"soon"`
  - closed or absent → `"needs login"`
  - live / unknown → `None` (no chip)
- Countdown numbers (`29d`, `today`, `expired Nd ago`) must **not** appear on
  the card face.
- Chip tooltip:
  - closing / closed with a known expiry → keep the exact-date rolling-window
    text (`expiry_tooltip` today); if face labels no longer include days, a
    small helper may format the date from `expires_at_ms` / `days_left`
  - absent / closed with no usable expiry → use the existing `warning()` prose
    (`No token here yet…` / `Refresh window closed…`)
- Do not render both a `needs login` chip and a ⚠ badge on the same row.

### 3.3 Rendering

`gui._render_card` already gates the chip on `expiry_label` being truthy.
After the label change, healthy rows naturally lose the chip. Remove the
`ACTIVE` `Label`. No new card layout widgets.

---

## 4. Banners and dialogs

### 4.1 Expandable banner pattern

Shared behaviour for the two rare cards:

1. **Collapsed (default):** one summary line + a `Details` control.
2. **Expanded:** the summary stays; the existing full explanation appears
   below; control becomes `Hide` (or equivalent).
3. **Persistence:** always start collapsed on each `refresh()` / window open.
   No preference file.

Implementation: one small helper used by `_render_missing_vendor` and
`_render_override_banner` (same frame chrome as today, less body text by
default). Prefer a text button or label-button over inventing new ttk styles
unless the theme already has a fit.

### 4.2 Missing vendor binary

- Collapsed: `{binary} not on PATH — can't add accounts`
  (e.g. `claude not on PATH — can't add accounts`).
- Expanded: current copy — install the CLI to sign in; switching already-saved
  accounts still works.

### 4.3 Config-dir env override

- Collapsed: `⚠ {env_name} is set` plus a truncated path if it fits on one line.
- Expanded: full path + current explanation (terminal uses that tree; Shambles
  swaps the default location; VS Code unaffected; unset in the shell profile
  to use Shambles from the CLI).

### 4.4 Add Account dialog

- Drop the paragraph about shared settings, plugins, and session history.
- Keep provider radio + profile name fields.
- One short line under the name field: `Browser will open to sign in`.
- Create / Cancel unchanged.

---

## 5. Error handling and edge cases

- Profiles with no token / undetermined expiry: still no invented countdown;
  `needs login` chip when `needs_login(profile)` is true; otherwise no chip.
- Expand/collapse must survive `refresh()` destroying and rebuilding the row
  tree (state resets to collapsed — intentional).
- Chip tooltips: same destroy/orphan rules as today (`Tooltip` on `<Destroy>`).
- Empty provider groups and “Save current login” are unchanged.

---

## 6. Testing

- Update unit expectations for `expiry_label` (and any tests that assert
  `"29d"` / `"today"` / `"expired …"` as the face string).
- Tooltip / date formatting still covered where it already is; add a focused
  test if countdown moves out of `expiry_label` into a helper.
- GUI: prefer lightweight checks that collapsed banners expose the short
  summary and that expanded content includes a distinctive phrase from the
  full copy. Do not require pixel-perfect layout tests.
- Card: assert no `ACTIVE` text path if tests currently look for it; assert
  healthy profiles render without an expiry chip label.

---

## 7. File touch list

| File | Change |
|---|---|
| `shambles/profiles.py` | Face `expiry_label`; optional countdown helper for tooltips |
| `shambles/gui.py` | Cards, expandable banners, Add Account copy |
| `tests/…` | Label + banner expectations as above |

`theme.py` only if the Details control needs a trivial style; no palette rewrite.

---

## 8. Success criteria

- A window full of healthy accounts shows name + email per row, no countdown,
  no `ACTIVE` text.
- Closing / closed accounts are obvious from a short chip, not a paragraph.
- Missing-CLI and env-override banners are one line until the user asks for
  Details.
- Add Account dialog fits without a teaching paragraph about shared history.
