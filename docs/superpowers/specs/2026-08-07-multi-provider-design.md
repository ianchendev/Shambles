# Shambles — Multi-provider Design

**Date:** 2026-08-07
**Status:** ACTIVE — design agreed, not yet implemented

Extends Shambles from a Claude-only switcher to a two-provider one, adds a
provider choice to Add Account, and replaces the "go run this in a terminal"
handoff with a login that opens the browser from inside the app.

Supersedes nothing. Implements [DD-4](../../design-decisions.md#dd-4--provider-facts-are-data-adapters-are-two-thin-orthogonal-layers)
and amends [DD-2](../../design-decisions.md#dd-2--do-not-implement-login-inside-the-tool).

---

## 1. Problem

Three separate gaps, one change.

**Codex has the identical problem Shambles already solves.** `~/.codex/auth.json`
is a single file holding a single account, shared by the Codex CLI, the VS Code
extension `openai.chatgpt`, and Codex inside ChatGPT.app. Running two Codex
accounts means swapping that file, which is exactly what this tool does.

**The tool is hardcoded to Claude.** `paths.py` names `.claude*` as constants,
`profiles.py` parses `claudeAiOauth` directly, `configjson.py` exists solely to
splice `~/.claude.json`. None of the switching *flow* is Claude-specific — only
its leaf facts are.

**The login handoff is the roughest edge in the product.** Adding an account
creates an empty profile, activates it, and shows a dialog reading "Run 'claude'
in a terminal, then /login." The user is dropped out of the app at the one
moment they most need it to work.

## 2. Investigation findings

### 2.1 Both vendors ship a one-shot browser login

Verified against the installed CLI on this machine:

```
$ claude auth --help
Commands:
  login [options]   Sign in to your Anthropic account
  logout            Log out from your Anthropic account
  status [options]  Show authentication status

$ claude auth login --help
Options:
  --claudeai       Use Claude subscription (default)
  --console        Use Anthropic Console (API usage billing)
  --email <email>  Pre-populate email address on the login page
  --sso            Force SSO login flow
```

Codex's equivalent is `codex login`, per `shambles/providers/codex.json`.

Both commands open the browser themselves and run their own OAuth callback
server. **Shambles does not need to implement OAuth, hold a client secret, open
a socket, or ever see a token in flight.** It spawns a vendor binary and reads a
file afterwards.

`codex` is **not installed on the development machine**, so its live path is
unverified here. Its spec was researched on macOS and marks Linux and Windows
`platforms_from_source_only`.

### 2.2 The provider and store layers already exist

The unmerged branch `feat/provider-adapters` contains, at commit `1467f7a`
("add the store and provider layers, wired to nothing yet"):

```
shambles/stores/     base.py file.py keychain.py credman.py
shambles/providers/  base.py spec.py claude.py codex.py claude.json codex.json
tests/contract/      test_provider_contract.py test_store_contract.py
tests/fakes.py
```

1317 lines of implementation plus contract tests, and called by nothing.
`switcher.py`, `paths.py`,
`state.py`, `profiles.py` and `gui.py` are untouched by that branch.

A second commit (`01d6de8`) adds a Swift macOS app and a `shambles list --json`
contract. Those serve a different goal and are **not** part of this change.

### 2.3 The two providers are near mirror images

| | claude | codex |
|---|---|---|
| Live store (Linux) | `~/.claude/.credentials.json` | `~/.codex/auth.json` |
| Token form | opaque | JWT |
| Identity | sidecar `~/.claude.json` → `oauthAccount.emailAddress` | `tokens.id_token` JWT claim |
| Liveness | `claudeAiOauth.refreshTokenExpiresAt`, epoch ms | `tokens.access_token` JWT `exp`, epoch s |
| Companion write | splice `oauthAccount`, `cachedUsageUtilization` | none |
| Refresh token rotates | no | **yes** |
| Observed window | ~4 days (Max 5x, n=1) | ~10 days |

Two consequences fall out of the right-hand column. Codex identity **cannot**
desynchronize from its credential, because both live in the same file. And a
stale Codex snapshot is **actively dangerous**: rotation invalidates the old
refresh token, so restoring a pre-refresh copy silently breaks the account.

### 2.4 Environment

`CLAUDE_CONFIG_DIR` relocates the entire Claude tree; `CODEX_HOME` does the same
for Codex and is **strict** — if set, the directory must already exist or Codex
errors out. Both need the warning banner `state.config_dir_override` already
provides for Claude.

## 3. Decisions

| # | Decision | Rationale |
|---|---|---|
| D1 | Codex is a **full peer** — add, login, switch, rename, remove | An add-only Codex group is dead weight in the UI. Scoped to Linux/WSL, matching where Claude is actually verified. |
| D2 | Login **spawns the vendor CLI**; OAuth stays in the vendor binary | Gets browser login without Shambles touching a token in flight. Amends DD-2's "never opens a browser" deliberately, not by accident. |
| D3 | **Cherry-pick** `1467f7a`, not a merge, not a rewrite | Reuses tested work; leaves the Swift app and CLI contract, which serve a different goal. Rewriting would re-solve JWT identity and namespaced claim pointers for no gain. |
| D4 | Store moves to **`~/.shambles/<provider>/<Name>/`** | `~/.claude-profiles/` becomes a lie the moment it holds Codex tokens. Migration cost is identical to any other layout — every option moves the directory. |
| D5 | Migration **copies**, leaving the original on disk | Same posture as the v1.0 merge and as Eject: never make a refresh token unrecoverable as a side effect. |
| D6 | **Per-group headings**; the global header is removed | Warnings are per-provider now. Keeping them in one header means rendering N states in a fixed space that grows with every provider. |
| D7 | Providers are **probed on PATH** | "No Codex accounts yet" next to an uninstalled Codex is a lie of omission; the user finds out only when login fails. |
| D8 | `Save Current Account` moves into the group heading | The footer button has no provider context once there are two. |
| D9 | Keep `credentials.json` / `account.json` filenames | `ClaudeProvider.identity()` already reads `<profile_dir>/account.json`. |

### 3.1 On amending DD-2

DD-2 concluded "do not implement login inside the tool", and listed as a
consequence that the tool "never sees a password, **never opens a browser**,
never holds a token it did not find already on disk."

Two of those three still hold exactly. What changes is that the vendor's browser
flow is now *started* by Shambles instead of typed by the user. The reasoning
DD-2 gives — user trust, and the structural argument that OAuth handling would
destroy the "inert tool" property — is untouched by this, because **no OAuth
code is added**. The credential still appears on disk, written by the vendor,
and Shambles still only finds it there.

DD-2 already approves `subprocess` explicitly ("it is not a constraint on this
project") and already drafts the README replacement wording for when the
`subprocess` claim goes stale. This change triggers that edit earlier than the
macOS build it was written for.

## 4. Architecture

Two orthogonal layers, per DD-4. **The core never learns a provider's name.**

```
stores/      where bytes live      FileStore(path, mode)            [platform axis]
providers/   what bytes mean       ClaudeProvider | CodexProvider   [vendor axis]
             declarative half      providers/<id>.json
login.py     how a lapsed profile gets re-authenticated
core         switcher · state · profiles · gui — talk only to the Provider protocol
```

`KeychainStore` and `CredmanStore` arrive with the cherry-pick and stay
unreferenced. Neither macOS nor Windows can be verified from here, and shipping
an unexercised credential path is worse than shipping none.

## 5. On-disk layout

```
~/.shambles/
  .backups/                      rolling copies of ~/.claude.json (last 10)
  claude/
    active                       "Work"
    Work/
      credentials.json           mode 600
      account.json               {"oauthAccount": {...},
                                  "cachedUsageUtilization": {...},
                                  "stashed_at": <ms>}
    Personal/
      ...
  codex/
    active                       "Work"
    Work/
      credentials.json           mode 600 — a copy of auth.json
                                 (no account.json: identity is inside the JWT)

~/.claude-profiles/              left intact by the migration
~/.claude.json                   REAL FILE, spliced, never replaced
~/.claude/.credentials.json      live Claude login
~/.codex/auth.json               live Codex login
```

The active marker is per provider. Two providers have two independent active
accounts, and no operation on one touches the other.

Profile discovery lists non-dot directories under `~/.shambles/<provider>/`. The
leading dot on `.backups/` excludes it by the same rule, and `active` is
excluded by being a file.

## 6. Operations

### 6.1 Switch A → B, for provider P

Unchanged in shape from v1.0 — DD-4 correctly identifies this flow as already
generic. Only its steps are provider-specific.

1. Refuse if P's companion file exists but cannot be parsed. **Before anything
   moves.** Codex has no companion and skips this.
2. Back up the companion file into `~/.shambles/.backups/`.
3. Stash outgoing: `store.read()` → `<A>/credentials.json`;
   `provider.companion_read()` → `<A>/account.json`.
4. Restore incoming: `<B>/credentials.json` → `store.write()`. If absent,
   `store.delete()` — so the vendor prompts for a login rather than silently
   reusing the previous account.
5. `provider.companion_write()` — keys absent from B are deleted, not left
   holding A's identity.
6. Write `~/.shambles/<P>/active`.

Steps 3–4 in that order are the load-bearing guarantee: the outgoing login is
saved before the incoming one is installed, so switching away can never strand
an account.

### 6.2 Add account, with login

```
＋ Add Account
  └─ AddAccountDialog(name, provider)      provider radio; unavailable ones disabled
     └─ switcher.add_empty_account(paths, provider, name)
          creates ~/.shambles/<P>/<name>/, switches to it, live credential cleared
     └─ login.available(provider)?
          yes → LoginDialog
                  spawn vendor command on a worker thread
                  vendor opens browser + runs its own callback server
                  piped stdout/stderr → dialog (surfaces the fallback URL)
                  exit 0    → store.read() → stash into the profile, refresh
                  exit != 0 → error dialog naming the manual command
                  cancel    → terminate child; profile left empty
          no  → today's instructional dialog, unchanged
```

Leaving the profile empty on failure is not a new failure mode: v1.0's
`add_empty_account` already activates an empty profile, and the vendor's own
`/login` is what fills it. The switch is recoverable by switching back.

### 6.3 Re-stash after use (Codex only)

`policy.rotates: true` means a snapshot taken before a refresh is **dead** — the
rotation invalidated the old refresh token.

`restash_active(paths, provider, platform)` runs at the top of `gui.refresh()`
for providers with `rotates=True`: if the live blob differs from the stashed
copy, re-stash it. Without this, switching away from a Codex account that
refreshed during use writes back a dead token and the account needs a fresh
login — the exact outcome this tool exists to prevent.

Invisible to the user, load-bearing for correctness. This is DD-3's "silent work
must still be correct work".

### 6.4 Store migration

Runs on startup when `~/.claude-profiles/` exists and `~/.shambles/` does not.
Independent of, and after, the existing pre-1.0 symlink migration.

```
~/.claude-profiles/<Name>/{credentials.json,account.json}
   → ~/.shambles/claude/<Name>/{credentials.json,account.json}
~/.claude-profiles/active             → ~/.shambles/claude/active
~/.claude-profiles/.shambles-backups/ → ~/.shambles/.backups/
```

Copies. Idempotent. Reports what it did in a dialog, naming the directory left
behind, in the same voice as the v1.0 history merge.

## 7. Error handling

| Condition | Behaviour |
|---|---|
| Vendor binary not on PATH | Provider disabled in Add Account with a reason; group body shows an install hint; no spawn attempted |
| Login exits non-zero | Error dialog with the stderr tail and the exact manual command — the DD-2 fallback, still intact |
| Login cancelled | Child gets SIGTERM, then SIGKILL after a grace period; profile left empty |
| Browser fails to open | Vendor prints a fallback URL; piping surfaces it in the dialog. Common under WSL and over SSH |
| Companion unparseable | Pre-flight refusal before anything moves (v1.0 behaviour, unchanged) |
| `StoreUnavailableError` | Already a `ShamblesError`; rendered as a dialog, never a stderr traceback |
| Stale Codex snapshot | Prevented by §6.3 |

Every message is user-facing prose. Tracebacks never reach the user — the rule
`errors.py` already states.

## 8. UI

```
┌────────────────────────────────────────────┐
│ ── Claude Code · Work — you@corp.com ────  │
│  ▌ Work       ACTIVE              29d      │
│  ▌ Personal   [Switch] [✕]         4d      │
│                                            │
│ ── Codex ────────────────────────────────  │
│    Codex CLI not found on PATH.            │
│    Install it to add Codex accounts.       │
│                                            │
│           [Eject]  [＋ Add Account]        │
└────────────────────────────────────────────┘
```

- Group heading carries the provider name, its active account, and its warning
  state inline. A provider whose state is `UNMANAGED` / `UNKNOWN` / `DRIFTED`
  renders `Save current login` in its heading.
- Chip severity maps from `Liveness`, with the threshold per provider
  (`provider.warn_days`; Claude ~4 days, Codex ~10 — DD-1 requires this):

| Liveness | Chip |
|---|---|
| `LIVE` | grey `29d` |
| `CLOSING` | amber `4d` / `today` |
| `CLOSED` | red `expired 12d ago` |
| `UNKNOWN` | no chip — the VS Code bundle writes credentials with no expiry field |
| `ABSENT` | no chip, ⚠ badge |

- No token is ever displayed, in any state. DD-3, unchanged.
- The ✕ appears only on inactive profiles, and `remove_profile` re-checks that
  in code. Hiding a button is not a safety property.

## 9. Modules

| Module | Change |
|---|---|
| `stores/` | **new**, cherry-picked. Only `FileStore` is referenced |
| `providers/` | **new**, cherry-picked. Both specs gain a `login.binary` / `login.command` block |
| `login.py` | **new**. `available()`, `command()`, `run()`, `terminate()` |
| `paths.py` | provider-scoped; `.claude*` constants move into the specs |
| `state.py` | `inspect(paths, provider)`; kinds unchanged; `LEGACY_LAYOUT` moves to `migrate.py` |
| `switcher.py` | `provider` threaded through; `copy_secret` → `store.read/write`; gains `restash_active` |
| `profiles.py` | delegates to `provider.liveness()` / `.identity()`; `EXPIRY_WARN_DAYS` → `provider.warn_days` |
| `migrate.py` | gains the second hop (§6.4) |
| `eject.py` | iterates providers |
| `gui.py` | grouped list, provider radio in Add, new `LoginDialog` |
| `configjson.py` | keeps atomic write / backup / prune — already generic. The splice moves to `ClaudeProvider.companion_write` |

`login.py` runs the child on a worker thread and marshals back with
`widget.after()`. A blocking `wait()` on the main thread would freeze the window
and break the signal pump `tests/test_shutdown.py` guards.

## 10. Testing

Every test runs against a synthetic home in `tmp_path`. Nothing reads or writes
a real `~/.claude` or `~/.codex`. That property is preserved absolutely.

- **`test_credentials_survive_a_round_trip_unmodified` is parametrized over
  providers.** It stops being a Claude test and becomes the first case every
  provider must pass, exactly as DD-4 specifies. If it regresses, the tool stops
  solving the problem it exists for.
- The existing ~139 tests gain a provider argument; most changes are mechanical.
- New coverage:
  - store migration — correctness, idempotency, source left intact
  - `login.py` against a **fake vendor binary**: a script in `tmp_path` that
    prints a URL and exits 0 or 1, with `PATH` pointed at it. No network, no
    real vendor, runs in CI
  - Codex identity and liveness from a synthetic unsigned JWT
  - PATH probing, provider present and absent
  - GUI under `xvfb` — group rendering, disabled provider in Add Account

## 11. Operating expectation

Unchanged and still the one real caveat: **do not switch while a session is
running.** A live Claude Code or Codex session holds its token in memory and
rewrites its config on its own schedule. This is a race with another process,
not something the tool can close from outside.

Codex adds a second reason to close sessions first — §6.3's re-stash reads the
live file, and a session refreshing mid-read is the case it exists to handle.

## 12. Out of scope

- macOS Keychain and Windows Credential Manager stores
- The Swift macOS app and `shambles list --json` contract
- MCP OAuth token policy — still the open item DD-2 records; behaviour unchanged
- Claude Desktop, per DD-3
- Any UI for tokens: no refresh, no repair, no manage

## 13. Verification note

The Claude path is verifiable end to end on the development machine. **The Codex
live path is not** — `codex` is not installed, and its spec was researched on
macOS with Linux marked source-only. Codex coverage in this change is the fake
vendor binary plus JWT fixtures. Installing Codex and exercising a real
`auth.json` swap is a follow-up, and should happen before Codex support is
described as verified anywhere user-facing.
