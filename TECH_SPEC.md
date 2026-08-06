# Shambles — Technical Specification

Architectural reference for the Claude Code account switcher.

| | |
|---|---|
| **Version** | 1.0 (post-redesign) |
| **Target** | Claude Code 2.1.x — CLI and VS Code extension |
| **Platforms** | Linux and WSL2 confirmed. Windows unverified — see §1.11. macOS unsupported |
| **Runtime** | Python 3.10+, Tkinter. No third-party dependencies |
| **Source** | ~1,800 lines across 13 modules |
| **Tests** | 169 cases, all passing on Linux and Windows |

---

## 1. System Architecture

### 1.1 The problem

Claude Code resolves its configuration to `~/.claude` and its machine config to
`~/.claude.json`. Neither path is configurable in a way that helps: the VS Code
extension host does not inherit shell environment variables, so `CLAUDE_CONFIG_DIR`
is invisible to it. There is no supported multi-account mode.

The naive fix — re-running `/login` per account — costs an email verification
round trip every switch.

### 1.2 What actually gates re-authentication

Email verification is the **initial OAuth grant only**. Continued access depends
on the refresh token in `.credentials.json`:

```
claudeAiOauth.accessToken             ~8 hour lifetime, refreshed silently
claudeAiOauth.refreshToken            the credential that avoids the email
claudeAiOauth.expiresAt               epoch ms
claudeAiOauth.refreshTokenExpiresAt   epoch ms — rolling; width varies, read it
claudeAiOauth.scopes / subscriptionType / rateLimitTier
```

Preserving that file per account makes every subsequent switch instant. An
account returns to the email flow only after the refresh window lapses, since
each use re-mints it.

**The window width is not a constant and must not be hardcoded.** Measurements
recorded in [token-storage.md](docs/token-storage.md) differ by an order of
magnitude — ~28 days across three blobs on Linux/Team, ~4 days on a single
macOS/Max 5x sample. Which variable moves it is unresolved.
`profiles.refresh_expiry_ms()` reads `refreshTokenExpiresAt` out of the blob
rather than deriving it, so the countdown is correct under either regime. The
**rolling** property is confirmed by both samples and is what matters: an
account in regular use never approaches its deadline.

**Shambles never rotates, refreshes, decodes or transmits a token.** It moves
bytes on a local filesystem. All token lifecycle management remains Claude
Code's.

### 1.3 Scope: what is account-scoped

The central design decision, and the one the original implementation got wrong.

| State | Scope | Rationale |
|---|---|---|
| `~/.claude/.credentials.json` | **account** | The OAuth grant itself |
| `oauthAccount` in `~/.claude.json` | **account** | Identity: email, org, `accountUuid` |
| `cachedUsageUtilization` | **account** | Keyed by `accountUuid`; foreign copies show wrong figures |
| `~/.claude/projects/` | machine | Keyed by **project path**, not by account |
| `~/.claude/plugins/`, `file-history/`, `todos/`, `shell-snapshots/`, `session-env/`, `plans/` | machine | Workspace state |
| `~/.claude/settings.json`, `history.jsonl` | machine | User preferences, prompt history |
| `projects`, `mcpServers`, `machineID` in `~/.claude.json` | machine | Trust decisions and machine identity |

Exactly **two keys and one file** are account-scoped. Everything else is
machine-scoped and must remain shared, because that is how stock Claude Code
behaves: one `~/.claude`, one history, regardless of who is signed in.

### 1.4 Mechanism: targeted replace, not root symlink

**Superseded design (pre-1.0).** `~/.claude` was a symlink retargeted between
`~/.claude-profiles/<Name>/`, each holding a full copy of the directory:

```
~/.claude -> ~/.claude-profiles/Admin/
   Admin/projects/      24 sessions
   Ian-Work/projects/    4 sessions      <- invisible while Admin is active
```

