# Shambles Production Terminal UI Design

**Date:** 2026-09-06  
**Status:** Approved for implementation planning

## Purpose

Shambles will gain a production-grade terminal user interface for managing and
switching Claude Code and Codex accounts. It will preserve the existing
safety-critical switching implementation, remain useful in headless and remote
environments, and be installable as a self-contained executable through npm.

The TUI is a new presentation layer, not a new account-switching
implementation. The Tk interface, scriptable CLI, native shells, and TUI will
all use the same application-service boundary.

## Goals

- Provide a fast keyboard-driven account switcher with rich account details.
- Work coherently in wide, medium, and narrow terminals.
- Expose all account lifecycle operations through one tested application API.
- Preserve Shambles' local-only, no-telemetry security promise.
- Offer an optional way to launch the selected vendor CLI in the same terminal.
- Support explicit installation and updates through npm without requiring
  Python on the user's machine.
- Keep the existing script-friendly CLI and graphical interfaces functional.

## Non-goals

- Opening a new terminal window after a switch.
- Passing credentials through command arguments or environment variables.
- Silent updates, background update checks, or telemetry.
- A third-party provider plugin system.
- Switching Claude Desktop chat accounts.
- Detecting or terminating every running Claude or Codex process.
- Adding providers beyond Claude and Codex in the first release.

## Architecture

The runtime has four presentation clients above one shared service:

```text
Textual TUI ─┐
Script CLI ──┼──> Application service ──> Existing Shambles core
Tk GUI ──────┤                              │
Native shell ┘                         Providers × stores
```

The application service is the only public route for account operations. It
coordinates existing modules; it does not replace the atomic switching logic
in `switcher.py`.

Proposed source layout:

```text
shambles/
├── app/
│   ├── service.py
│   ├── snapshot.py
│   ├── cli.py
│   └── tui/
│       ├── application.py
│       ├── screens.py
│       ├── widgets.py
│       └── theme.tcss
├── providers/
├── stores/
└── switcher.py
```

### Application service

The service exposes typed operations:

```python
list_accounts()
switch_account(provider, account)
save_current_account(provider, name)
add_account(provider, name)
rename_account(provider, old_name, new_name)
remove_account(provider, name)
login_account(provider, name)
refresh()
survey_eject()
eject()
```

Every mutation returns a structured result containing:

- success or failure;
- a stable machine-readable code;
- user-facing summary and recovery guidance;
- warnings;
- an updated snapshot when available.

Operations that need confirmation have a read-only planning form. The plan
names exactly what will change and is passed back to the service for execution.
UI layers never infer safe recovery actions by parsing message text.

The service is also the place to extract lifecycle orchestration currently
embedded in `gui.py`. Provider interpretation, store access, and switching
order remain in their existing modules.

## Terminal interface

The TUI uses Textual. Because bare `shambles` opens the TUI, Textual is a
normal runtime dependency rather than an optional extra. It is bundled inside
release executables and npm platform packages, so those users do not manage
Python dependencies.

### Responsive dashboard

The selected design combines fast list navigation with a persistent detail
view.

On terminals at least 78 columns wide:

- the left pane lists provider groups and their accounts;
- the right pane shows the selected account's identity, plan, status, usage,
  login health, affected applications, and available actions.

Between 48 and 77 columns, the selected account expands below its row. Below
48 columns, the interface uses a compact single-column form and omits
nonessential decoration. Content never wraps into an ambiguous layout. If the
terminal cannot fit the minimum usable controls, the app displays the required
dimensions and remains safely quittable.

Terminal width is measured in character cells. The design does not scale
characters, crop artwork, or assume that pixels map consistently to cells.
Resize events reselect the appropriate composition while preserving the
selected provider and account.

### Account details

The detail view includes:

- profile name, email address, and plan when known;
- active, ready, closing, expired, signed-out, or unavailable state;
- session and weekly usage with reset times when the provider publishes them;
- whether cached usage is stale and when it was last updated;
- refresh-window health without displaying raw token data;
- surfaces affected by switching, such as CLI, VS Code, and ChatGPT;
- a reminder that already-running sessions retain their loaded credential;
- actions valid for the selected account.

Missing data is shown as unavailable rather than estimated.

### Screens and overlays

The interface has four primary states:

1. **Account dashboard:** provider groups, accounts, and selected-account
   detail.
2. **Account workflow:** add, save, rename, remove, login, and eject flows.
3. **Confirmation overlay:** explicit approval for destructive or sensitive
   actions.
4. **Help overlay:** shortcuts, security model, affected surfaces, and
   troubleshooting.

The default shortcuts are:

