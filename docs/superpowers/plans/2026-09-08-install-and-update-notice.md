# Install Scripts & Opt-in Update Notice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Claude-like `install.sh` / `install.ps1` for Release binaries, expand the Release build matrix, and add an opt-in “newer version” notice that is off by default.

**Architecture:** A small Python `release_assets` module is the named contract for OS/arch → artifact. Shell installers embed the same mapping and download from GitHub Releases into user-local PATH dirs. Settings live in `~/.shambles/settings.json`; `update_check` may call GitHub only when `update.check` is true. npm packaging stays in the separate [npm distribution plan](2026-09-06-npm-distribution.md) — do not re-implement it here.

**Tech Stack:** bash, PowerShell, Python 3.10+, urllib (gated), pytest, GitHub Actions / Releases API

**Spec:** [`docs/superpowers/specs/2026-09-08-install-and-update-notice-design.md`](../specs/2026-09-08-install-and-update-notice-design.md)

## Global Constraints

- Update checks are **off by default**; no outbound request unless the user enables them.
- When enabled: at most one GitHub Releases lookup per 24h; cache tag + timestamp only under `~/.shambles/`; never auto-download or self-replace the binary.
- Install to `~/.local/bin/shambles` (Unix, no sudo) or `%LOCALAPPDATA%\Shambles\shambles.exe` (Windows).
- Install success ≠ switching support — post-install and README must not claim macOS Keychain or Windows CM switching works until those gates pass.
- Networking imports are banned package-wide **except** `shambles/update_check.py`.
- Do not execute the [npm distribution plan](2026-09-06-npm-distribution.md) as part of this plan; update the roadmap to run it after this plan’s verification (and after platform-store hardening).
- No new runtime dependencies beyond the stdlib for update checks (`urllib.request`).

## File map

| File | Responsibility |
|---|---|
| `shambles/release_assets.py` | OS/arch → Release artifact name |
| `scripts/install.sh` | Unix installer (self-contained) |
| `scripts/install.ps1` | Windows installer |
| `tests/test_release_assets.py` | Mapping + shell/script sync checks |
| `tests/test_install_scripts.py` | Fixture HTTP install dry-runs where practical |
| `.github/workflows/release.yml` | Add macOS + linux-arm64 build matrix entries |
| `shambles/settings.py` | Read/write `~/.shambles/settings.json` |
| `shambles/update_check.py` | Opt-in Releases fetch + cache + compare |
| `shambles/app/cli.py` / `__main__.py` | `config` subcommands + version notice line |
| TUI footer/banner (existing app module) | Show dismissible one-liner when newer |
| `tests/test_login.py` | Allowlist networking only in `update_check.py` |
| `README.md`, `SECURITY.md`, roadmap | Install order + opt-in privacy note |

---

### Task 1: Release asset naming contract

**Files:**
- Create: `shambles/release_assets.py`
- Create: `tests/test_release_assets.py`

**Produces:** `release_asset(*, sys_platform: str, machine: str) -> str` raising `UnsupportedPlatform` with a clear message; `ARTIFACTS` frozenset of all artifact basenames.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_release_assets.py
import pytest
from shambles.release_assets import UnsupportedPlatform, release_asset

@pytest.mark.parametrize("sys_platform,machine,want", [
    ("linux", "x86_64", "shambles-linux-x86_64"),
    ("linux", "amd64", "shambles-linux-x86_64"),
    ("linux", "aarch64", "shambles-linux-arm64"),
    ("linux", "arm64", "shambles-linux-arm64"),
    ("darwin", "x86_64", "shambles-macos-x86_64"),
    ("darwin", "arm64", "shambles-macos-arm64"),
    ("win32", "AMD64", "shambles-windows-x64.exe"),
    ("win32", "x86_64", "shambles-windows-x64.exe"),
])
def test_release_asset_mapping(sys_platform, machine, want):
    assert release_asset(sys_platform=sys_platform, machine=machine) == want

def test_unsupported_platform_is_clear():
    with pytest.raises(UnsupportedPlatform, match="freebsd"):
        release_asset(sys_platform="freebsd", machine="x86_64")