Because `projects/` lived *inside* the swapped directory, switching accounts
also switched session history. Transcripts did not disappear — they became
unreachable, which is worse, because the failure is silent. A user reported it
as data loss.

The design also carried structural cost: an atomic symlink-swap dance, a Windows
`MoveFileEx` workaround (it refuses to replace an existing directory link), a
foreign-link safety state, VS Code lock-file migration between profiles, and a
filesystem-boundary warning for cross-device moves.

**Current design.** `~/.claude` is an ordinary directory. It is never moved,
replaced, renamed or deleted. A switch performs exactly three writes:

```
1.  ~/.claude/.credentials.json          <- copied from the target profile
2.  oauthAccount + cachedUsageUtilization in ~/.claude.json   <- spliced
3.  ~/.claude-profiles/active            <- marker updated
```

Each credential write is a same-directory temp file followed by `os.replace`:

```python
def once():
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".shambles-tmp")
    shutil.copyfile(source, tmp)
    os.chmod(tmp, 0o600)
    os.replace(tmp, dest)
```

`os.replace` is atomic on POSIX (`rename(2)`) and on Windows (`MoveFileEx` with
`MOVEFILE_REPLACE_EXISTING`). Guarantees:

- **No partial credential file is ever observable.** A reader sees the old
  complete file or the new complete file.
- **No window where the file is absent.** Unlike the old symlink path, which had
  to unlink before creating on Windows.
- **The mode is set on the temp file before the rename**, so the file is never
  briefly world-readable at its final path.
- **A running process is unaffected** — see §4.3.

`~/.claude.json` is deliberately *never* replaced wholesale. Claude Code owns
that file and rewrites it continuously; Shambles parses it, mutates two keys,
and writes it back atomically, preserving all other keys and their original
order.

### 1.5 Directory layout

```
~/.claude/                        real directory — SHARED by every account
  .credentials.json               the live login          (swapped, mode 600)
  projects/                       session history         (never touched)
  plugins/  file-history/  todos/  shell-snapshots/
  session-env/  plans/  ide/  sessions/  statsig/
  settings.json  history.jsonl                            (never touched)

~/.claude.json                    machine config — two keys spliced

~/.claude-profiles/               mode 700
  active                          name of the live profile
  <Name>/                         mode 700
    credentials.json              that account's tokens   (mode 600)
    account.json                  oauthAccount + cachedUsageUtilization
  .shambles-backups/
    claude.json.<epoch_ms>        last 10 snapshots
```

A profile is roughly **500 bytes**. Under the previous design it was 208 MB.

### 1.6 Module structure

| Module | Lines | Responsibility |
|---|---|---|
| `paths.py` | 113 | Every path, derived from an injectable home root |
| `state.py` | 109 | Which account is live; six-state classification |
| `switcher.py` | 194 | Switch, save, add, rename |
| `configjson.py` | 145 | Parse, splice and back up `~/.claude.json` |
| `profiles.py` | 172 | Discovery, token state, expiry arithmetic, name validation |
| `migrate.py` | 219 | One-way conversion from the pre-1.0 layout |
| `retry.py` | 36 | Transient-lock retry |
| `errors.py` | 46 | Typed exceptions carrying user-facing text |
| `gui.py` | 430 | Tkinter window |
| `theme.py` | 131 | Palette, fonts, DPI scaling |

`Path.home()` is called in exactly one place — `Paths.real()` — so the entire
application can be pointed at a temporary directory under test.

### 1.7 State model

There is no symlink to inspect. The active profile is recorded in
`~/.claude-profiles/active` and then **verified** against the identity actually
present in `~/.claude.json`:

| State | Condition | UI |
|---|---|---|
| `MANAGED` | Marker names a profile; live identity agrees | Normal |
| `UNMANAGED` | No profiles exist | Offer *Save Current Account* |
| `UNKNOWN` | Profiles exist, no marker | Offer *Save Current Account* |
| `MISSING_PROFILE` | Marker names a deleted profile | Offer *Forget that profile* |
| `DRIFTED` | Live identity ≠ the marked profile's | Warn with both addresses |
| `LEGACY_LAYOUT` | `~/.claude` is still a symlink | Auto-repair on startup |

`DRIFTED` exists because a user can run `/login` outside Shambles. Reporting the
discrepancy is strictly better than displaying a confidently wrong account name.

A profile that has never been logged into carries no stored identity, so it has
no expectation to violate and is not treated as drift.

### 1.8 Environment override

`CLAUDE_CONFIG_DIR` relocates Claude Code's entire config tree — config,
credentials and `projects/` alike. A shell exporting it reads a tree Shambles
never touches, so switches silently have no effect there.

`state.config_dir_override()` resolves the variable and compares it against the
managed directory, returning `None` when unset, empty, or pointing at
`~/.claude` itself. A non-`None` result renders a persistent banner naming the
target.

The effect is CLI-only. The VS Code extension host does not inherit shell
environment variables — the same fact that makes this tool necessary.

### 1.9 Eject

The failure mode being prevented: a user removes Shambles by deleting
`~/.claude-profiles/`, destroying every stashed refresh token. Each is
recoverable only through a new verification email.

`eject.run()`:

1. Ensures `~/.claude` is signed in — if the live credentials are absent but
   the active profile has a copy, restores it via the same atomic
   temp-then-`os.replace` used elsewhere.
2. Removes only Shambles' bookkeeping: the `active` marker and any legacy
   `.shambles.json`.
3. Leaves every profile directory intact and reports where they are.

Idempotent, and refuses on the legacy layout — ejecting a symlinked
`~/.claude` would leave a dangling link.

Nothing in eject deletes a credentials file.

### 1.11 Platform reach is narrower than the build matrix suggests

Shambles swaps `~/.claude/.credentials.json`. That file is not where Claude Code
keeps credentials on every platform. Per source analysis of the shipping bundle
([token-storage.md](docs/token-storage.md)), the binary defines **three**
backends:

| Platform | Backend | Store |
|---|---|---|
| Linux / fallback | `plaintext` | `$CLAUDE_CONFIG_DIR/.credentials.json`, mode 0600 |
| macOS | `keychain` | Keychain generic password, service name **computed** from a hash of the config dir |
| Windows | `windows-credman` | Credential Manager, values **chunked** at 2000 chars |

Consequences for this codebase:

- **Linux and WSL2 — confirmed working.** The plaintext backend is the one
  Shambles manipulates, verified in daily use on the development host.
- **Windows — unverified, and likely non-functional.** If Claude Code uses
  Credential Manager there, `~/.claude/.credentials.json` never exists, so
  `save_current_account` would report nothing to save and a switch would move a
  file no reader consults. CI builds and tests a Windows binary, which proves
  the *app* runs — not that account switching works. Supporting Windows
  properly means a Credential Manager backend that reassembles chunked entries,
  which does not exist.
- **macOS — unsupported, correctly.** The Keychain is the sole store; there is
  no file to swap. Any future support must compute
  `` `Claude Code${suffix}-credentials${dirHash}` `` rather than hardcode it.

The Windows and macOS rows are graded [SRC] in the source document — read out of
the shipping bundle on a macOS host, not executed on Windows. The Linux row is
the only one this project has exercised.

### 1.10 Migration from the legacy layout

Repair is **automatic on startup**, not offered as a choice. The old layout hid
session history; there is no configuration of that anyone wants, and presenting
it as an option would leave users running the broken arrangement until they
happened to notice a button. The merge is purely additive, so there is nothing
to undo.

