# Changelog

Notable changes per release. Dates are the tag date.

## Unreleased

### Added

- **A terminal interface.** Running `shambles` on an interactive terminal now
  opens a keyboard-driven dashboard (`j`/`k` or the arrow keys to move,
  `Enter` to switch, `m` for the account menu, `l` to log in, `x` to eject,
  `?` for help) instead of requiring the Tk window. `shambles tui` opens it
  explicitly; `shambles gui` still opens the window; `shambles list` and
  `shambles switch` are unchanged and remain the scriptable, non-interactive
  path. See the README's "Terminal interface" section for the full shortcut
  list.
- **Same-terminal launch after switching.** From the terminal interface's
  result screen, choosing Launch hands the current terminal to the vendor CLI
  (`claude` or `codex`) in place — Textual exits and tears down first, then
  the vendor process replaces Shambles rather than running alongside it.
- **`--no-motion` and `NO_COLOR`** disable the terminal interface's onboarding
  box-draw animation; `NO_COLOR` is detected automatically, the same
  convention respected by most other terminal tools.
- **`SHAMBLES_NO_MOTION=1`** does the same as `--no-motion`, for scripts and
  session managers that set environment variables more easily than flags.

### Notes

- Bare `shambles` only opens the terminal interface when both stdin and
  stdout are attached to a real terminal. Anything else (a pipe, a script, a
  non-interactive shell) falls through to the usage message the same as
  before — this release adds no new implicit behaviour for non-interactive
  callers.
- The terminal interface goes through the same `ShamblesService` core as
  `shambles list`/`shambles switch`, and reads and writes exactly the same
  files the Tk window does — see "What it touches" in the README. The
  restart requirement is unchanged too: a Claude Code session already running
  keeps the login it loaded at startup, in a terminal or in VS Code, no
  matter which interface performed the switch.

## 2.0.0 — 2026-08-07

A redesign. Everything below happens automatically on first launch; there is
nothing to run and nothing to move.

### Breaking

- **`~/.claude` is no longer a symlink.** It is an ordinary directory that
  Shambles never moves, replaces or deletes. A switch now copies one file —
  `~/.claude/.credentials.json` — and splices `oauthAccount` in
  `~/.claude.json`.
- **Session history is shared across accounts again.** 1.0.0 swapped the whole
  of `~/.claude`, so `projects/` went with it and every account had its own
  history. Transcripts were never deleted, but they became unreachable while
  another account was active, which reads as data loss. Claude Code keys history
  by project path, not by account, and now Shambles leaves it alone.
- **Profiles are ~500 bytes instead of 208 MB.** They hold a credentials file
  and an identity, nothing else.
- **First launch migrates the old layout**, merging every profile's `projects/`,
  `plugins/`, `file-history/`, `todos/`, `shell-snapshots/`, `session-env/`,
  `plans/` and `history.jsonl` into one shared directory. Nothing is
  overwritten and nothing is deleted; the old profile folders stay on disk for
  you to remove. Run it with no Claude Code sessions open.
- An older Shambles cannot read the new layout. Downgrading after upgrading is
  not supported.

### Added

- **Session and weekly usage** on every card, as bars. Red at 80%, matching the
  VS Code extension's own meter. The active account shows live figures; others
  show their last known values with an age attached, never anything newer.
- **Eject** — hands `~/.claude` back as a stock Claude Code install, still
  signed in, and removes only Shambles' own bookkeeping. Exists because the
  obvious way to uninstall — deleting `~/.claude-profiles/` — destroys every
  stored refresh token.
- **Remove profile** — a per-card control for inactive accounts only, with a
  confirmation naming the account and what it costs.
- **Refresh** — re-reads the figures on disk. Local files only; no network call
  and nothing a running Claude Code session can notice.
- **A warning when `CLAUDE_CONFIG_DIR` is set**, which silently points the CLI
  at a config tree Shambles never touches.
- `SECURITY.md`, and `SHAMBLES_SCALE` for overriding UI scaling.

### Fixed

- **A failed switch could destroy the account it switched away from.** If the
  identity splice failed after the login was installed, the active marker still
  named the outgoing profile, and the next refresh copied the incoming login
  over that profile's stored token.
- **Writing onto an unreadable `~/.claude.json` replaced the whole file.** A
  parse failure yielded `{}`, which was then spliced and written back, losing
  every project, MCP server and machine ID. The write path now refuses.
- **A stale usage cache was restored on every switch**, so the VS Code meter
  displayed hours-old figures as current.
- **The active account was the only one guaranteed to show no usage** — a
  profile learned its figures only when switched away from.
- **Refresh tokens rotate**, so a profile's stored login went stale within hours
  of becoming active. It is now re-synced while the account is in use.
- **A locked file escaped as a bare `OSError`**, which the window could not
  render, so a switch appeared to do nothing. Credential writes and the config
  backup are retried.
- **The profile store was created world-traversable** under the usual umask.
  Now `0700`, with credentials `0600`.
- Migration skipped `plugins/` and `history.jsonl`.
- Tooltips could stack on screen, fired from anywhere on a usage row, and ran
  off the display near the right edge.
- Icon glyphs missing from the system font rendered as boxes; they are now
  chosen at runtime from what the font can draw.
- Window layout: the footer claimed a column beside the cards, the card list
  had no scrollbar and grew past the screen, and long profile names stretched
  the window instead of eliding.
- Body text was below the 16px accessibility floor.

### Known limitations

- **Windows account switching is unverified.** Claude Code appears to use the
  Credential Manager there rather than a credentials file, in which case
  switching would quietly do nothing. The binary builds and runs; nobody has
  confirmed a switch takes effect. See `docs/token-storage.md`.
- **macOS is unsupported** — credentials live in the Keychain, so there is no
  file to swap.
- A session already running keeps the token it loaded at startup. Start a new
  one, or reload the VS Code window.

## 1.0.0 — 2026-08-05

First tagged release. Swapped `~/.claude` as a symlink between profile
directories — superseded by 2.0.0, which shares session history instead of
partitioning it.