| Key | Action |
|---|---|
| Up/Down or `j`/`k` | Select an account |
| Left/Right or `h`/`l` | Move between provider groups |
| Enter | Switch to the selected account |
| `a` | Add an account |
| `l` | Log in or reauthenticate |
| `r` | Refresh local state |
| `m` | Open account actions |
| `?` | Open help |
| `q` | Quit |

Enter on the active account performs no mutation. Destructive actions require
a confirmation overlay and cannot be executed by a single accidental
keystroke. The selected account remains selected after refresh if it still
exists.

## Switching and launching

Switching follows the existing safe order:

```text
Select account
    ↓
Build read-only plan and run preflight
    ↓
Request confirmation when required
    ↓
Use the existing atomic switch operation
    ↓
Read a fresh snapshot from disk
    ↓
Show the result and session-restart guidance
```

The TUI permits only one mutating operation at a time. Repeated keys cannot
queue duplicate switches. Navigation and help remain responsive while an
operation is running.

After a successful switch, the TUI offers:

```text
✓ Switched Claude Code to Work
  ian@company.com

  [ Enter ] Launch Claude here
  [ Esc   ] Return to accounts
  [ q     ] Quit
```

Launching is always optional. The TUI first restores the cursor, input mode,
and alternate screen, then starts the provider's official CLI in the same
terminal. The vendor process reads its normal credential store. Shambles never
puts credential material in arguments or environment variables.

The first release does not open a separate terminal window. New-window
behavior is inconsistent across desktop environments, WSL, SSH, and terminal
multiplexers.

## State and failure recovery

The TUI holds presentation state only:

- selected provider and account;
- open overlay;
- current operation state;
- latest immutable snapshot;
- temporary notification.

Disk remains authoritative. There is no separate TUI account database.

Each operation uses this state machine:

```text
Idle → Planning → Awaiting confirmation → Running
                                      ├→ Succeeded → refresh snapshot
                                      └→ Failed    → preserve error
```

After success or failure, the service reads disk again. The UI does not
construct an optimistic state.

The dashboard represents these existing conditions explicitly:

- **Managed:** the expected account is live.
- **Unmanaged:** a live credential exists but no profile owns it.
- **Drifted:** the live identity differs from the active marker.
- **Missing profile:** the marker names a directory that is absent.
- **Store unavailable:** the selected platform credential store cannot be
  reached.
- **Signed out or expired:** the profile exists but requires the vendor login
  flow.

Example error result:

```json
{
  "ok": false,
  "error": {
    "code": "live_identity_drifted",
    "message": "Claude is signed in as a different account.",
    "recovery": "Save the live account or restore the expected profile."
  }
}
```

Errors remain visible until dismissed. Credential contents never enter logs,
notifications, exceptions, clipboard operations, or test snapshots.

The TUI shares one cleanup path for normal exit, `Ctrl+C`, `Ctrl+D`,
terminal closure, and unhandled Python exceptions. Cleanup restores the
cursor, input mode, and alternate screen before control returns to the shell.

Shambles cannot externally lock a running vendor process. The detail pane and
post-switch result state clearly state that existing sessions retain their
loaded credential and may rewrite vendor-owned state. The interface does not
claim that process detection guarantees safety.

### Login

Login continues to use the vendor's official command. The TUI shows progress
and captures only sanitized status output. On process exit, it reads the
credential store again. A zero exit code alone is not treated as proof of a
successful login; the resulting credential must exist and resolve to a valid
profile state.

## Brand system

The approved brand combines a heavy terminal wordmark with a warm
terracotta-and-gold palette:

- terracotta `#e07a5f` for the wordmark and terminal/switch symbol;
- gold `#d9a441` for frames and supporting copy;
- dark navy `#0b1020` for the README banner background.

The colored README asset is
`docs/assets/shambles-banner.svg`. It includes an accessible title and
description. A collapsed text version remains in the README.

The TUI does not load the SVG. It ships hand-composed terminal-native variants:

| Width | Brand treatment |
|---|---|
| 78 columns or wider | Full framed wordmark during onboarding |
| 48–77 columns | Medium branded panel |
| Below 48 columns | Compact `>_ ⇄ SHAMBLES` mark |

The full wordmark appears only during onboarding, an explicit welcome screen,
or an about screen. The normal dashboard uses the compact mark.

### Restrained motion

Onboarding reuses the approved ANSI wordmark from the README. It may play one
brief box-loop: corners appear, horizontal borders draw, vertical borders draw,
and the completed frame settles around the static wordmark. The wordmark never
fades, slides, or loops. `Enter` and `Esc` skip the sequence immediately.

Normal navigation remains static. Motion is limited to this one-time onboarding
frame, explicit operation progress, and a brief post-switch highlight. It is
disabled by `NO_COLOR`, `SHAMBLES_NO_MOTION=1`, or `--no-motion`; narrow
terminals show the completed compact mark without animation.