```
1. Rank profiles by session count; the richest becomes the base for ~/.claude.
2. Merge every other profile's machine-scoped directories into the base,
   skipping any file already present. Never overwrites.
3. Merge history.jsonl line-wise, dropping exact duplicates.
4. Read each profile's credentials and identity out of the old locations.
5. Replace the symlink with the real merged directory — guarded, restoring the
   symlink if the rename fails.
6. Remove Shambles' own .shambles.json so ~/.claude is indistinguishable from
   a stock install.
7. Write the slim profile store and the active marker.
```

Nothing is deleted. Old profile directories are left on disk for the user to
remove once satisfied.

Step 5 is the only non-atomic moment in the system. `rename(dir, symlink)` fails
with `ENOTDIR` on POSIX, so the symlink must be unlinked first. Both operations
are metadata-only and the window is microseconds, but it is real — which is why
migration should run with no Claude Code sessions active.

---

## 2. Concurrency & Lock Handling

### 2.1 The contention model

Shambles has no locking relationship with Claude Code. They are independent
processes writing to overlapping paths:

- Claude Code rewrites `~/.claude.json` on its own schedule.
- Claude Code rewrites `.credentials.json` on silent token refresh.
- Antivirus scanners and the Windows Search indexer open files opportunistically.

Contention is therefore expected, not exceptional, and must be survivable rather
than prevented.

### 2.2 `retry.py`

```python
RETRIES = 3
DELAY = 0.5                 # seconds
WINDOWS_SYMLINK_DENIED = 1314

def with_retry(action, what, *, retries=RETRIES, delay=DELAY, sleep=time.sleep):
    last = None
    for attempt in range(retries):
        try:
            return action()
        except OSError as exc:
            if getattr(exc, "winerror", None) == WINDOWS_SYMLINK_DENIED:
                raise SymlinkPermissionError(WINDOWS_SYMLINK_HELP) from exc
            last = exc
            if attempt < retries - 1:
                sleep(delay)
    raise SwitchFailedError(
        f"Could not {what} after {retries} attempts:\n{last}\n\n"
        "Close any running Claude Code sessions and try again."
    ) from last
```

Design notes:

- **`OSError` is the catch, not `PermissionError`.** Windows surfaces sharing
  violations under several errnos; the base class covers them.
- **`ERROR_PRIVILEGE_NOT_HELD` (1314) fails immediately.** No amount of waiting
  grants an account the right to create symlinks. Reached only via the legacy
  migration path.
- **Exhaustion raises `SwitchFailedError`**, a `ShamblesError` subclass. This is
  load-bearing — see §2.4.
- **`sleep` is injected** so the suite never actually waits.
- Worst case latency: 3 attempts, 2 sleeps, ~1.0 s.

### 2.3 `_copy_secret`

```python
def _copy_secret(source: Path, dest: Path, *, sleep=time.sleep) -> None:
    def once():
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".shambles-tmp")
        shutil.copyfile(source, tmp)
        os.chmod(tmp, 0o600)
        os.replace(tmp, dest)
    retry.with_retry(once, f"write {dest.name}", sleep=sleep)
```

The whole operation retries, not just the copy. If `os.replace` loses to a
concurrent writer, the next attempt rebuilds the temp file from scratch — no
stale intermediate is reused. The temp file lives in the destination directory
so the rename never crosses a filesystem boundary.

### 2.4 Single-guard invariant

Every filesystem operation in `switch()` is inside one `try`:

```python
try:
    retry.with_retry(lambda: configjson.backup(...), "back up ~/.claude.json", sleep=sleep)
    if current.profile and paths.profile_dir(current.profile).is_dir():
        stash_live_login(paths, current.profile, now_ms_fn=lambda: stamp, sleep=sleep)
    paths.claude_dir.mkdir(parents=True, exist_ok=True)
    if incoming.exists():
        _copy_secret(incoming, paths.live_credentials, sleep=sleep)
    else:
        paths.live_credentials.unlink(missing_ok=True)
except OSError as exc:
    raise SwitchFailedError(
        f"Could not update the login in ~/.claude:\n{exc}\n\n"
        "Close any running Claude Code sessions and try again.") from exc
```

