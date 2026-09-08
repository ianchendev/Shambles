# Shambles — Terminal UI Visual Refresh

**Date:** 2026-09-08  
**Status:** Approved — plan at [`../plans/2026-09-08-tui-visual-refresh.md`](../plans/2026-09-08-tui-visual-refresh.md)

Give the existing Textual TUI the visual hierarchy of a daily tool: the
README ANSI lockup as the wide header, a grouped account list, a hero
inspector, a shortcut footer, and matching overlays. Switching, login,
eject, and the application service stay as they are.

Amends the presentation sections of
[2026-09-06-terminal-ui-design.md](2026-09-06-terminal-ui-design.md).
That spec remains the architecture, shortcut, and safety source of truth.
This one replaces how those screens look.

---

## 1. Problem

The TUI is complete and keyboard-correct, but it still looks like a first
pass. The dashboard is a centered `SHAMBLES` title, a duplicate surfaces
line, ASCII `+---+` frames, two-line `Provider / Name` rows, a terracotta
full-row highlight, and a details pane that dumps unlabeled fields. Help
and workflows are the same gold ASCII box five times. The README wordmark
only appears on the empty welcome screen.

People open this to pick an account. The screen should look like the brand
they already saw in the README, then get out of the way of identity, usage,
and the next key.

---

## 2. Goals and non-goals

### Goals

- Ship the README framed ANSI lockup as the wide dashboard (and empty
  welcome) header.
- Group accounts by provider, one line per account, with a terracotta
  spine for the selection.
- Replace the details dump with a hero inspector: title bar, identity,
  plan, usage meters, surface pills, contextual next-key line.
- Keep shortcuts visible in a footer, with **Switch**, **Add**, and
  **Eject** as first-class keys the way the Tk window’s footer exposes
  Add and Eject.
- Restyle help, confirm, result, menu, name input, and login progress in
  one overlay language.
- Keep `NO_COLOR`, ASCII fallback, and snapshot coverage. `--no-motion`
  remains accepted so existing flags do not break.

### Non-goals

- Changing switch order, confirmation rules, or `ShamblesService`.
- Changing the Tk window.
- New verbs, providers, or dependencies. `a` is promoted from the
  account menu to a top-level key so Add matches the window footer;
  `x` (eject) already exists and is only made visible.
- The opt-in update notice (already specified). If that work lands later,
  it is a one-line strip above the footer.
- Pixel-scaling, true-color artwork, or loading the README SVG in the TUI.

---

## 3. Palette and chrome

Unchanged brand colours, applied more consistently:

| Role | Colour |
|---|---|
| Ground | `#0b1020` |
| Pane | `#11182b` |
| Selected row wash | `#1a2238` |
| Wordmark, spine, keys, danger | `#e07a5f` |
| Frames, section labels, healthy chips | `#d9a441` |
| Body copy | `#f4f1de` |
| Muted / unavailable | `#8b90a0` |

Unicode terminals use box-drawing borders (`┌┐└┘─│` or Textual `heavy` /
`tall`), not `border: ascii`. `unicode=False` keeps `+ - |`. `NO_COLOR`
keeps the same glyphs and drops the palette.

Shared overlay chrome lives in `theme.tcss`, not copy-pasted
`DEFAULT_CSS` on every screen.

---

## 4. Dashboard

Three bands. No extra `SHAMBLES` title. No header surface-pills row —
surfaces belong in the inspector.

```text
[ README lockup or compact mark ]
[ grouped list | hero inspector ]
[ shortcut footer ]
```

### 4.1 Header lockup

When width ≥ 78 cells **and** height ≥ 24 rows, the header is the README
ASCII banner verbatim:

- gold double frame
- terracotta `>_ ⇄` chip (ASCII `>_ <->`)
- gold `OFFLINE` chip — brand copy for “local-only”, not a live network
  probe
- six-line terracotta wordmark, identical to `brand.WIDE_UNICODE_ROWS`
- gold tagline `Switch Claude and Codex accounts safely.`

