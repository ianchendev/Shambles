# Shambles — Design

**Date:** 2026-08-05
**Status:** Approved for planning

A lightweight Tkinter utility that switches the active `claude-code` account by
swapping an OS-level symlink at `~/.claude`, so both the CLI and the VS Code
extension pick up the change without environment variables.

---

## 1. Problem

Claude Code hardcodes its configuration path to `~/.claude` (`%USERPROFILE%\.claude`
on Windows). Environment variables cannot redirect it, because the VS Code extension
host process ignores them. Running more than one account therefore means physically
changing what that path resolves to.

## 2. Investigation findings

Established by read-only inspection of a live Claude Code 2.1.220 install on
WSL Ubuntu.

### 2.1 The token

`~/.claude/.credentials.json`, mode `600`:

```
claudeAiOauth.accessToken            str
claudeAiOauth.refreshToken           str
claudeAiOauth.expiresAt              int   (epoch ms)
claudeAiOauth.refreshTokenExpiresAt  int   (epoch ms)
claudeAiOauth.scopes                 list[5]
claudeAiOauth.subscriptionType       str
claudeAiOauth.rateLimitTier          str
```

This file contains **no email**. It is the authoritative login identity — swapping
it is what actually changes accounts.

### 2.2 The email

`~/.claude.json` — note this sits **outside** `~/.claude/` — under `oauthAccount`:

```
emailAddress       str     <- the field the UI needs
displayName        str
accountUuid        str
organizationUuid   str
organizationName   str
organizationType   str     e.g. "claude_team"
seatTier           str     e.g. "team_standard"
billingType        str
profileFetchedAt   int     (epoch ms — proves this is a refreshable cache)
```

`profileFetchedAt` shows `oauthAccount` is a cache that Claude Code re-fetches from
the API using the current token. It is not the source of truth, but it is what the
UI can read, and a stale value is user-visibly wrong.

The same file also holds machine-scoped state that is **not** account-specific:
`projects` (per-directory trust flags, MCP servers, prompt history), `userID`,
`machineID`, `numStartups`, `skillUsage`, `pluginUsage`, feature caches.

### 2.3 The rescue hatch

Claude Code snapshots `~/.claude.json` to
`~/.claude/backups/.claude.json.backup.<epoch_ms>` on every write. Five were present
during investigation. Because `backups/` lives **inside** the swappable directory,
every profile folder carries its own historical copy of `oauthAccount.emailAddress`.

This means a profile's email is recoverable even if Shambles never stashed it, so
**no manual email-entry fallback is required**.

### 2.4 Environment

- Claude Code 2.1.220, WSL only. `/mnt/c/Users/IanChen/` contains neither `.claude`
  nor `.claude.json` — there is no Windows-side install on this machine.
- Python 3.12.3. Neither `tkinter` nor `PyQt6` installed.
- WSLg is active (`DISPLAY=:0`, `WAYLAND_DISPLAY=wayland-0`), so a GUI will display.
- `~/.claude/settings.json` holds the permissions allowlist, `enabledPlugins`
  (superpowers, mongodb), `effortLevel: xhigh`, `tui: fullscreen`, `model`.

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Symlink `~/.claude`; splice only the `oauthAccount` key in `~/.claude.json` | Identity follows the profile while project trust, MCP servers and history stay shared. `~/.claude.json` is never a symlink, so a temp-file+rename write by Claude Code cannot clobber it. |
| D2 | Tkinter | One `apt` package, stdlib thereafter. No venv, no pip, fastest start under WSLg, no xcb platform-plugin failure mode. |
| D3 | The profile folder **is** the `.claude` directory | Matches the brief; one less nesting level. |
| D4 | Metadata sidecar inside each profile | Renaming a folder carries its metadata automatically. |
| D5 | `Add Empty Account` seeds `settings.json`, checkbox-controlled | A bare profile loses plugins, permissions and model prefs. Checked by default; uncheck for a clean slate. |
| D6 | No delete-profile feature | Not in scope, and `rmtree` on a folder holding live credentials is the one mistake worth designing out. |
| D7 | Never bridge WSL ↔ Windows | Cross-boundary symlinks break Claude Code's file operations and produce 9p permission problems on a `600` credentials file. |

## 4. On-disk layout