This invariant is not cosmetic. The GUI's error boundary catches
`ShamblesError` **only**:

```python
def _guarded(self, action):
    try:
        action()
    except ShamblesError as exc:
        messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
    finally:
        self.refresh()
```

A bare `OSError` escaping `switch()` propagates into the Tk callback, prints a
traceback to stderr, and shows the user **nothing** — a switch that appears to
have silently done nothing. QA found three such escapes: `configjson.backup`
(`shutil.copy2` internally), the outgoing `stash_live_login`, and the retry-less
credential copy. All are now inside the guard.

### 2.5 Ordering and failure semantics

```
1. Classify state                     read-only
2. Verify target profile exists       read-only
3. Parse ~/.claude.json               ABORT if unreadable — see §2.6
4. Back up ~/.claude.json             retried
5. Stash the outgoing login           retried
6. Install the incoming login         retried
7. Splice the identity                atomic
8. Update the active marker           last
```

Two properties follow:

- **The marker moves last.** A failure at any earlier step leaves the marker on
  the previous profile, so the UI never claims a switch that did not happen.
- **The outgoing login is stashed before the incoming one is installed.**
  Switching away can never strand an account.

### 2.6 Config-clobbering defence

`configjson.load()` returns `{}` for anything unparseable — correct for merely
displaying a profile's email, catastrophic on the write path. Splicing two keys
onto that `{}` and writing it back would replace the entire config: every
project trust decision, MCP server and machine ID.

`~/.claude.json` is ~61 KB on a typical machine with 15 projects and is rewritten
by Claude Code continuously, so a read landing mid-write is plausible rather
than theoretical.

The write path therefore distinguishes *absent* from *unreadable*:

```python
def load_for_write(path) -> dict:
    if not path.exists() or path.stat().st_size == 0:
        return {}                       # fresh machine — fine
    try:
        config = json.load(path.open(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigUnreadableError(...) from exc
    if not isinstance(config, dict):
        raise ConfigUnreadableError(...)
    return config
```

`switch()` calls it as a **pre-flight, before anything moves**. Aborting later
would be worse than useless: the login would be installed while the marker still
named the old profile, and a retry would short-circuit on "already there".

Every write to `~/.claude.json` is preceded by a snapshot into
`.shambles-backups/`, retained 10 deep.

---

## 3. Security & File Permissions

### 3.1 Enforced model

| Path | Mode | Enforced by |
|---|---|---|
| `~/.claude-profiles/` | `0700` | `Paths.ensure_store()` |
| `~/.claude-profiles/<Name>/` | `0700` | `Paths.ensure_profile()` |
| `~/.claude-profiles/<Name>/credentials.json` | `0600` | `_copy_secret` |
| `~/.claude-profiles/<Name>/account.json` | `0600` | `configjson.write_atomic` |
| `~/.claude/.credentials.json` | `0600` | `_copy_secret` |
| `~/.claude-profiles/active` | default | Contains only a profile name |

Modes are applied to the **temp file before the rename**, never to the file at
its final path. There is no window in which a credentials file exists
world-readable.

### 3.2 The umask defect

The redesign introduced a regression. Directory creation used plain `mkdir`:

```python
paths.profiles_dir.mkdir(parents=True, exist_ok=True)      # defective
paths.profile_dir(name).mkdir(parents=True, exist_ok=True) # defective
```

`mkdir` requests `0777` and lets the process umask subtract from it. Under the
standard `022`, that yields `0755` — world-readable, world-traversable
directories holding OAuth refresh tokens. Observed on a real installation:

```
drwx------  ~/.claude-profiles          (700 — inherited from the old layout)
drwxr-xr-x  ~/.claude-profiles/Admin    (755 — created by migrate.py)
-rw-------  ~/.claude-profiles/Admin/credentials.json
```