That block is already in `README.md`. The TUI must not re-wrap, recolour
the letters independently of the brand rules, or crop it. If it does not
fit, do not show a broken frame.

Otherwise the header is one compact line: `>_ ⇄ SHAMBLES` (or ASCII
`>_ <-> SHAMBLES`), terracotta, left-aligned.

The lockup is always settled. The README frame is part of the artwork, so
the old onboarding box-draw is retired. `--no-motion` and
`SHAMBLES_NO_MOTION=1` remain as no-ops for this chrome (they still
disable any future nonessential motion).

### 4.2 Account list

Accounts stay in snapshot order inside each group. Groups use
`Group.display_name` as a gold section header (`Claude Code`, `Codex`).
Headers are not selectable; `j`/`k` moves only between accounts. Do not
prefix rows with `Provider /`.

Each row is one line: profile name on the left, a state chip on the right.

| Situation | Chip |
|---|---|
| `account.active` | gold `Active` |
| `account.needs_login` | terracotta `needs login` |
| else | muted `Saved` |

The selected row gets a 1-cell terracotta left spine and a `#1a2238`
wash. It is **not** a full terracotta fill. Keyboard `j`/`k` and arrows
are unchanged.

### 4.3 Hero inspector

Right pane, terracotta border, only on the wide layout.

**Title bar** (terracotta rule under it): profile name left, state right
(`● Active`, `needs login`, `Saved`).

**Identity:** `display_name` or `email` as the heading. Plan and provider
display name as gold pills. Omit a pill when the field is missing.

**USAGE:** one meter per `Window`. Label and percent on the first line;
a terracotta bar (`█` filled, `░` empty; ASCII `#` and `-`) on the
second; reset and age on a muted third line. `used_percent is None` draws
an empty muted bar and the word `unavailable`. Stale windows keep the
last bar and say `stale` plus `age_label`. Never invent a percent.

**SWITCHES:** one line per group surface — gold pill for `label`, muted
`detail` beside it (`Claude Code CLI`, `anthropic.claude-code`, …). If
`detail` is empty, show the pill only.

**Needs login:** a terracotta callout with `login_hint` when present,
instead of burying it in the table.

**Context line** (dashed rule, gold/terracotta keys):

| Situation | Line |
|---|---|
| Selected is active | `Already active · m for actions · running sessions keep their login` |
| `needs_login` | `l to log in · cannot switch until this account is signed in` |
| else | `Enter to switch · m for actions` |

The inspector reads only snapshot fields. It does not compute dates or
open stores.

### 4.4 Footer

Always visible when the terminal is not `too-short`. Primary actions
match the Tk footer (Add, Eject) plus Switch, which the window puts on
each card:

`j/k move · ⏎ switch · a add · x eject · m menu · l login · r refresh · ? help · q quit`

Terracotta keys, gold separators. On compact widths, drop `j/k`, `l`,
and `r` from the footer (they remain in `?`) so Switch / Add / Eject /
menu still fit.

**`a` Add** opens the same overlay the window’s Add Account dialog uses:
pick a provider, type a profile name, then the existing add + vendor
login flow. Preselect the selected account’s provider when there is
one; otherwise the first available provider. The account menu’s `a`
stays as an alias for the same overlay.

**`x` Eject** is the existing eject plan and confirm. Show it on the
footer even when the list is empty.

**`Enter` Switch** is unchanged.

### 4.5 Responsive behaviour

Breakpoints stay 78 / 48 cells, decided in Python (`variant_for` plus a
height check). Do not duplicate those numbers in TCSS.

| Conditions | Composition |
|---|---|
| width ≥ 78 and height ≥ 24 | lockup + list + inspector + footer |
| width ≥ 48, or wide-but-short | compact header + list with **inline** inspector under the selected row + footer |
| width < 48 | compact header + stacked list/inline inspector, no decoration extras |
| height < 16 | existing “too small” message, quittable |

