# Shambles — Multi-channel Install & Opt-in Update Notice

**Date:** 2026-09-08
**Status:** IMPLEMENTED — plan at [`../plans/2026-09-08-install-and-update-notice.md`](../plans/2026-09-08-install-and-update-notice.md)

Two things below were decided differently during implementation, because npm
is still unpublished and shipping a command that fails is worse than shipping
one fewer route:

- **§3 / §3.1 — the README leads with the curl and irm scripts, not npm.** npm
  is documented last, marked as not yet available, with the reason. It becomes
  the primary route when the [npm plan](../plans/2026-09-06-npm-distribution.md)
  actually publishes.
- **§7 — the notice names only the install script.** The copy in §7 offered
  `npm i -g shambles@latest` as the first route; a version notice that tells
  the reader to run a command that does not work is worse than no notice.

Give users Claude-like install paths on Linux, macOS, and Windows: **npm as
primary**, **curl / irm scripts** when Node is absent, while keeping pipx and
direct Release downloads. Add an **opt-in** “newer version available” notice
that is **off by default**, preserving the no-outbound-request rule unless the
user enables checks.

Extends [terminal-ui-design § npm distribution](2026-09-06-terminal-ui-design.md#npm-distribution)
and amends its absolute “no outbound request” wording for a single, gated
GitHub Releases lookup. Does not replace the existing
[npm distribution plan](../plans/2026-09-06-npm-distribution.md); that plan
remains the implementation vehicle for the npm half. Curl installers and the
update-notice feature are additive.

**Prerequisite:** finish the terminal-UI roadmap gates called out in that npm
plan (application service, Textual TUI, platform-store hardening) before
publishing npm packages or claiming macOS/Windows switching support.

---

## 1. Problem

Users want `shambles` on PATH the way they get Claude Code — one short
install command — on Linux, macOS, and Windows. Today the README leads with
pipx-from-git and manual Release downloads. npm distribution is designed but
not shipped; there is no `install.sh` / `install.ps1`.

Separately, users may want to know when a newer release exists without
forcing every install to phone home (the product manages login files).

---

## 2. Goals and non-goals

### Goals

- **Primary:** `npm install -g shambles` then `shambles`.
- **Secondary:** curl|bash (Unix) and irm|iex (Windows) install the matching
  GitHub Release binary with no Node.
- Keep pipx and manual binary download documented.
- Shared Release binaries feed npm platform packages and the shell installers.
- Opt-in update notice (default off); no auto-download or self-update.
- Docs distinguish **install success** from **account-switching support**
  (Linux supported; Windows experimental; macOS after Keychain work).

### Non-goals

- Implementing Keychain or Credential Manager switching in this workstream.
- Background telemetry, crash reporting, or unsigned-code notarization.
- Replacing the existing npm plan’s architecture (launcher + optional
  platform packages, no lifecycle download scripts).
- Making update checks on by default.

---

## 3. User-facing install story

### 3.1 Primary — npm

```bash
npm install -g shambles
shambles
```

Update explicitly:

```bash
npm install -g shambles@latest
```

### 3.2 Secondary — no Node

```bash
# Linux / macOS / WSL
curl -fsSL https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.sh | bash

# optional pin
curl -fsSL …/install.sh | bash -s v2.0.0

# Windows PowerShell
irm https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.ps1 | iex
```

Scripts live in-repo under `scripts/` so the raw.githubusercontent.com URLs
are stable on `main` (and tagged releases still work if users pin a tag URL).

### 3.3 Also documented

- `pipx install git+https://github.com/ianchendev/Shambles`
- Direct download from GitHub Releases

README Install section: npm first, then curl/irm, then pipx, then Releases.

---

## 4. Shared release assets

Release CI builds (and smoke-tests) executables both channels consume:

| Artifact | npm package (provisional names) | Shell installer |
|---|---|---|
| `shambles-linux-x86_64` | `@shambles/linux-x64` | `install.sh` |
| `shambles-linux-arm64` | `@shambles/linux-arm64` | `install.sh` |
| `shambles-macos-x86_64` | `@shambles/darwin-x64` | `install.sh` |
| `shambles-macos-arm64` | `@shambles/darwin-arm64` | `install.sh` |
| `shambles-windows-x64.exe` | `@shambles/windows-x64` | `install.ps1` |

Today’s workflow already builds Linux x86_64 and Windows x64. This design
**requires** adding macOS (and Linux arm64 if not already present) before
claiming those install targets work. Until an asset exists, installers and
npm must fail with a clear “no binary for this platform yet” message.

Package names stay provisional until npm scope ownership is confirmed (same
as the terminal-UI design).

---

## 5. npm channel

Follow [2026-09-06-npm-distribution.md](../plans/2026-09-06-npm-distribution.md)
and the terminal-UI design:

- Thin launcher selects the host platform package and `exec`s the binary.
- No `preinstall` / `install` / `postinstall` scripts that download code.
- Publish platform packages first; publish the launcher last so `latest`
  never points at a missing platform artifact.
- One release version across Python package, binaries, and npm packages.

---

## 6. Curl / irm installers

### 6.1 `scripts/install.sh` (Linux, macOS, WSL)

1. Detect OS/arch (`uname -s` / `uname -m`); map to a Release asset name.
2. Resolve version: argument if given, else latest GitHub Release tag via API
   or `…/releases/latest` redirect.
3. Download asset to a temp file; `chmod +x`.
4. Install to `~/.local/bin/shambles` (create directory if needed). No sudo.
5. If `~/.local/bin` is not on PATH, print exact shell snippet to add it.
6. Run `shambles --version` as a smoke check; print success line.
7. On missing asset or unsupported OS: non-zero exit and plain-language error.

### 6.2 `scripts/install.ps1` (Windows)

1. Detect x64 (other arch: clear unsupported message).
2. Resolve latest or pinned tag; download `shambles-windows-x64.exe`.
3. Install under `%LOCALAPPDATA%\Shambles\shambles.exe`.
4. Ensure that directory (or a shim) is on the **user** PATH.
5. Smoke-test `--version`; warn that binaries are unsigned (SmartScreen).

### 6.3 Honesty

Installers may succeed on a platform where **switching** is still
experimental or unsupported. Post-install message (and README) must not claim
otherwise; point at the support matrix.

---

## 7. Opt-in update notice

### 7.1 Default

**Off.** With the flag off, Shambles makes no outbound requests (unchanged
from the terminal-UI privacy rule).

### 7.2 Enable

User turns on a setting stored under `~/.shambles/` (exact key/command to
match whatever config surface exists at implementation time — e.g.
`shambles config set update.check true` and/or a TUI/GUI toggle). Documented
in README and `--help`.

### 7.3 Behavior when enabled

- At most **once per 24 hours**, GET the latest release tag from the public
  GitHub Releases API for `ianchendev/Shambles` (or the configured repo).
- Compare to the running app version.
- If newer: one-line dismissible notice in TUI/GUI; optionally mention on
  `shambles --version`.
- Notice text tells the user how to update — **never** downloads or replaces
  the binary itself. *As implemented it names the install script only; see the
  status note at the top of this document.*
- Network errors, timeouts, and rate limits: fail silent (no modal spam).
- Cache file under `~/.shambles/`: latest-seen tag + check timestamp only.
  No account names, emails, or tokens.

### 7.4 Security amendment

The existing “no networking imports” / AST gate is amended to allow **only**
this Releases lookup path when update checks are enabled. Credential and
config paths are never included in the request. SECURITY.md / README note
the opt-in exception.

---

## 8. Release pipeline (extended)

```text
Tag release
    ↓
Tests (Python, service, TUI, security)
    ↓
Build platform executables (Linux x64/arm64, macOS x64/arm64, Windows x64)
    ↓
Smoke-test each executable
    ↓
Attach artifacts (+ checksums) to GitHub Release
    ↓
Publish npm platform packages
    ↓
Publish npm launcher last
```

Curl/irm scripts are not re-published per release when they live on `main`;
they always resolve the latest (or pinned) Release assets.

---

## 9. Testing

- **install.sh / install.ps1:** unit-test OS→asset mapping; integration test
  against a fake Release HTTP fixture (no live GitHub required in CI).
- **npm:** as in the npm plan (packed tarballs, platform select, unsupported
  host, uninstall).
- **Update notice:** flag off → zero network mocks hit; flag on → mock
  Releases response shows banner when newer, stays quiet when equal/older;
  failure path stays silent; cache respects 24h TTL.
- **Security:** AST/network allowlist tests cover the gated Releases client
  only.

---

## 10. File touch list (expected)

| Area | Likely paths |
|---|---|
| Install scripts | `scripts/install.sh`, `scripts/install.ps1` |
| npm | `npm/` per existing plan |
| Release CI | `.github/workflows/release.yml` (macOS + arm64 matrix) |
| Update check | small module under `shambles/` + TUI/GUI/CLI wiring |
| Docs | README Install, SECURITY.md note, CHANGELOG, release body |

---

## 11. Success criteria

- New user with Node: `npm i -g shambles` → `shambles` runs.
- New user without Node (supported binary): curl/irm → `shambles` on PATH.
- macOS/Windows install does not over-claim switching support.
- Update checks off by default; with flag on, a newer Release produces a
  non-blocking notice and never auto-updates.
- npm `latest` never advertises a release missing that host’s platform package.