```

- [ ] **Step 2: Run — expect FAIL**

Run: `.venv/bin/pytest tests/test_release_assets.py -v`  
Expected: FAIL importing `shambles.release_assets`

- [ ] **Step 3: Implement**

```python
# shambles/release_assets.py
"""Map host OS/arch to GitHub Release artifact basenames.

Kept in Python so tests and docs stay honest. ``scripts/install.sh`` and
``scripts/install.ps1`` embed the same table; Task 2's sync test fails if they
drift.
"""

class UnsupportedPlatform(ValueError):
    pass

_LINUX = {
    "x86_64": "shambles-linux-x86_64",
    "amd64": "shambles-linux-x86_64",
    "aarch64": "shambles-linux-arm64",
    "arm64": "shambles-linux-arm64",
}
_DARWIN = {
    "x86_64": "shambles-macos-x86_64",
    "arm64": "shambles-macos-arm64",
}
_WIN = {
    "AMD64": "shambles-windows-x64.exe",
    "x86_64": "shambles-windows-x64.exe",
    "amd64": "shambles-windows-x64.exe",
}

ARTIFACTS = frozenset(_LINUX.values()) | frozenset(_DARWIN.values()) | frozenset(_WIN.values())

def release_asset(*, sys_platform: str, machine: str) -> str:
    table = {"linux": _LINUX, "darwin": _DARWIN, "win32": _WIN}.get(sys_platform)
    if table is None or machine not in table:
        raise UnsupportedPlatform(
            f"No Shambles binary for {sys_platform}-{machine} yet")
    return table[machine]
```

- [ ] **Step 4: Run — expect PASS**

- [ ] **Step 5: Commit**

```bash
git add shambles/release_assets.py tests/test_release_assets.py
git commit -m "feat: name GitHub Release artifacts per OS and arch"
```

---

### Task 2: `scripts/install.sh`

**Files:**
- Create: `scripts/install.sh` (executable)
- Modify: `tests/test_release_assets.py` (add sync + mapping helpers used by install tests)
- Create: `tests/test_install_scripts.py`

**Consumes:** artifact names from Task 1  
**Produces:** Unix installer that downloads latest (or `$1` tag) asset into `~/.local/bin/shambles`

- [ ] **Step 1: Write failing sync + behavior tests**

```python
# append to tests/test_release_assets.py
from pathlib import Path
from shambles.release_assets import ARTIFACTS

def test_install_sh_mentions_every_unix_artifact():
    text = Path("scripts/install.sh").read_text(encoding="utf-8")
    for name in ARTIFACTS:
        if name.endswith(".exe"):
            continue
        assert name in text, f"install.sh missing {name}"
```

```python
# tests/test_install_scripts.py
import os, stat, subprocess, textwrap
from pathlib import Path
import pytest