True-color terminals receive the approved hex colors. A 256-color terminal
uses the nearest indexed colors. A basic color terminal uses yellow and the
default foreground. `NO_COLOR` produces a monochrome interface. When Unicode
is unreliable, `⇄` and box-drawing characters fall back to strict ASCII:

```text
>_ <-> SHAMBLES
Local account switcher
```

## Command-line behavior

```text
shambles              Open the TUI when attached to an interactive terminal
shambles tui          Explicitly open the TUI
shambles gui          Open the existing graphical interface
shambles list         List accounts for people and scripts
shambles switch ...   Switch non-interactively
shambles --version    Print the unified release version
shambles --no-motion  Disable nonessential terminal motion
```

When standard input or output is not interactive, bare `shambles` prints
help instead of drawing a TUI. Machine-readable commands retain their JSON
forms and stable exit codes.

## npm distribution

The npm package is a thin launcher over platform-specific, self-contained
executables:

```text
shambles
├── bin/shambles.js
└── optionalDependencies
    ├── @shambles/linux-x64
    ├── @shambles/linux-arm64
    ├── @shambles/darwin-x64
    ├── @shambles/darwin-arm64
    └── @shambles/windows-x64
```

These package names are provisional until registry ownership and name
availability are confirmed. Changing the published names does not change the
launcher architecture.

The launcher selects and starts the executable matching the host. It does not
read credentials or contain account logic. Platform packages declare their
`os` and `cpu` constraints. Unsupported combinations fail with a clear
message.

Executables bundle Python, Textual, and the Shambles package. npm users do not
need Python, pip, or pipx. The packages contain the executable at publication
time; no install lifecycle script downloads code.

Python and direct-binary installation remain supported.

### Updates and privacy

Users install or update explicitly:

```bash
npm install --global shambles
npm install --global shambles@latest
```

Shambles performs no background version check, self-update, telemetry, or
outbound request. npm contacts its registry only when the user invokes npm.
No account name, identity, usage data, or credential is sent by Shambles.

The Python distribution, npm launcher, npm platform packages, and release
binaries share one release version. The JSON contract has its own version,
which changes only for incompatible schema changes.

## Testing

The production gate has these layers:

1. **Core contract tests:** every supported provider/store combination
   preserves credentials byte-for-byte across a round trip.
2. **Application-service tests:** operations return correct snapshots,
   structured results, stable errors, and recovery actions.
3. **TUI unit tests:** navigation, focus, dialogs, shortcuts, asynchronous
   operations, and resize behavior.
4. **TUI snapshot tests:** wide, medium, narrow, Unicode, ASCII, true-color,
   256-color, and `NO_COLOR` renderings.
5. **Terminal recovery tests:** normal exit, exceptions, signals, and failed
   vendor launch restore terminal state.
6. **Integration tests:** TUI actions use synthetic homes and fake vendor
   commands.
7. **Binary smoke tests:** version, list, switch, TUI boot, and clean exit on
   every supported build target.
8. **npm package tests:** install from packed tarballs, select the correct
   executable, run, update, reject unsupported platforms, and uninstall.
9. **Security tests:** prohibit networking imports, token output, secrets in
   errors, and lifecycle scripts that download executables.

No automated test reads a real user home or invokes a real vendor login.

## Release pipeline

```text
Tag release
    ↓
Run Python, service, TUI, and security tests
    ↓
Build platform executables
    ↓
Smoke-test each executable
    ↓
Publish platform npm packages
    ↓
Publish the npm launcher last
    ↓
Attach signed artifacts and checksums to GitHub
```

Publishing the launcher last prevents npm from advertising a release whose
platform executable is missing. A failed release does not move the npm
`latest` tag.

## Initial production support

| Platform | Initial status |
|---|---|
| Linux x64 and arm64 | Supported after binary and live switch validation |
| WSL | Supported through the matching Linux package |
| macOS x64 and arm64 | Supported after Keychain integration passes live tests |
| Windows x64 | Experimental until Credential Manager switching is verified |

Claude and Codex are the only initial providers. A provider is not marked
supported merely because its fixture tests pass; at least one live-machine
switch and round-trip verification is required for each supported
provider/platform store.

## Documentation and migration

The release documentation will:

- explain that the Claude CLI and VS Code extension share the switched login;
- explain that already-running sessions must restart;
- distinguish Claude Code from Claude Desktop chat;
- document npm, pipx, and direct-binary installation and update commands;
- retain the no-network security explanation;
- name experimental and unsupported platforms accurately.

Existing profiles require no migration for the TUI. The application service
uses the current store layout and migration path.