Tokens were not exposed: the files were `0600`, and the parent happened to be
`0700` because the *previous* implementation had set it. Both were accidents of
history rather than properties of the code.

The fix routes every creation path through two helpers:

```python
def ensure_store(self) -> Path:
    self.profiles_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(self.profiles_dir, 0o700)
    except OSError:
        pass
    return self.profiles_dir

def ensure_profile(self, name: str) -> Path:
    self.ensure_store()
    directory = self.profile_dir(name)
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory
```

`chmod` after `mkdir` rather than `mkdir(mode=...)`: the latter is also subject
to umask, and the explicit call additionally **repairs** directories left loose
by an earlier version. No raw `mkdir` on a profile path remains in the codebase.

### 3.3 Platform caveats

**Linux / WSL2.** POSIX modes apply as written. `0700` on the store means no
other local user can traverse it even if a child were left loose — defence in
depth behind the `0600` files.

**Windows.** `os.chmod` cannot express POSIX modes. CPython maps it to the
read-only attribute only; `0700` and `0600` are silently approximated. The
`try/except OSError: pass` is therefore not defensive padding — it is the
expected path on Windows. Credentials there rely on the user profile's own ACLs,
which is precisely the protection Claude Code's own `.credentials.json` receives.
Shambles does not weaken the Windows posture; it does not strengthen it either.

Implementing real Windows ACLs would require `pywin32` or shelling out to
`icacls`, contradicting the zero-dependency constraint for a threat model
(hostile local user on a single-user developer machine) that does not justify it.

**macOS.** Unsupported. Credentials live in the system Keychain, not in
`.credentials.json`, so there is no file to swap.

### 3.4 Other properties

- **No token is ever logged, printed or transmitted.** Credential contents are
  copied byte-for-byte and never parsed except to read `refreshTokenExpiresAt`
  and test `accessToken` for presence.
- **Profile names are validated** against `/ \ : * ? " < > |`, the union of
  POSIX and Windows illegal characters, preventing path traversal via a name.
- **Deletion is minimal and exhaustively enumerable.** Five `unlink` calls exist
  in the entire codebase; there is no `rmtree` and no delete-profile button:

  | Site | Target | When |
  |---|---|---|
  | `configjson.py:137` | `claude.json.<ms>` snapshot | Pruning past 10 |
  | `switcher.py:113` | live `.credentials.json` | Switching to a never-logged-in profile |
  | `state.py:51` | `active` marker | *Forget that profile* |
  | `migrate.py:196` | the legacy `~/.claude` symlink | Migration, restored on failure |
  | `migrate.py:207` | stale `.shambles.json` | Migration |

  None targets session history, and a lapsed credentials file is never removed —
  see §4.1.

---

## 4. Token Lifecycle & Edge Cases

### 4.1 Expiry is surfaced, never enforced

Each profile row carries a countdown chip derived from
`claudeAiOauth.refreshTokenExpiresAt`:

| Chip | Severity | Token state | Warning |
|---|---|---|---|
| `28d` | ok | `ok` | — |
| `4d` | soon | `ok` | — |
| `today` | soon | `ok` | — |
| `expired 12d ago` | gone | `expired` | "Token expired — switch to this profile and run /login." |
| *(none)* + ⚠ | — | `missing` | "No token found. Switch to this profile and run 'claude' in terminal to login." |

`EXPIRY_WARN_DAYS = 7`. Day counts use `math.floor`, so a token twelve hours past
its window reads "expired 1d ago" rather than "today". Hovering a chip gives the
absolute date and an explanation of the rolling window.

**Switching to a lapsed profile is not an error.** It succeeds. Shambles does not
validate tokens against the server and does not gate on the local clock.

### 4.2 Clock-drift rationale