Inline inspector is a shortened hero: title, identity, plan pill, one
usage meter (the first window), login callout if needed. Surface details
and extra meters wait for the wide pane.

Empty snapshot: no list, no inspector. Same lockup rules as the
dashboard, plus:

```text
No saved accounts yet.

a add · x eject · r refresh · ? help · q quit
```

Empty welcome still has no selected account, so `m` and `Enter` stay
no-ops. `a` works anyway: the add overlay lists providers from the
snapshot groups (the same choice the window’s footer button offers).

---

## 5. Overlays

Centered modal, pane fill `#11182b`, dimmed navy around it. Title bar in
terracotta; body in cream; shortcut line at the bottom.

| Screen | Border | Title |
|---|---|---|
| Help, menu, name input, add, successful result, login progress | gold | action name |
| Confirm, failed result | terracotta | the plan prompt or error |

Body copy stays the service’s `prompt`, `summary`, `error.message`,
`error.recovery`, and `warnings`. The overlay does not paraphrase safety
text.

Result after a successful switch still offers launch when the service
result allows it:

```text
Enter  launch <provider> here
Esc    accounts
q      quit
```

Login progress: same panel, scrolling sanitized log, `Esc` cancels.

**Add** is a gold overlay with a provider list and a name field (the
window’s Add Account dialog). `j`/`k` move the provider, typing goes to
the name, `Enter` submits, `Esc` cancels. Unavailable providers are
shown muted, not omitted.

Dialogs never include the six-line wordmark.

---

## 6. What does not move

- Mutation gating and “one mutation at a time”.
- Shortcut meanings, except `a` is also bound on the dashboard (not
  only inside the account menu).
- Enter on the active account is still a no-op.
- Disk remains authoritative; the TUI still re-renders from a fresh
  snapshot after every mutation.
- Credential material never appears in UI, logs, or snapshots.
- `theme.py` (Tk) is out of scope.

---

## 7. Testing

Update the existing pytest-textual-snapshot fixtures and add coverage for:

1. Wide dashboard with the README lockup, grouped list, spine selection,
   and hero inspector (healthy + `needs_login` accounts).
2. Wide-but-short: compact header, no broken lockup.
3. Medium and compact: inline shortened hero, no right pane.
4. Empty welcome with the lockup (Unicode, ASCII, `NO_COLOR`) and `a` /
   `x` in the footer.
5. Help, confirm, successful-result, and Add (provider + name) overlays.
6. `unicode=False`: ASCII lockup chips and `+ - |` frames.

Unit tests keep asserting navigation and resize behaviour. Snapshot
review uses `--snapshot-update` after a visual check. No test reads a
real home or a real vendor login.

---

## 8. Files

Expected touch list (implementation may split further):

- `shambles/app/tui/brand.py` — framed README lockup composition; compact
  fallback unchanged
- `shambles/app/tui/theme.tcss` — palette, pane chrome, overlay chrome,
  footer
- `shambles/app/tui/dashboard.py` / `widgets.py` — grouped list, hero
  inspector, footer
- `shambles/app/tui/application.py` / `overlays.py` / `workflows.py` —
  overlay title bars; empty welcome copy; top-level `a` add overlay
  (provider + name)
- `tests/tui/test_snapshots.py` and fixtures — visual gate
- `tests/tui/test_dashboard.py`, `test_brand.py`, `test_application.py` —
  lockup height gate, grouping, inspector fields

---

## 9. Decisions already made

- Richer visual language, not a quieter Tk port.
- Keep terracotta / gold / navy.
- Whole TUI in one pass (dashboard, empty welcome, every overlay).
- Grouped two-pane “command center”, not a stacked inspector.
- Full README framed lockup on the wide header, not letter-rows alone.
- Hero inspector, not a spec-sheet or meters-first pane.
- Footer exposes Switch, Add, and Eject like the Tk window; empty
  welcome can Add.