```
~/.claude-profiles/
  Work/                          <- a real .claude directory
    .credentials.json
    .shambles.json               <- sidecar: {"oauthAccount": {...}, "stashed_at": <ms>}
    settings.json
    backups/  projects/  plugins/  sessions/  ...
  Personal/
    ...
  .shambles-backups/             <- rolling copies of ~/.claude.json (last 10)

~/.claude       -> symlink -> ~/.claude-profiles/Work
~/.claude.json  -> REAL FILE, never symlinked
```

**The symlink is the single source of truth for which profile is active.** It is
never mirrored into a config field, so the UI cannot disagree with the filesystem.

Profile discovery lists non-dot directories directly under `~/.claude-profiles/`.
The leading dot on `.shambles-backups/` excludes it by the same rule.

## 5. Email and token resolution

### 5.1 Email chain, per profile, first hit wins

1. If this profile is **active** → `~/.claude.json` → `oauthAccount.emailAddress`
2. `<profile>/.shambles.json` → `oauthAccount.emailAddress`
3. Newest `<profile>/backups/.claude.json.backup.*` by filename timestamp →
   parse → `oauthAccount.emailAddress`
4. `None` → UI renders `unknown`

Every step tolerates missing files, unreadable permissions and malformed JSON by
falling through to the next.

### 5.2 Token state

| Condition | UI |
|---|---|
| `.credentials.json` missing, unreadable or unparseable, or `claudeAiOauth.accessToken` absent/empty | ⚠ tooltip: *"No token found. Switch to this profile and run 'claude' in terminal to login."* |
| `claudeAiOauth.refreshTokenExpiresAt` in the past | ⚠ tooltip: *"Token expired — switch to this profile and run /login."* |
| otherwise | no badge |

## 6. Operations

### 6.1 Switch A → B

```
0. guard    if B is already active -> no-op, return
1. stash    ~/.claude.json .oauthAccount        -> <A>/.shambles.json
2. backup   ~/.claude.json                      -> .shambles-backups/claude.json.<ts>
3. swap     os.symlink(abspath(B), ~/.claude.shambles-tmp, target_is_directory=True)
            os.replace(~/.claude.shambles-tmp, ~/.claude)
4. splice   <B>/.shambles.json .oauthAccount    -> ~/.claude.json
```

Symlink targets are always **absolute**. A relative target would resolve differently
depending on the process's working directory and would silently break if
`~/.claude-profiles/` ever moved.

Step 3 is **rename-onto-symlink**, atomic on POSIX: there is never an instant where
`~/.claude` does not exist. Unlink-then-symlink is rejected because a crash in that
window leaves the user with no config path at all.

Step 4 writes to a temp file in the same directory, `os.replace`s it into position,
then `chmod 600`. All other keys and their order are preserved (`json.load` into a
dict preserves insertion order on 3.7+).

If B has no stashed `oauthAccount`, the key is **deleted** from `~/.claude.json`
rather than left holding A's identity. Claude Code re-fetches it on next start.

Steps 3 and 4 retry 3× at 500 ms on `OSError`/`PermissionError` to absorb file locks.

Backup retention: keep the 10 newest in `.shambles-backups/`, prune the rest.

### 6.2 Save Current Account

The only operation that moves live data. Preconditions: `~/.claude` exists and is
**not** already a symlink.

```
validate name
mkdir -p ~/.claude-profiles/
warn if ~/.claude and ~/.claude-profiles are on different filesystems
shutil.move(~/.claude, ~/.claude-profiles/<Name>)
try:
    os.symlink(abspath(~/.claude-profiles/<Name>), ~/.claude, target_is_directory=True)
except OSError:
    shutil.move(~/.claude-profiles/<Name>, ~/.claude)   # rollback, then re-raise
stash ~/.claude.json .oauthAccount -> <Name>/.shambles.json
```

The rollback is mandatory. Without it a WinError 1314 after the move leaves the user
with no `~/.claude` at all.

The cross-filesystem warning matters because `shutil.move` silently degrades to
copytree+rmtree across devices — slow and non-atomic on a directory holding credentials.

### 6.3 Add Empty Account

```
validate name
mkdir ~/.claude-profiles/<Name>          mode 0700
if seed checkbox: copy <active>/settings.json -> <Name>/settings.json
switch to <Name>                         (§6.1; no sidecar, so oauthAccount is deleted)
show hint: "Run 'claude' in a terminal, then /login"
```

Only `settings.json` is copied. `.credentials.json` is never copied. Plugins arrive
via `enabledPlugins` in `settings.json` and are re-downloaded on first run.

### 6.4 Rename profile