Blocking a switch on a locally-computed expiry would mean trusting the system
clock. WSL2's clock can jump when Windows resumes from sleep. A drifted clock
would mark a perfectly good refresh token dead, and a hard block would then cost
the user a real verification email — the exact cost this tool exists to avoid.

The asymmetry is decisive: **a wrong label is recoverable; a refused switch or a
deleted refresh token is not.** So Shambles labels and proceeds. Claude Code then
fails its own refresh against the authoritative server clock and prompts
`/login`, which overwrites the file anyway.

For the same reason, lapsed credentials files are never deleted. Their presence
is what lets the UI distinguish "expired twelve days ago" from "never logged in
here".

### 4.3 Running sessions are unaffected

Verified on a live installation: no Claude Code process holds an open descriptor
on `.credentials.json` or `~/.claude.json`.

```
PID 502025:  no handle on credentials or .claude.json
PID 502153:  no handle
PID 524844:  no handle
PID 524867:  no handle
```

Claude Code reads credentials on demand and holds the token in memory. Because
`os.replace` swaps a directory entry, a running process is looking at neither
the new file nor a broken handle — it continues with the token it loaded at
startup. Corroborated by mtime: two sessions up 57 minutes, credentials
untouched since the switch 73 minutes earlier.

**A switch therefore takes effect for newly spawned instances only.**

| Context | Behaviour after a switch |
|---|---|
| New `claude` in a terminal | New account |
| Terminal tab already running | Old account until restarted |
| VS Code extension | Old account until *Developer: Reload Window* |

This is a feature as much as a constraint: two accounts can run concurrently in
different terminals.

### 4.4 Known edge case — the 8-hour access token

**Scenario.** A session outlives its ~8-hour access token *and* an account switch
occurred in the interim. Claude Code performs a silent refresh and may write the
refreshed tokens for the **previous** account into `.credentials.json`, which now
belongs to the account switched in.

**Detection gap.** `state.inspect()` compares `oauthAccount` in `~/.claude.json`
against the active profile's stored identity. A token refresh does not change
the account, so identity still agrees while the credential underneath is the
wrong one. The drift check does not fire.

Content comparison is not a viable substitute: Claude Code rewrites the file on
every legitimate silent refresh, so comparing the live file against the stored
copy would false-positive continuously. Both access and refresh tokens rotate,
so no stable field survives to compare.

**Recommended mitigation.** Close long-running sessions before switching. Already
documented in the README's *Adding an account* and *Switching* procedures. A
session started within the last few hours is not at risk.

**Recovery.** Benign and self-correcting. Switch to the affected profile and run
`/login` once. The refresh window reopens. No data is lost — session history is
not involved.

**Status.** Documented, not fixed. A robust fix would require either an
inotify-style watch on `.credentials.json` or a stable account discriminator
inside the file. Neither is justified by the exposure.

### 4.5 Independent lifecycle: Claude Code's own cleanup

Claude Code prunes sessions older than 30 days, recorded in
`~/.claude/.last-cleanup`. This is unrelated to Shambles and applies with or
without it. Users wanting longer retention should set `cleanupPeriodDays` in
`~/.claude/settings.json`. Worth stating explicitly because aged-out history is
easily mistaken for switching-related loss.

---

## 5. Test Coverage Summary

**147 cases from 122 functions**, all passing, ~1.3 s. The gap is
parametrisation in `test_profiles.py` and `test_shutdown.py`.

| Module | Functions | Focus |
|---|---|---|
| `test_profiles.py` | 24 | Discovery, token state, expiry arithmetic, name validation |
| `test_switch.py` | 23 | Switch, save, add, rename, lock handling, permissions |
| `test_migrate.py` | 21 | Legacy conversion, merge completeness, auto-repair |
| `test_configjson.py` | 17 | Splicing, atomic writes, corruption refusal, backups |
| `test_state.py` | 9 | Six-state classification |
| `test_gui_import.py` | 7 | Header text per state, full widget-tree render |
| `test_paths.py` | 7 | Path derivation, store permissions |
| `test_packaging.py` | 6 | Entry points, packaged-binary imports |
| `test_retry.py` | 4 | Retry, exhaustion, Windows privilege short-circuit |
| `test_shutdown.py` | 4 | Signal handling, tooltip teardown |