@pytest.fixture
def fake_release(tmp_path, monkeypatch):
    """Minimal static file server stand-in: pre-seed a 'downloaded' binary via
    rewriting PATH to a curl stub that copies a fixture file."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    payload = tmp_path / "payload"
    payload.write_bytes(b"#!/bin/sh\necho fake-shambles\n")
    payload.chmod(0o755)
    curl = bin_dir / "curl"
    curl.write_text(textwrap.dedent(f"""\
        #!/bin/sh
        # ignore args; always emit the fixture binary to -o target
        out=""
        while [ $# -gt 0 ]; do
          if [ \"$1\" = \"-o\" ]; then out=$2; shift 2; continue; fi
          shift
        done
        cp {payload} \"$out\"
        """), encoding="utf-8")
    curl.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (tmp_path / "home").mkdir()
    return tmp_path

@pytest.mark.skipif(os.name == "nt", reason="bash installer")
def test_install_sh_writes_local_bin(fake_release, monkeypatch):
    # Point the script at a local 'API' by exporting SHAMBLES_RELEASE_BASE
    # (installer must honor this override for tests — see implementation).
    monkeypatch.setenv("SHAMBLES_RELEASE_BASE", "https://example.test")
    monkeypatch.setenv("SHAMBLES_FORCE_ASSET", "shambles-linux-x86_64")
    script = Path("scripts/install.sh").resolve()
    subprocess.run(["bash", str(script)], check=True)
    dest = Path(os.environ["HOME"]) / ".local/bin/shambles"
    assert dest.is_file()
    assert dest.stat().st_mode & stat.S_IXUSR
```

- [ ] **Step 2: Run — expect FAIL** (missing `scripts/install.sh`)

- [ ] **Step 3: Implement `scripts/install.sh`**

Requirements to encode in the script (full script in the commit; outline here):

- `set -euo pipefail`
- Map `uname -s`/`uname -m` to the same names as Task 1 (`Linux`→linux, `Darwin`→darwin; normalize `amd64`/`arm64`/`aarch64`)
- Honor `SHAMBLES_FORCE_ASSET` (tests) and optional `$1` version tag (`vX.Y.Z`)
- Honor `SHAMBLES_RELEASE_BASE` defaulting to `https://github.com/ianchendev/Shambles/releases`
- Resolve latest via `$BASE/latest/download/$ASSET` when no version pin; pinned via `$BASE/download/$TAG/$ASSET`
- Install to `"$HOME/.local/bin/shambles"`, `chmod +x`
- If `~/.local/bin` not on PATH, print: `export PATH="$HOME/.local/bin:$PATH"`
- Print support-honesty line: install ≠ switching support; see README matrix
- On unknown OS/arch: exit 1 with `No Shambles binary for … yet`
- Optional smoke: `"$HOME/.local/bin/shambles" --version` if the binary is real (skip when `SHAMBLES_SKIP_SMOKE=1` for fixture tests)

- [ ] **Step 4: Run tests — PASS** (set `SHAMBLES_SKIP_SMOKE=1` in the fixture test)

- [ ] **Step 5: Commit**

```bash
git add scripts/install.sh tests/test_release_assets.py tests/test_install_scripts.py
git commit -m "feat: add curl|bash installer for Release binaries"
```

---

### Task 3: `scripts/install.ps1`

**Files:**
- Create: `scripts/install.ps1`
- Modify: `tests/test_release_assets.py` (assert `.exe` name appears in ps1)

**Produces:** Windows installer → `%LOCALAPPDATA%\Shambles\shambles.exe` + user PATH

- [ ] **Step 1: Failing sync test**

```python
def test_install_ps1_mentions_windows_artifact():
    text = Path("scripts/install.ps1").read_text(encoding="utf-8")
    assert "shambles-windows-x64.exe" in text
```

- [ ] **Step 2: Run — FAIL**

- [ ] **Step 3: Implement `scripts/install.ps1`**

- Refuse non-x64 with a clear message
- Download from GitHub Releases (support `-Version vX.Y.Z` and env overrides `SHAMBLES_RELEASE_BASE` / `SHAMBLES_FORCE_ASSET` for tests)
- Write to `$env:LOCALAPPDATA\Shambles\shambles.exe`
- Add that directory to the **user** PATH if missing (`[Environment]::SetEnvironmentVariable("Path", …, "User")`)
- Warn binaries are unsigned (SmartScreen)
- Print support-honesty line
- Smoke `--version` unless `SHAMBLES_SKIP_SMOKE=1`

- [ ] **Step 4: Sync test PASS** (full ps1 execution in CI is optional on Linux runners; sync + review is enough unless a Windows job already exists for scripts)

- [ ] **Step 5: Commit**

```bash
git add scripts/install.ps1 tests/test_release_assets.py
git commit -m "feat: add PowerShell installer for Windows Release binary"
```

---

### Task 4: Expand Release build matrix

**Files:**
- Modify: `.github/workflows/release.yml`

**Produces:** CI artifacts for linux-arm64, macos-x86_64, macos-arm64 in addition to existing linux-x86_64 and windows-x64

- [ ] **Step 1: Extend matrix `include`**

Add entries (mirror existing Linux/Windows steps’ PyInstaller flags and `--add-data` patterns; macOS uses `:` separator like Linux):

```yaml
- os: ubuntu-24.04-arm
  artifact: shambles-linux-arm64
  built: dist/shambles
- os: macos-13
  artifact: shambles-macos-x86_64
  built: dist/shambles
- os: macos-14
  artifact: shambles-macos-arm64
  built: dist/shambles
```

Wire `if: runner.os == 'macOS'` build/test/smoke steps analogous to Linux (no xvfb; `pytest` then PyInstaller onefile with provider JSON + tcss `--add-data`).

Update release body blurb to mention curl/irm and npm-primary (npm publish still later).

- [ ] **Step 2: Open a draft PR or push a test tag on a fork if available; otherwise commit and note “verify on next `v*` tag”**

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: build macOS and linux-arm64 Release binaries"
```

---

### Task 5: Settings + update check module

**Files:**
- Create: `shambles/settings.py`
- Create: `shambles/update_check.py`
- Create: `tests/test_settings.py`
- Create: `tests/test_update_check.py`
- Modify: `shambles/paths.py` — add `settings_path` property → `library_dir / "settings.json"`
- Modify: `tests/test_login.py` — networking allowlist

**Produces:**

```python
# settings
load_settings(paths) -> dict
save_settings(paths, data) -> None
update_check_enabled(paths) -> bool   # default False
set_update_check(paths, enabled: bool) -> None

# update_check
@dataclass(frozen=True)
class UpdateStatus:
    enabled: bool
    current: str
    latest: str | None
    newer: bool
    message: str | None  # user-facing one-liner or None

check_for_update(paths, *, current_version: str, now_s: float,
                 fetch=...) -> UpdateStatus
```

Fetch URL (only when enabled):  
`https://api.github.com/repos/ianchendev/Shambles/releases/latest`  
Parse `tag_name`, strip leading `v`, compare with packaging-style loose semver or simple tuple split on `.`. Cache at `paths.library_dir / "update-cache.json"`: `{"checked_at": <epoch>, "latest": "<tag>"}`. TTL 86400 seconds. On any error: return `UpdateStatus(enabled=True, newer=False, message=None, …)`.

Notice copy when newer:  
`Shambles {latest} is available (you have {current}). Update with: npm i -g shambles@latest — or re-run the install script.`

- [ ] **Step 1: Failing tests**

```python
def test_update_check_default_off_never_fetches(paths):
    calls = []
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=lambda url: calls.append(url) or {"tag_name": "v9.0.0"})
    assert status.enabled is False and status.newer is False
    assert calls == []

def test_update_check_fetches_when_enabled(paths):
    set_update_check(paths, True)
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=lambda url: {"tag_name": "v2.1.0"})
    assert status.newer is True
    assert "2.1.0" in (status.message or "")

def test_update_check_respects_ttl(paths):
    set_update_check(paths, True)
    check_for_update(paths, current_version="2.0.0", now_s=1_000,
                     fetch=lambda url: {"tag_name": "v2.1.0"})
    calls = []
    check_for_update(paths, current_version="2.0.0", now_s=1_000 + 60,
                     fetch=lambda url: calls.append(1) or {"tag_name": "v9.0.0"})
    assert calls == []  # within 24h

def test_update_check_failures_are_silent(paths):
    set_update_check(paths, True)
    def boom(_):
        raise OSError("offline")
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000, fetch=boom)
    assert status.message is None and status.newer is False
```

Amend `test_the_package_imports_no_networking_module`:

```python
ALLOWED_NETWORK_FILES = {pathlib.Path("shambles/update_check.py")}
# skip banned hits when source.resolve() matches an allowed file
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement settings + update_check** (stdlib `json` + `urllib.request` only inside `update_check.fetch_latest_tag` default `fetch`)

- [ ] **Step 4: PASS**

- [ ] **Step 5: Commit**

```bash
git add shambles/settings.py shambles/update_check.py shambles/paths.py \
  tests/test_settings.py tests/test_update_check.py tests/test_login.py
git commit -m "feat: opt-in GitHub Releases update check (default off)"
```

---

### Task 6: CLI + TUI wiring

**Files:**
- Modify: `shambles/app/cli.py` — add `config` subparser: `get update.check` / `set update.check true|false`
- Modify: `shambles/__main__.py` — USAGE lines for config; on `--version`, if check enabled and newer, print `status.message` on stderr or second line
- Modify: TUI application startup (wherever snapshot/header is built — find `run_tui` / dashboard compose) — if `check_for_update(…).message`, show a one-line dismissible banner/footer
- Create/modify: `tests/test_cli_config.py` and a focused TUI test if the suite has a pattern for banners

**Produces:** Users can run:

```bash
shambles config set update.check true
shambles config get update.check
```

- [ ] **Step 1: Failing CLI tests** (tmp `paths` via `--home` if CLI already supports it; else inject via env `SHAMBLES_HOME` — prefer extending existing `--home` if present, or use `Paths` only through service; add `--home` only if already there)

Inspect `cli.py` argparse: if no `--home`, test `settings` functions via unit tests already done and only smoke argparse with monkeypatch on `Paths.real`.

```python
def test_config_set_update_check_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr("shambles.paths.Paths.real",
                        classmethod(lambda cls: Paths.for_home(tmp_path)))
    # invoke cli main with argv ["config", "set", "update.check", "true"]
    assert update_check_enabled(Paths.for_home(tmp_path)) is True
```

- [ ] **Step 2: FAIL**

- [ ] **Step 3: Implement CLI + minimal TUI banner** (no auto-update action)

- [ ] **Step 4: PASS relevant tests + `.venv/bin/pytest -q` green**

- [ ] **Step 5: Commit**

```bash
git commit -m "feat: config CLI and UI banner for opt-in update notices"
```

---

### Task 7: Docs + roadmap

**Files:**
- Modify: `README.md` — Install section order: npm (primary, “when published”), curl/irm, pipx, Releases; document `config set update.check`; support matrix honesty
- Modify: `SECURITY.md` — note the single opt-in Releases exception
- Modify: `docs/superpowers/plans/2026-09-06-terminal-ui-roadmap.md` — insert this plan before npm (or after hardening); note npm plan’s “no version check” constraint is amended by the update-notice design for the Python app only (npm launcher still does not check)
- Modify: `docs/superpowers/specs/2026-09-08-install-and-update-notice-design.md` — Status: `IMPLEMENTED` when this plan’s verification passes (do this in the final commit of the plan execution, not early)
- Modify: `.github/workflows/release.yml` body template — curl/irm one-liners

- [ ] **Step 1: Edit docs**

- [ ] **Step 2: Commit**

```bash
git commit -m "docs: npm-primary install, curl scripts, opt-in update checks"
```

---

### Task 8: Full verification

- [ ] **Step 1: Run** `.venv/bin/pytest -q`  
  Expected: all green

- [ ] **Step 2: Manual dry-run** (optional): `SHAMBLES_SKIP_SMOKE=1 SHAMBLES_FORCE_ASSET=… bash scripts/install.sh` against the curl stub fixture

- [ ] **Step 3: Mark design spec status IMPLEMENTED; commit if dirty**

```bash
git commit -m "docs: mark install-and-update-notice design implemented"
```

---

## Spec coverage check

| Spec section | Task |
|---|---|
| §3 npm primary (docs only here) | 7 (+ deferred npm plan) |
| §3.2 curl/irm | 2, 3 |
| §4 shared assets / matrix | 1, 4 |
| §5 npm channel | deferred → existing npm plan |
| §6 installers | 2, 3 |
| §7 update notice | 5, 6 |
| §7.4 security AST | 5 |
| §8 pipeline | 4, 7 |
| §9 testing | 1–6, 8 |

## Handoff note for npm

After this plan’s Task 8 passes **and** platform-store hardening is done, execute [2026-09-06-npm-distribution.md](2026-09-06-npm-distribution.md). Amend that plan’s Global Constraint “Shambles performs no version check…” to: “The **npm launcher** performs no version check; the Python app may check GitHub Releases only when `update.check` is enabled.”