Inline edit in the list. `os.rename(<old>, <new>)`, then — if the renamed profile was
active — immediately re-point `~/.claude` using the same atomic swap as §6.1 step 3,
because an absolute symlink target is left dangling by the rename.

### 6.5 Name validation

Reject: empty or whitespace-only; any of `/ \ : * ? " < > |`; `.` or `..`; a leading
dot; a name that already exists (case-insensitive, since the same tree may be reached
from Windows). Trim surrounding whitespace before validating.

## 7. Error handling

| Case | Behaviour |
|---|---|
| `OSError.winerror == 1314` | Dialog: *"Windows blocked symlink creation. Enable Developer Mode (Settings → System → For developers), or run Shambles as Administrator."* Any move already rolled back. |
| Dangling `~/.claude` symlink | Header shows ⚠ *Broken → \<missing target\>*. Offers re-point to an existing profile, or remove the dead link. |
| `~/.claude` is a symlink pointing outside `~/.claude-profiles/` | Refuse all operations, state the target. Treated as a foreign setup. |
| `~/.claude` missing entirely | Header shows *not set up*; only `Add Empty Account` is enabled. |
| File lock / `PermissionError` | 3 retries × 500 ms, then a dialog naming the failed step. |
| `~/.claude-profiles/` missing | Treated as zero profiles; created on first write. |
| Malformed JSON anywhere | Never fatal. Falls through the resolution chain; the profile still lists. |

Typed exceptions in `errors.py` carry a user-facing message; the GUI renders
`str(exc)` in a dialog and never leaks a traceback.

## 8. UI

A single non-resizable window, roughly 420×360.

```
┌─ Shambles ──────────────────────────────┐
│ ACTIVE  Work                            │
│ admin@cognitivo.com.au · Cognitivo      │
├─────────────────────────────────────────┤
│ ● Work                                  │
│   admin@cognitivo.com.au                │
│                                         │
│ ○ Personal              [   Switch   ]  │
│   ian@example.com                       │
│                                         │
│ ○ Client-A              [   Switch   ]  │
│   ⚠ no token found                      │
├─────────────────────────────────────────┤
│ [Save Current Account]  [Add Empty]     │
└─────────────────────────────────────────┘
```

- Header: active profile name, its email, org name. Or a ⚠ state per §7.
- Rows: radio-style active marker, editable name, email, optional ⚠ with tooltip.
  `Switch` appears only on inactive rows.
- `Save Current Account` is enabled only when `~/.claude` is a real directory.
- The whole list re-reads from disk after every mutation. No cached view state.

## 9. Modules

```
shambles/paths.py      environment detection, path resolution, injectable home root
shambles/profiles.py   discovery, email chain, token state, sidecar read/write
shambles/switcher.py   symlink swap, oauthAccount splice, retry, rollback, backups
shambles/errors.py     typed exceptions carrying user-facing messages
shambles/gui.py        tkinter window and dialogs
shambles.py            entrypoint
tests/                 pytest
```

Every core function takes the home root as a parameter. `paths.py` resolves the real
`Path.home()` only at the entrypoint. This is what lets the entire test suite run
against `tmp_path`.

## 10. Testing

pytest, every test against a synthetic `~` in `tmp_path`. **No test touches the real
`~/.claude`.**

Core cases:

- bootstrap: real dir → moved, symlinked, sidecar written
- bootstrap rollback: `os.symlink` patched to raise → directory restored intact
- switch: link re-points, A's `oauthAccount` stashed, B's spliced in
- switch to a profile with no sidecar: `oauthAccount` key deleted, not stale
- splice preserves every other key in `~/.claude.json` byte-for-byte
- email chain: each of the four steps in isolation, including backup-file fallback
- token states: missing, malformed, expired, valid
- dangling symlink detected and repairable
- foreign symlink target refused
- retry loop: raises twice then succeeds; raises 3× then surfaces the error
- name validation: each rejection class
- backup retention prunes to 10

GUI is smoke-tested only (constructs against a fake root, no display assertions).

## 11. Out of scope

- Deleting profiles (D6)
- Any WSL ↔ Windows bridging (D7)
- Copying `projects/`, `sessions/`, history or file-history between profiles
- Automating `/login` — the user runs `claude` themselves
- macOS Keychain, which stores credentials differently from `.credentials.json`

## 12. Verification note

The Windows code paths (`target_is_directory=True`, WinError 1314 handling) are
written to spec but **cannot be exercised on this machine** — there is no Windows-side
Claude Code install. The README will state this rather than imply they are verified.