The suite uses no mocks for filesystem behaviour. Every test builds a real
directory tree under `tmp_path`, with `Paths.for_home()` redirecting the entire
application. Clocks are injected (`NOW = 1_785_000_000_000`); `sleep` is injected
so retry tests do not wait.

### 5.1 QA test plan results

Executed against a **210 MB copy of a production installation** (314 transcript
files, 171.7 MB of session history) rather than synthetic fixtures.

**Test 1 — Auth bypass.** *Pass, structural.* Both profiles carry live refresh
and access tokens; `~/.claude.json` identity tracks the swap correctly. Full
verification requires observing that no browser opens on `Developer: Reload
Window`, which cannot be automated here — and exercising a refresh token against
the live endpoint would rotate it. **This item requires manual confirmation.**

**Test 2 — Shared history.** *Pass.* Identical transcript sets visible under both
accounts across repeated switches.

**Test 3 — Non-destructive.** *Pass.* Ten consecutive switches in 0.04 s:

```
transcripts before/after : 314 / 314
deleted                  : 0
content changed          : 0   (SHA-256 per file)
mtime altered            : 0
unexpected new files     : 0
```

**Test 4 — Conflict & locks.** *Initially failed; fixed.* A transient lock
crashed with a bare `PermissionError`. Root cause in §2.4. After the fix:

```
~/.claude.json truncated mid-write   -> clean warning
~/.claude read-only                  -> clean warning
profile credentials unreadable       -> clean warning
transient lock (fails 2x)            -> recovered after 5 attempts
permanent lock (fails 99x)           -> clean warning after 3 attempts

marker after failures    : unchanged
transcripts still present: 314
```

**Test 5 — Pathing.** *Pass, with the §3.3 Windows caveat.* Note that the
POSIX-mode assertions in §3.1 are marked `posix_modes_only` and skip on
Windows; asserting them there failed CI for six consecutive commits until the
marker was added. All paths built via
`pathlib` operators; no hardcoded separators; `os.replace` atomic on both
platforms; Windows-illegal characters rejected in profile names. Shambles manages
whichever environment it runs in and deliberately does not bridge Windows↔WSL —
cross-boundary access breaks Claude Code's file operations and produces 9p
permission failures on a `0600` credentials file.

### 5.2 Defects found and fixed

| Defect | Impact | Commit |
|---|---|---|
| Session history partitioned per account | Weeks of transcripts unreachable after a switch | `0e2ba63` |
| `load()` returning `{}` on the write path | Entire `~/.claude.json` replaceable by two keys | `eef533b` |
| Migration offered as an opt-in button | Broken layout persists until noticed | `5a060e6` |
| `plugins/` and `history.jsonl` not merged | Second-account plugins and prompt history stranded | `33ece4e` |
| Bare `OSError` escaping `switch()` | Lock failures invisible to the user | `c851a2b` |
| No retry on credential writes | Transient locks failed the switch | `c851a2b` |
| umask-dependent directory modes | Token directories `0755` | `c851a2b` |

### 5.3 Coverage limitations

Stated explicitly rather than implied:

- **The browser-bypass claim is structural**, not observed end to end (§5.1).
- **The 8-hour refresh interaction is undemonstrated** (§4.4). Reproducing it
  requires an 8-hour session straddling a switch.
- **Windows account switching is unverified and probably broken** (§1.11). The
  CI Windows job proves the app starts and its tests pass; it does not exercise
  a real Claude Code login, because the runner has none. macOS is unsupported by
  design.
- **Migration ran once on real data**, verified complete afterwards. It is
  one-way; re-running is refused.
