# Multi-provider Shambles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend Shambles from a Claude-only account switcher to a two-provider one, where Codex is a full peer, Add Account offers a provider choice, and login opens the browser from inside the app.

**Architecture:** Two orthogonal layers per DD-4 — `stores/` knows *where* credential bytes live (platform axis), `providers/` knows *what they mean* (vendor axis), with the declarative half of each provider in `providers/<id>.json`. The core (`switcher`, `state`, `profiles`, `gui`) talks only to the `Provider` protocol and never learns a provider's name. Both layers already exist, tested, on `feat/provider-adapters`; this plan wires them into the core and adds the login handoff.

**Tech Stack:** Python 3.10+, stdlib only (`json`, `os`, `shutil`, `sys`, `time`, `pathlib`, `dataclasses`, `subprocess`, `threading`, `tkinter`). pytest 8 for tests. No third-party runtime dependencies — `pyproject.toml` `dependencies = []` is deliberate and must stay empty.

**Spec:** [`docs/superpowers/specs/2026-08-07-multi-provider-design.md`](../specs/2026-08-07-multi-provider-design.md)

## Global Constraints

- **No network.** No `socket`, no `urllib`, no `requests`. This is the load-bearing security claim in the README and must survive this change. `subprocess` is now permitted (DD-2 approves it explicitly); it is used only to spawn a vendor binary already on the user's PATH.
- **No new runtime dependencies.** `dependencies = []` in `pyproject.toml` stays empty. Tkinter ships with Python and cannot come from PyPI.
- **Every test runs against a synthetic home in `tmp_path`.** No test may read or write the real `~/.claude`, `~/.codex`, `~/.claude-profiles` or `~/.shambles`. `Paths.for_home()` is the only way to build paths in tests; `Paths.real()` is called in exactly one place (`gui.ShamblesApp.__init__`).
- **Credentials are written mode `0600`, directories `0700`**, via a temp file + `os.replace` so a half-written credential is never observable. `FileStore.write` already does this — do not reimplement it.
- **No token is ever displayed**, in any state, truncated or masked. DD-3.
- **Tracebacks never reach the user.** Every user-facing failure is a `ShamblesError` subclass whose `str()` reads as prose to someone who has never seen the source.
- **Never delete a credentials file automatically.** The only permitted deletions are pruning backups past 10, clearing the live credential when switching to a never-logged-in profile, and an explicitly confirmed profile removal.
- **Platform strings are `sys.platform` values** — `"linux"`, `"darwin"`, `"win32"` — matching the keys in each provider spec's `store` block.
- **Commit after every task.** Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `refactor:`). End every commit message with `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File Structure

### Created

| File | Responsibility |
|---|---|
| `shambles/stores/` | *(cherry-picked)* Where bytes live. `FileStore` is the only one wired; `KeychainStore`/`CredmanStore` ship unreferenced. |
| `shambles/providers/` | *(cherry-picked)* What bytes mean. `ClaudeProvider`, `CodexProvider`, `spec.py` loader, `<id>.json` specs. |
| `shambles/login.py` | Spawning the vendor's login command and streaming its output. The only module that knows `subprocess` exists. |
| `tests/test_login.py` | `login.py` against a fake vendor script on `PATH`. |
| `tests/test_store_migration.py` | The `~/.claude-profiles` → `~/.shambles/claude` hop. |

### Modified

| File | Change |
|---|---|
| `shambles/paths.py` | Provider-scoped. `.claude*` constants move into the specs; legacy paths retained for migration only. |
| `shambles/state.py` | `inspect(paths, provider)`. Kinds unchanged. `LEGACY_LAYOUT` moves to `migrate.py`. |
| `shambles/profiles.py` | Delegates to `provider.liveness()` / `.identity()`. `EXPIRY_WARN_DAYS` → `provider.warn_days`. |
| `shambles/switcher.py` | `provider` threaded through every entry point; store-mediated I/O; gains `restash_active`. |
| `shambles/migrate.py` | Gains the store-layout hop, independent of the pre-1.0 symlink hop. |
| `shambles/eject.py` | Iterates providers. |
| `shambles/gui.py` | Grouped list, per-group headings, provider radio in Add, new `LoginDialog`. |
| `shambles/configjson.py` | Keeps atomic write / backup / prune. The `~/.claude.json` splice moves to `ClaudeProvider.companion_write`. |
| `tests/helpers.py` | Provider-scoped builders; JWT and Codex `auth.json` fixtures. |
| `conftest.py` | `posix_only` marker; `fake_vendor` fixture. |

### Deleted

- `docs/providers/*.json` — removed by the cherry-pick; the specs now ship inside the package.

---

## Task 1: Cherry-pick the provider and store layers

The layers exist, tested, on `feat/provider-adapters`. Commit `1467f7a` is purely additive — it touches no existing module — and has been verified to apply to this branch **with no conflicts**. It also fixes packaging (subpackages, `package-data`, PyInstaller `--add-data`) and repoints the doc links itself, so there is nothing to fix up by hand.

**Files:**
- Create: `shambles/stores/{__init__,base,file,keychain,credman}.py`
- Create: `shambles/providers/{__init__,base,spec,claude,codex}.py`, `shambles/providers/{claude,codex}.json`
- Create: `tests/contract/{test_provider_contract,test_store_contract}.py`, `tests/fakes.py`, `tests/test_spec.py`
- Modify: `pyproject.toml`, `.github/workflows/release.yml`, `docs/design-decisions.md`
- Delete: `docs/providers/{claude,codex}.json`

**Interfaces:**
- Consumes: nothing.
- Produces: `providers.load(id, *, env=None) -> Provider`, `providers.all_providers(*, env=None) -> list[Provider]`, `providers.ids() -> list[str]`. Provider protocol: `.id`, `.display_name`, `.rotates`, `.warn_days`, `.spec`, `.store(home=, platform=)`, `.identity(blob, home=, profile_dir=, active=)`, `.liveness(blob, now_ms=)`, `.companion_read(home=)`, `.companion_write(data, home=)`, `.login_hint()`. Liveness states: `LIVE`, `CLOSING`, `CLOSED`, `ABSENT`, `UNKNOWN`, plus `NEEDS_LOGIN = frozenset({CLOSED, ABSENT})`. Store protocol: `.read() -> bytes|None`, `.write(bytes)`, `.delete()`, `.describe() -> str`, raising `StoreUnavailableError`.

- [ ] **Step 1: Confirm the cherry-pick still applies cleanly**

```bash
git merge-tree --write-tree --merge-base=$(git rev-parse 1467f7a^) HEAD 1467f7a
```

Expected: a single tree hash and exit 0. Any conflict output means the branch has moved — stop and re-check before continuing.

- [ ] **Step 2: Cherry-pick**

```bash
git cherry-pick 1467f7a
```

- [ ] **Step 3: Run the full suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS, ~264 tests (139 existing + 125 from the cherry-pick). No existing test changes behaviour — the commit touches no existing module.

- [ ] **Step 4: Confirm specs load as package data, not via `__file__`**

Run: `.venv/bin/python -c "from shambles import providers; print([p.display_name for p in providers.all_providers()])"`
Expected: `['Claude Code', 'Codex']`

This matters because the release binary is PyInstaller `--onefile`, where `__file__` points into a temporary extraction directory. `providers/spec.py` already uses `importlib.resources` for this reason.

---

## Task 2: Login metadata, the wide `identity()` signature, and two layer fixes

Four changes to the layers Task 1 brought in, all of them prerequisites for wiring the core onto them.

`login_hint()` returns prose. Driving the browser needs the binary name and argv, as data, so `login.py` never hardcodes a vendor.

The other three come from the Task 1 review:

1. **`identity()` must take `profile_dir` and `active`.** Commit `1467f7a` shipped the narrow `identity(self, blob, *, home)`. Tasks 5 and 6 call the wide form, and without it `ClaudeProvider.identity()` always reads the live `~/.claude.json` — so **every parked Claude profile displays the active account's email**. Task 6's `test_a_parked_claude_profile_shows_its_own_email_not_the_live_one` asserts the opposite. The correct implementation already exists in commit `01d6de8` as exactly three hunks touching only these modules.
2. **`FileStore.write` leaves a permission window.** It does `tmp.write_bytes(payload)` — creating the file at the default umask, typically `0644`, with the full plaintext credential in it — and only then `os.chmod(tmp, 0o600)`. The Global Constraint says a credential is never observable at loose permissions; that is currently false.
3. **`_write_json` in `claude.py` has no error handling.** It is what `companion_write()` writes through, and Task 7 calls `companion_write()` *outside* its `OSError` guard, so a disk-full or read-only filesystem surfaces as a raw traceback — violating "tracebacks never reach the user."

> **Ruling (human partner, pre-Task-2):** fixes 2 and 3 land here rather than being deferred. This overrides Task 1's "do not improve its content" and the Global Constraints sentence "FileStore.write already does this — do not reimplement it", which is false as written.

**Files:**
- Modify: `shambles/providers/claude.json`, `shambles/providers/codex.json`
- Modify: `shambles/providers/base.py`, `shambles/providers/claude.py`, `shambles/providers/codex.py`
- Modify: `shambles/stores/file.py`
- Test: `tests/test_spec.py`, `tests/contract/test_store_contract.py`

**Interfaces:**
- Consumes: Task 1's `Provider` protocol.
- Produces: `provider.login_binary() -> str`, `provider.login_command() -> list[str]` (used by Task 9's `login.py` and Task 12's GUI); and the wide `provider.identity(blob, *, home, profile_dir=None, active=False) -> Identity` (used by Tasks 5 and 6).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_spec.py`:

```python
import pytest

from shambles import providers


@pytest.mark.parametrize("provider_id, binary, command", [
    ("claude", "claude", ["claude", "auth", "login"]),
    ("codex", "codex", ["codex", "login"]),
])
def test_every_provider_declares_how_to_log_in(provider_id, binary, command):
    provider = providers.load(provider_id)
    assert provider.login_binary() == binary
    assert provider.login_command() == command


def test_login_command_starts_with_the_binary():
    """The binary is what gets probed on PATH; argv[0] must be the same thing,
    or availability and execution would disagree."""
    for provider in providers.all_providers():
        assert provider.login_command()[0] == provider.login_binary()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_spec.py -k login -v`
Expected: FAIL with `AttributeError: 'ClaudeProvider' object has no attribute 'login_binary'`

- [ ] **Step 3: Extend the specs**

In `shambles/providers/claude.json`, replace the `"login"` block:

```json
  "login": {
    "binary": "claude",
    "command": ["claude", "auth", "login"],
    "hint": "Run 'claude auth login' in a terminal.",
    "email_flag": "--email",
    "note": "claude auth login opens the browser and runs its own callback server. --email pre-populates the address on the login page."
  },
```

In `shambles/providers/codex.json`:

```json
  "login": {
    "binary": "codex",
    "command": ["codex", "login"],
    "hint": "Run 'codex login' in a terminal.",
    "email_flag": null
  },
```

- [ ] **Step 4: Add the accessors to both providers**

Add to `ClaudeProvider` in `shambles/providers/claude.py`, next to `login_hint`:

```python
    def login_binary(self) -> str:
        """The executable to probe on PATH before offering this provider."""
        return self.spec["login"]["binary"]

    def login_command(self) -> list[str]:
        """The vendor's own login command. It opens the browser itself and
        runs its own OAuth callback -- Shambles never handles a token in
        flight, which is what keeps DD-2's structural argument intact."""
        return list(self.spec["login"]["command"])
```

Add the identical two methods to `CodexProvider` in `shambles/providers/codex.py`. They read from `self.spec`, so the bodies are the same and neither class knows the other exists.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_spec.py -v`
Expected: PASS

- [ ] **Step 6: Commit the login metadata**

```bash
git add shambles/providers tests/test_spec.py
git commit -m "feat: declare each provider's login command as spec data

login_hint() returns prose for a human. Driving the browser needs the
binary name and argv as data, so login.py can spawn either vendor
without naming one.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Widen `identity()` to take `profile_dir` and `active`**

Take the implementation from commit `01d6de8`, which contains exactly this change for these three files and nothing else.

**Apply it as a patch, not a checkout.** `git checkout 01d6de8 -- <files>` replaces whole files with that commit's versions, and `01d6de8` branched before Step 6 existed — it would silently delete the `login_binary()` and `login_command()` methods you just added. Take only the three `identity()` hunks:

```bash
git diff 1467f7a 01d6de8 -- shambles/providers/base.py \
    shambles/providers/claude.py shambles/providers/codex.py > /tmp/identity.patch
git apply --check --verbose /tmp/identity.patch     # verify first
git apply /tmp/identity.patch
```

Expected from `--check`: three hunks apply, two of them reporting `offset 10 lines` (the offset is the login accessors you added above them — it is correct, not a warning). Then confirm:

```bash
git diff --stat
```

Expected: 3 files changed, 35 insertions, 10 deletions, and `git diff` shows **only** `identity()` signatures and bodies. If it shows anything touching `login_binary`, `login_command`, or any other method, stop and report BLOCKED.

`ClaudeProvider.identity()` gains the branch that matters:

```python
        if active or profile_dir is None:
            data = _read_json(specmod.expand(block["path"], home=home))
        else:
            data = _read_json(Path(profile_dir) / "account.json")
```

Confirm `from pathlib import Path` is present in `claude.py` after the checkout; the new body uses it.

- [ ] **Step 8: Write the failing tests for the two layer fixes**

Append to `tests/contract/test_store_contract.py`:

```python
import os

import pytest

from conftest import posix_modes_only
from shambles.stores import FileStore
from shambles.stores.base import StoreUnavailableError


@posix_modes_only
def test_a_credential_is_never_observable_at_loose_permissions(tmp_path, monkeypatch):
    """The temp file must be *created* 0600, not created at the umask and
    tightened afterwards. In between, a complete plaintext refresh token sits
    on disk world-readable -- a window, not a formality.

    Observed at the ``chmod`` call rather than at ``os.replace``: by replace
    time the mode is 0600 whichever way it got there, so that vantage point
    cannot tell a fixed implementation from a vulnerable one. The umask is
    pinned lax for the same reason -- under a strict umask the old code
    happened to create at 0600 and the window closed by luck.
    """
    observed = {}
    real_chmod = os.chmod

    def spy(path, mode, *args, **kwargs):
        try:
            stat = os.stat(path)
            # Regular files only: this call also tightens the parent
            # directory, and a directory's mode says nothing about whether
            # the credential inside it was ever exposed.
            if os_stat.S_ISREG(stat.st_mode) and stat.st_size:
                observed.setdefault("mode", oct(stat.st_mode)[-3:])
        except OSError:
            pass
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "chmod", spy)
    previous = os.umask(0o022)
    try:
        FileStore(tmp_path / "creds.json", 0o600).write(b'{"token": "secret"}')
    finally:
        os.umask(previous)

    assert observed.get("mode") == "600", (
        f"credential was on disk at {observed.get('mode')} before being "
        f"restricted to 0600")
```

This test needs `import stat as os_stat` alongside the existing `import os` at the top of the file.

**Verify it is not vacuous.** Temporarily revert `FileStore.write` to `tmp.write_bytes(payload)` + `os.chmod(...)` and confirm the test fails with `credential was on disk at 644 before being restricted to 0600`. A permission test that passes against the vulnerable code is worse than no test.

```python


@posix_modes_only
def test_the_parent_directory_is_created_owner_only(tmp_path):
    store = FileStore(tmp_path / "nested" / "creds.json", 0o600)
    store.write(b"{}")
    assert oct(os.stat(tmp_path / "nested").st_mode)[-3:] == "700"


def test_a_write_failure_is_a_shambles_error(tmp_path):
    """Never a bare OSError: the GUI renders ShamblesError only, and anything
    else reaches the user as a stderr traceback."""
    store = FileStore(tmp_path / "creds.json", 0o600)
    (tmp_path / "creds.json").mkdir()  # a directory where a file must go
    with pytest.raises(StoreUnavailableError):
        store.write(b"{}")
```

Append to `tests/test_spec.py`:

```python
def test_companion_write_failure_is_a_shambles_error(tmp_path, monkeypatch):
    """_write_json backs companion_write, which switcher.switch calls outside
    its OSError guard. An unguarded failure there is a raw traceback."""
    from shambles.errors import ShamblesError
    claude = providers.load("claude")

    def refuse(*_args, **_kwargs):
        raise OSError(28, "No space left on device")

    monkeypatch.setattr("shambles.providers.claude._write_json", refuse)
    with pytest.raises(ShamblesError):
        claude.companion_write({"oauthAccount": {}}, home=tmp_path)
```

- [ ] **Step 9: Run the new tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/contract/test_store_contract.py tests/test_spec.py -k "loose_permissions or owner_only or shambles_error" -v`
Expected: FAIL — the permission test reports `644`, and both error tests raise bare `OSError` rather than a `ShamblesError`.

- [ ] **Step 10: Fix `FileStore.write`**

In `shambles/stores/file.py`, replace the body of `write`. The temp file is created **already restricted**, so the credential is never on disk at a looser mode for any interval:

```python
    def write(self, payload: bytes) -> None:
        """Write via a same-directory temp file, then rename over the original.

        The temp file is opened with its final mode rather than chmod'd after
        the fact. Creating it at the umask and tightening it afterwards leaves
        the complete plaintext credential world-readable in between, which is
        a window, not a formality. Codex's own writer gets this half right --
        it sets 0600 only on creation, leaving an existing loose file loose --
        so this sets the mode every time.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.chmod(self.path.parent, 0o700)
            except OSError:
                pass  # Windows cannot express this; the file mode still applies
            tmp = self.path.with_name(self.path.name + TMP_SUFFIX)
            fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, self.mode)
            try:
                os.write(fd, payload)
            finally:
                os.close(fd)
            # O_CREAT honours the mode only when the file did not already
            # exist, so a leftover temp from a crashed run keeps its old mode
            # without this.
            os.chmod(tmp, self.mode)
            os.replace(tmp, self.path)
        except OSError as exc:
            raise StoreUnavailableError(
                f"Could not write {self.path}:\n{exc}") from exc
```

- [ ] **Step 11: Guard `_write_json`**

In `shambles/providers/claude.py`, add the import and wrap the body:

```python
from ..stores.base import StoreUnavailableError
```

```python
def _write_json(path: Path, data: dict) -> None:
    """Atomic, owner-only write of a companion file.

    Raises :class:`StoreUnavailableError` rather than ``OSError``:
    ``switcher.switch`` calls ``companion_write`` outside its own ``OSError``
    guard, so a bare one would reach the user as a stderr traceback and look
    like the switch silently did nothing.
    """
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".shambles-tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        try:
            os.write(fd, (json.dumps(data, indent=2) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except OSError as exc:
        raise StoreUnavailableError(f"Could not write {path}:\n{exc}") from exc
```

- [ ] **Step 12: Run the full suite**

Run: `.venv/bin/python -m pytest`
Expected: PASS. The suite must still be fully green at the end of this task — the accepted red window does not start until Task 3.

- [ ] **Step 13: Commit the layer fixes**

```bash
git add shambles/providers shambles/stores tests/
git commit -m "fix: close a credential permission window and a traceback path

Three corrections to the layers, all found by the Task 1 review and all
prerequisites for wiring the core onto them.

identity() regains the profile_dir/active parameters from 01d6de8.
Without them ClaudeProvider always reads the live ~/.claude.json, so
every parked profile would display the active account's email -- the
credential and the name beside it would disagree.

FileStore.write created its temp file at the umask, wrote the complete
plaintext credential into it, and only then chmod'd 0600. The file is
now opened with its final mode. A window is not a formality when the
bytes in it are a refresh token.

_write_json had no error handling at all, and switcher.switch calls
companion_write outside its OSError guard -- a disk-full would have
surfaced as a stderr traceback rather than a dialog.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Make `paths.py` provider-scoped

The store moves to `~/.shambles/<provider>/<Name>/`. The injectable-home structure survives untouched — it is what lets the whole suite run against `tmp_path`. What changes is that a provider id sits between the root and the profile name.

`claude_dir` and `claude_json` stay, but *only* for the pre-1.0 symlink migration and Claude's companion file. Live credential locations now come from `provider.store()`.

**Files:**
- Modify: `shambles/paths.py`
- Modify: `tests/helpers.py`
- Test: `tests/test_paths.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Paths.library_dir`, `.backup_dir`, `.provider_dir(pid)`, `.profile_dir(pid, name)`, `.credentials(pid, name)`, `.account(pid, name)`, `.active_marker(pid)`, `.ensure_store()`, `.ensure_provider(pid)`, `.ensure_profile(pid, name)`, `.legacy_profiles_dir`, `.legacy_active_marker`, `.legacy_backup_dir`, `.claude_dir`, `.claude_json`. Every later task uses these.

- [ ] **Step 1: Write the failing test**

Replace the body of `tests/test_paths.py` with:

```python
import os

import pytest

from conftest import posix_modes_only
from shambles.paths import Paths


def test_every_path_derives_from_the_injected_home(tmp_path):
    paths = Paths.for_home(tmp_path)
    assert paths.library_dir == tmp_path / ".shambles"
    assert paths.provider_dir("claude") == tmp_path / ".shambles" / "claude"
    assert paths.profile_dir("codex", "Work") == tmp_path / ".shambles" / "codex" / "Work"
    assert paths.credentials("codex", "Work") == \
        tmp_path / ".shambles" / "codex" / "Work" / "credentials.json"
    assert paths.account("claude", "Work") == \
        tmp_path / ".shambles" / "claude" / "Work" / "account.json"
    assert paths.active_marker("codex") == tmp_path / ".shambles" / "codex" / "active"
    assert paths.backup_dir == tmp_path / ".shambles" / ".backups"


def test_two_providers_never_collide(tmp_path):
    """The whole point of the provider hop: same profile name, different
    account, no shared bytes."""
    paths = Paths.for_home(tmp_path)
    assert paths.credentials("claude", "Work") != paths.credentials("codex", "Work")


def test_legacy_paths_point_at_the_old_layout(tmp_path):
    paths = Paths.for_home(tmp_path)
    assert paths.legacy_profiles_dir == tmp_path / ".claude-profiles"
    assert paths.legacy_active_marker == tmp_path / ".claude-profiles" / "active"
    assert paths.legacy_backup_dir == tmp_path / ".claude-profiles" / ".shambles-backups"


@posix_modes_only
def test_the_store_and_every_level_below_it_is_owner_only(tmp_path):
    """It holds OAuth refresh tokens. A plain mkdir under the usual 022 umask
    would leave these 755."""
    paths = Paths.for_home(tmp_path)
    paths.ensure_profile("codex", "Work")
    for directory in (paths.library_dir, paths.provider_dir("codex"),
                      paths.profile_dir("codex", "Work")):
        assert oct(os.stat(directory).st_mode)[-3:] == "700"


def test_ensure_profile_is_idempotent(tmp_path):
    paths = Paths.for_home(tmp_path)
    first = paths.ensure_profile("claude", "Work")
    second = paths.ensure_profile("claude", "Work")
    assert first == second and first.is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_paths.py -v`
Expected: FAIL with `AttributeError: 'Paths' object has no attribute 'library_dir'`

- [ ] **Step 3: Rewrite `shambles/paths.py`**

```python
"""Every path Shambles touches, derived from an injectable home root.

``Path.home()`` is called in exactly one place -- :meth:`Paths.real` -- so the
test suite can point the entire application at a temporary directory.

The store is provider-scoped: ``~/.shambles/<provider>/<Name>/``. It was
``~/.claude-profiles/<Name>/`` before there was a second provider, and that
name became a lie the moment it could hold Codex tokens. :mod:`shambles.migrate`
moves the old layout across.

Where a *live* credential lives is deliberately not here any more. That is a
provider-and-platform fact, and it comes from ``provider.store()``. What
remains below is Shambles' own storage, plus the two Claude paths the pre-1.0
migration and Claude's companion splice still need by name.
"""

import os
from dataclasses import dataclass
from pathlib import Path

LIBRARY_DIRNAME = ".shambles"
BACKUP_DIRNAME = ".backups"

#: Per-profile files. Small: tokens and, for providers whose identity lives
#: outside the credential, a stashed copy of it.
CREDENTIALS_NAME = "credentials.json"
ACCOUNT_NAME = "account.json"

#: Records which profile a provider's live login belongs to. One per provider.
ACTIVE_NAME = "active"

#: The v1.0 layout, read only while migrating out of it.
LEGACY_PROFILES_DIRNAME = ".claude-profiles"
LEGACY_BACKUP_DIRNAME = ".shambles-backups"

#: Claude-specific, and deliberately the only two vendor paths still named
#: here. ``claude_dir`` is needed to detect the pre-1.0 symlink layout;
#: ``claude_json`` is Claude's companion file. Everything else comes from a
#: provider spec.
CLAUDE_DIRNAME = ".claude"
CLAUDE_JSON_NAME = ".claude.json"


@dataclass(frozen=True)
class Paths:
    home: Path

    @classmethod
    def for_home(cls, home) -> "Paths":
        return cls(home=Path(home).expanduser())

    @classmethod
    def real(cls) -> "Paths":
        return cls.for_home(Path.home())

    # -- Shambles' own storage -------------------------------------------

    @property
    def library_dir(self) -> Path:
        return self.home / LIBRARY_DIRNAME

    @property
    def backup_dir(self) -> Path:
        return self.library_dir / BACKUP_DIRNAME

    def provider_dir(self, provider_id: str) -> Path:
        return self.library_dir / provider_id

    def profile_dir(self, provider_id: str, name: str) -> Path:
        return self.provider_dir(provider_id) / name

    def credentials(self, provider_id: str, name: str) -> Path:
        return self.profile_dir(provider_id, name) / CREDENTIALS_NAME

    def account(self, provider_id: str, name: str) -> Path:
        return self.profile_dir(provider_id, name) / ACCOUNT_NAME

    def active_marker(self, provider_id: str) -> Path:
        return self.provider_dir(provider_id) / ACTIVE_NAME

    # -- creation, locked down -------------------------------------------

    def ensure_store(self) -> Path:
        """Create the library root, readable only by its owner.

        It holds OAuth refresh tokens. The credential files are written 600
        regardless, but a plain ``mkdir`` under the usual 022 umask leaves the
        directories 755, so this closes that off too. On Windows ``chmod``
        cannot express this and is skipped -- the file modes still apply.
        """
        return _locked_mkdir(self.library_dir)

    def ensure_provider(self, provider_id: str) -> Path:
        self.ensure_store()
        return _locked_mkdir(self.provider_dir(provider_id))

    def ensure_profile(self, provider_id: str, name: str) -> Path:
        self.ensure_provider(provider_id)
        return _locked_mkdir(self.profile_dir(provider_id, name))

    # -- Claude's own locations ------------------------------------------

    @property
    def claude_dir(self) -> Path:
        return self.home / CLAUDE_DIRNAME

    @property
    def claude_json(self) -> Path:
        return self.home / CLAUDE_JSON_NAME

    # -- the v1.0 layout, read only during migration ---------------------

    @property
    def legacy_profiles_dir(self) -> Path:
        return self.home / LEGACY_PROFILES_DIRNAME

    @property
    def legacy_active_marker(self) -> Path:
        return self.legacy_profiles_dir / ACTIVE_NAME

    @property
    def legacy_backup_dir(self) -> Path:
        return self.legacy_profiles_dir / LEGACY_BACKUP_DIRNAME


def _locked_mkdir(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass
    return directory
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_paths.py -v`
Expected: PASS

- [ ] **Step 5: Update the test builders**

Rewrite `tests/helpers.py`. The Claude builders gain a provider id; the Codex builders and the JWT helper are new and are what every Codex test in later tasks depends on.

```python
"""Builders for synthetic homes. Never touches a real one."""

import base64
import json

NOW = 1_785_000_000_000  # fixed reference clock for every test
DAY_MS = 86_400_000


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# -- claude -------------------------------------------------------------

def account(email="a@example.com", org="Acme", uuid="uuid-a"):
    return {
        "emailAddress": email,
        "organizationName": org,
        "accountUuid": uuid,
        "displayName": org,
        "organizationRateLimitTier": "max_5x",
    }


def credentials(refresh_expires_ms=NOW + 30 * DAY_MS, access_token="tok"):
    return {
        "claudeAiOauth": {
            "accessToken": access_token,
            "refreshToken": "refresh",
            "expiresAt": NOW + 8 * 3_600_000,
            "refreshTokenExpiresAt": refresh_expires_ms,
            "scopes": ["user:inference"],
            "subscriptionType": "team",
            "rateLimitTier": "default_raven",
        }
    }


def make_claude_json(paths, email="a@example.com", extra=None):
    """A ~/.claude.json with account keys plus unrelated shared state."""
    data = {
        "numStartups": 42,
        "projects": {"/some/dir": {"allowedTools": []}},
        "oauthAccount": account(email),
        "cachedUsageUtilization": {
            "accountUuid": "uuid-a",
            "utilization": {"five_hour": {"utilization": 55}},
        },
        "machineID": "machine",
    }
    if extra:
        data.update(extra)
    write_json(paths.claude_json, data)
    return data


def make_live_claude_login(paths, refresh_expires_ms=NOW + 30 * DAY_MS):
    """Put a credentials file inside the shared ~/.claude."""
    path = paths.claude_dir / ".credentials.json"
    write_json(path, credentials(refresh_expires_ms))
    return path


# -- codex --------------------------------------------------------------

def jwt(claims: dict) -> str:
    """An unsigned JWT. Signatures are never verified -- see CodexProvider."""
    def segment(payload: dict) -> str:
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f'{segment({"alg": "none", "typ": "JWT"})}.{segment(claims)}.sig'


def codex_auth(email="a@example.com", name="A User", plan="plus",
               org="Acme", exp_ms=NOW + 10 * DAY_MS):
    """An ~/.codex/auth.json under OAuth, shaped as Codex writes it.

    Note ``id_token`` is a bare JWT string on disk even though it is a struct
    in the Rust source -- the parser trap the spec records.
    """
    return {
        "OPENAI_API_KEY": None,
        "auth_mode": "chatgpt",
        "tokens": {
            "access_token": jwt({"exp": exp_ms // 1000}),
            "id_token": jwt({
                "https://api.openai.com/profile": {"email": email, "name": name},
                "https://api.openai.com/auth": {
                    "chatgpt_plan_type": plan,
                    "organizations": [{"title": org}],
                },
            }),
            "refresh_token": "refresh-1",
            "account_id": "acct-1",
        },
        "last_refresh": "2026-08-01T00:00:00Z",
    }


def make_live_codex_login(paths, **kwargs):
    path = paths.home / ".codex" / "auth.json"
    write_json(path, codex_auth(**kwargs))
    return path


# -- provider-agnostic --------------------------------------------------

def make_profile(paths, provider_id, name, *, email=None, token=True,
                 refresh_expires_ms=NOW + 30 * DAY_MS, active=False):
    """Create a slim profile: a credential and, for Claude, a stashed identity."""
    directory = paths.ensure_profile(provider_id, name)
    if token:
        blob = (credentials(refresh_expires_ms) if provider_id == "claude"
                else codex_auth(email=email or "a@example.com",
                                exp_ms=refresh_expires_ms))
        write_json(paths.credentials(provider_id, name), blob)
    if email and provider_id == "claude":
        write_json(paths.account(provider_id, name),
                   {"oauthAccount": account(email), "stashed_at": NOW})
    if active:
        paths.ensure_provider(provider_id)
        paths.active_marker(provider_id).write_text(name + "\n", encoding="utf-8")
    return directory


def make_legacy_profile(paths, name, *, email=None, sessions=0):
    """A pre-1.0 profile: a full ~/.claude copy with its own history."""
    directory = paths.legacy_profiles_dir / name
    (directory / "projects" / "-some-project").mkdir(parents=True, exist_ok=True)
    write_json(directory / ".credentials.json", credentials())
    if email:
        write_json(directory / ".shambles.json",
                   {"oauthAccount": account(email), "stashed_at": NOW})
    for index in range(sessions):
        (directory / "projects" / "-some-project" /
         f"{name}-{index}.jsonl").write_text('{"type":"user"}\n', encoding="utf-8")
    return directory


def make_v1_profile(paths, name, *, email=None, token=True, active=False):
    """A v1.0 slim profile in ~/.claude-profiles/, the migration's input."""
    directory = paths.legacy_profiles_dir / name
    directory.mkdir(parents=True, exist_ok=True)
    if token:
        write_json(directory / "credentials.json", credentials())
    if email:
        write_json(directory / "account.json",
                   {"oauthAccount": account(email), "stashed_at": NOW})
    if active:
        paths.legacy_active_marker.write_text(name + "\n", encoding="utf-8")
    return directory
```

- [ ] **Step 6: Commit**

```bash
git add shambles/paths.py tests/test_paths.py tests/helpers.py
git commit -m "refactor!: make the profile store provider-scoped

~/.claude-profiles/<Name>/ becomes ~/.shambles/<provider>/<Name>/. The
old name became a lie the moment the store could hold Codex tokens.

Live credential locations leave this module entirely -- those are a
provider-and-platform fact and now come from provider.store(). Only
~/.claude and ~/.claude.json remain by name, for the pre-1.0 symlink
check and Claude's companion splice.

Migration lands in the next commit. The rest of the tree is broken
until the provider argument is threaded through.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Migrate the v1.0 store to the provider-scoped layout

Existing users have profiles in `~/.claude-profiles/`. This hop copies them to `~/.shambles/claude/`. **Copies** — the source is left intact, matching how the v1.0 history merge and Eject behave: never make a refresh token unrecoverable as a side effect.

Independent of, and running after, the existing pre-1.0 symlink migration.

**Files:**
- Modify: `shambles/migrate.py`
- Test: `tests/test_store_migration.py`

**Interfaces:**
- Consumes: Task 3's `Paths`.
- Produces: `migrate.store_migration_needed(paths) -> bool`, `migrate.migrate_store(paths) -> StorePlan`, and `StorePlan(profiles: list[str], active: str|None, backups: int, source: Path, dest: Path)`. Task 11's GUI calls both at startup.

- [ ] **Step 1: Write the failing test**

Create `tests/test_store_migration.py`:

```python
import json

import pytest

from helpers import make_v1_profile
from shambles import migrate


def test_not_needed_when_there_is_no_old_store(paths):
    assert migrate.store_migration_needed(paths) is False


def test_not_needed_once_the_new_store_exists(paths):
    """Having migrated already is not a reason to migrate again, even though
    the source is deliberately left on disk."""
    make_v1_profile(paths, "Work")
    paths.ensure_store()
    assert migrate.store_migration_needed(paths) is False


def test_needed_when_only_the_old_store_exists(paths):
    make_v1_profile(paths, "Work")
    assert migrate.store_migration_needed(paths) is True


def test_profiles_land_under_the_claude_provider(paths):
    make_v1_profile(paths, "Work", email="w@example.com", active=True)
    make_v1_profile(paths, "Personal", email="p@example.com")

    plan = migrate.migrate_store(paths)

    assert sorted(plan.profiles) == ["Personal", "Work"]
    assert plan.active == "Work"
    assert paths.credentials("claude", "Work").is_file()
    assert paths.account("claude", "Personal").is_file()
    assert paths.active_marker("claude").read_text(encoding="utf-8").strip() == "Work"


def test_the_credential_is_copied_byte_for_byte(paths):
    """The whole product promise. A migration that alters a refresh token
    costs the user a verification email."""
    make_v1_profile(paths, "Work")
    before = (paths.legacy_profiles_dir / "Work" / "credentials.json").read_bytes()

    migrate.migrate_store(paths)

    assert paths.credentials("claude", "Work").read_bytes() == before


def test_the_old_store_is_left_untouched(paths):
    make_v1_profile(paths, "Work", email="w@example.com", active=True)

    migrate.migrate_store(paths)

    assert (paths.legacy_profiles_dir / "Work" / "credentials.json").is_file()
    assert paths.legacy_active_marker.is_file()


def test_backups_come_across(paths):
    make_v1_profile(paths, "Work")
    paths.legacy_backup_dir.mkdir(parents=True, exist_ok=True)
    (paths.legacy_backup_dir / "claude.json.1785000000000").write_text("{}", encoding="utf-8")

    plan = migrate.migrate_store(paths)

    assert plan.backups == 1
    assert (paths.backup_dir / "claude.json.1785000000000").is_file()


def test_running_twice_changes_nothing(paths):
    make_v1_profile(paths, "Work", email="w@example.com", active=True)
    migrate.migrate_store(paths)
    paths.credentials("claude", "Work").write_text('{"edited": true}', encoding="utf-8")

    migrate.migrate_store(paths)

    assert json.loads(paths.credentials("claude", "Work").read_text()) == {"edited": True}


def test_a_marker_naming_a_missing_profile_is_not_carried_over(paths):
    """A stale marker in the old store must not become a stale marker in the
    new one -- MISSING_PROFILE would then be reported on a fresh layout."""
    make_v1_profile(paths, "Work")
    paths.legacy_active_marker.write_text("Ghost\n", encoding="utf-8")

    plan = migrate.migrate_store(paths)

    assert plan.active is None
    assert not paths.active_marker("claude").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_store_migration.py -v`
Expected: FAIL with `AttributeError: module 'shambles.migrate' has no attribute 'store_migration_needed'`

- [ ] **Step 3: Add the hop to `shambles/migrate.py`**

Append to the module, and add `from .paths import ACCOUNT_NAME, CREDENTIALS_NAME` to the imports:

```python
#: The provider every v1.0 profile belongs to. There was only one.
V1_PROVIDER = "claude"

#: Files a v1.0 profile could hold. Anything else in there was not ours.
V1_PROFILE_FILES = (CREDENTIALS_NAME, ACCOUNT_NAME)


@dataclass
class StorePlan:
    profiles: list = field(default_factory=list)
    active: str | None = None
    backups: int = 0
    source: Path | None = None
    dest: Path | None = None


def store_migration_needed(paths) -> bool:
    """Whether a v1.0 store exists and has not been migrated yet.

    The presence of ``~/.shambles`` is the "already done" signal, deliberately
    rather than the absence of the old store: the migration copies, so the old
    store is still there afterwards and would otherwise retrigger forever.
    """
    return paths.legacy_profiles_dir.is_dir() and not paths.library_dir.exists()


def migrate_store(paths) -> StorePlan:
    """Copy ~/.claude-profiles/<Name>/ to ~/.shambles/claude/<Name>/.

    Copies rather than moves. Every profile directory holds a refresh token
    recoverable only through a fresh verification email, so the old store stays
    on disk for the user to remove once they are satisfied -- the same posture
    as the pre-1.0 history merge and as Eject.

    Never overwrites: a file already present in the new store wins, which is
    what makes running this twice a no-op.
    """
    plan = StorePlan(source=paths.legacy_profiles_dir,
                     dest=paths.library_dir)
    if not paths.legacy_profiles_dir.is_dir():
        return plan

    paths.ensure_provider(V1_PROVIDER)

    for entry in sorted(paths.legacy_profiles_dir.iterdir()):
        if not entry.is_dir() or entry.name.startswith("."):
            continue
        paths.ensure_profile(V1_PROVIDER, entry.name)
        plan.profiles.append(entry.name)
        for filename in V1_PROFILE_FILES:
            source = entry / filename
            dest = paths.profile_dir(V1_PROVIDER, entry.name) / filename
            if source.is_file() and not dest.exists():
                shutil.copy2(source, dest)
                _lock_down(dest)

    # A marker naming a profile that did not come across would surface as
    # MISSING_PROFILE on a brand-new layout, which is a confusing thing to
    # greet someone with after an automatic migration.
    marked = None
    if paths.legacy_active_marker.is_file():
        marked = paths.legacy_active_marker.read_text(encoding="utf-8").strip() or None
    if marked in plan.profiles:
        plan.active = marked
        if not paths.active_marker(V1_PROVIDER).exists():
            paths.active_marker(V1_PROVIDER).write_text(
                marked + "\n", encoding="utf-8")

    if paths.legacy_backup_dir.is_dir():
        paths.backup_dir.mkdir(parents=True, exist_ok=True)
        for snapshot in sorted(paths.legacy_backup_dir.glob("claude.json.*")):
            dest = paths.backup_dir / snapshot.name
            if not dest.exists():
                shutil.copy2(snapshot, dest)
                plan.backups += 1

    return plan


def _lock_down(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_store_migration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shambles/migrate.py tests/test_store_migration.py
git commit -m "feat: migrate the v1.0 store into the provider-scoped layout

~/.claude-profiles/<Name>/ -> ~/.shambles/claude/<Name>/, copying rather
than moving. Every profile holds a refresh token recoverable only
through a fresh verification email, so the old store stays on disk.

Presence of ~/.shambles is the 'already done' signal, not absence of the
old store -- copying means the source survives and would otherwise
retrigger the migration forever.

A marker naming a profile that did not come across is dropped rather
than carried, so an automatic migration cannot greet the user with
MISSING_PROFILE on a brand-new layout.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Make `state.py` report one State per provider

The state machine — `MANAGED` / `UNMANAGED` / `DRIFTED` / `MISSING_PROFILE` / `UNKNOWN` — is already generic, exactly as DD-4 says. Two things change: identity is read through the provider (so Codex's JWT works), and `LEGACY_LAYOUT` leaves, because a pre-1.0 symlink is a Claude-only concern that `migrate.py` already owns.

**Files:**
- Modify: `shambles/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: Task 1's `Provider`, Task 3's `Paths`.
- Produces: `state.inspect(paths, provider, *, platform=sys.platform) -> State`, `State(kind, provider, profile, live_email, expected_email)`, `state.read_active(paths, pid)`, `state.write_active(paths, pid, name)`, `state.profile_names(paths, pid)`, `state.config_dir_override(provider, *, home, env=None)`. Tasks 7, 10, 11 all consume these.

- [ ] **Step 1: Write the failing test**

Replace `tests/test_state.py` with:

```python
import pytest

from helpers import (make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile)
from shambles import providers, state


@pytest.fixture
def claude():
    return providers.load("claude")


@pytest.fixture
def codex():
    return providers.load("codex")


def test_no_profiles_reads_as_unmanaged(paths, claude):
    assert state.inspect(paths, claude, platform="linux").kind == state.UNMANAGED


def test_a_marked_profile_matching_the_live_login_is_managed(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    current = state.inspect(paths, claude, platform="linux")

    assert current.kind == state.MANAGED
    assert current.profile == "Work"
    assert current.live_email == "w@example.com"


def test_a_manual_login_elsewhere_reads_as_drifted(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="someone@else.com")

    current = state.inspect(paths, claude, platform="linux")

    assert current.kind == state.DRIFTED
    assert current.live_email == "someone@else.com"
    assert current.expected_email == "w@example.com"


def test_a_marker_naming_a_deleted_profile_is_surfaced(paths, claude):
    paths.ensure_provider("claude")
    state.write_active(paths, "claude", "Ghost")

    current = state.inspect(paths, claude, platform="linux")

    assert current.kind == state.MISSING_PROFILE
    assert current.profile == "Ghost"


def test_profiles_but_no_marker_reads_as_unknown(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com")
    assert state.inspect(paths, claude, platform="linux").kind == state.UNKNOWN


def test_codex_identity_comes_from_the_token(paths, codex):
    """No sidecar, no splice: the JWT is the whole story."""
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)
    make_live_codex_login(paths, email="c@example.com")

    current = state.inspect(paths, codex, platform="linux")

    assert current.kind == state.MANAGED
    assert current.live_email == "c@example.com"


def test_each_provider_has_its_own_active_profile(paths, claude, codex):
    """Two providers, two independent markers. Neither can shadow the other."""
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_live_codex_login(paths, email="c@example.com")

    assert state.inspect(paths, claude, platform="linux").profile == "Work"
    assert state.inspect(paths, codex, platform="linux").profile == "Side"


def test_config_dir_override_is_reported_per_provider(paths, claude, codex):
    env = {"CODEX_HOME": "/somewhere/else"}
    assert state.config_dir_override(claude, home=paths.home, env=env) is None
    assert state.config_dir_override(codex, home=paths.home, env=env) == "/somewhere/else"


def test_pointing_the_variable_at_the_default_is_not_an_override(paths, codex):
    """Setting it explicitly to where it already points changes nothing and
    must not raise a false alarm."""
    env = {"CODEX_HOME": str(paths.home / ".codex")}
    assert state.config_dir_override(codex, home=paths.home, env=env) is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_state.py -v`
Expected: FAIL with `TypeError: inspect() takes 1 positional argument but 2 were given`

- [ ] **Step 3: Rewrite `shambles/state.py`**

```python
"""Which account is logged in for one provider, and whether Shambles knows it.

The active profile is recorded in ``~/.shambles/<provider>/active`` and then
*verified* against the identity actually present in the provider's own store,
so a login performed outside Shambles is detected rather than silently
mistrusted.

One provider at a time. Two providers have two independent active profiles and
no operation on one can affect the other, which is why every function here
takes a provider rather than looping over them.
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .providers import spec as specmod

#: The marker names a profile, and the live identity matches it.
MANAGED = "managed"
#: No profiles exist yet for this provider.
UNMANAGED = "unmanaged"
#: A profile is marked active but is no longer on disk.
MISSING_PROFILE = "missing-profile"
#: The live login belongs to some account other than the marked profile,
#: which is what a manual login looks like from here.
DRIFTED = "drifted"
#: Profiles exist but none is marked active.
UNKNOWN = "unknown"


@dataclass(frozen=True)
class State:
    kind: str
    provider: str | None = None
    profile: str | None = None
    #: Email of whoever is actually logged in, regardless of the marker.
    live_email: str | None = None
    #: Email the marked profile expects, when that differs from live_email.
    expected_email: str | None = None


def config_dir_override(provider, *, home, env=None) -> str | None:
    """The foreign config directory this provider's environment points at.

    Returns ``None`` when unset, empty, or pointing at the very directory the
    provider uses by default -- setting it explicitly to its own default
    changes nothing and must not raise a false alarm.

    Only a terminal is affected: neither VS Code extension host inherits shell
    environment variables, which is why this tool exists at all.
    """
    env = os.environ if env is None else env
    block = provider.spec.get("config_dir") or {}
    name = block.get("env")
    raw = env.get(name, "").strip() if name else ""
    if not raw:
        return None
    default = specmod.expand(block.get("default", ""), home=home)
    try:
        if Path(raw).expanduser().resolve() == Path(default).resolve():
            return None
    except OSError:
        return raw
    return raw


def read_active(paths, provider_id: str) -> str | None:
    try:
        name = paths.active_marker(provider_id).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return name or None


def write_active(paths, provider_id: str, name: str | None) -> None:
    paths.ensure_provider(provider_id)
    if name is None:
        paths.active_marker(provider_id).unlink(missing_ok=True)
        return
    paths.active_marker(provider_id).write_text(name + "\n", encoding="utf-8")


def profile_names(paths, provider_id: str) -> list[str]:
    """Directories under one provider's store that hold a profile.

    A directory counts even with no credential file: that is exactly the state
    of a profile added but not yet logged in.
    """
    try:
        entries = sorted(p for p in paths.provider_dir(provider_id).iterdir()
                         if p.is_dir())
    except OSError:
        return []
    return [p.name for p in entries if not p.name.startswith(".")]


def live_email(paths, provider, *, platform: str) -> str | None:
    """Who the provider's live store says is signed in."""
    try:
        blob = provider.store(home=paths.home, platform=platform).read()
    except OSError:
        return None
    return provider.identity(blob, home=paths.home, active=True).email


def profile_email(paths, provider, name: str) -> str | None:
    """Who a stashed profile belongs to."""
    directory = paths.profile_dir(provider.id, name)
    try:
        blob = paths.credentials(provider.id, name).read_bytes()
    except OSError:
        blob = None
    return provider.identity(blob, home=paths.home, profile_dir=directory,
                             active=False).email


def inspect(paths, provider, *, platform: str = sys.platform) -> State:
    """Classify one provider's login without touching anything."""
    names = profile_names(paths, provider.id)
    marked = read_active(paths, provider.id)
    live = live_email(paths, provider, platform=platform)

    # A marker naming a profile that is gone matters more than the store being
    # empty -- otherwise deleting the last profile reads as a clean unmanaged
    # machine and the stale marker is never surfaced.
    if marked is not None and marked not in names:
        return State(MISSING_PROFILE, provider.id, profile=marked, live_email=live)
    if not names:
        return State(UNMANAGED, provider.id, live_email=live)
    if marked is None:
        return State(UNKNOWN, provider.id, live_email=live)

    expected = profile_email(paths, provider, marked)
    # Only call it drift when both sides actually name someone. A profile that
    # has never been logged into has no expectation to violate.
    if expected and live and expected != live:
        return State(DRIFTED, provider.id, profile=marked, live_email=live,
                     expected_email=expected)

    return State(MANAGED, provider.id, profile=marked, live_email=live or expected)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shambles/state.py tests/test_state.py
git commit -m "refactor!: report one State per provider

The state machine was already generic, as DD-4 says. What changes is
that identity now comes through provider.identity(), so Codex's JWT
path works without the module learning a vendor name.

LEGACY_LAYOUT leaves: a pre-1.0 symlink is a Claude-only concern that
migrate.py already owns, and it was never a per-provider state.

config_dir_override generalises to the spec's config_dir.env, so it
warns on CODEX_HOME as well as CLAUDE_CONFIG_DIR.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Make `profiles.py` delegate to the provider

`token_state` and `EXPIRY_WARN_DAYS` are replaced by `provider.liveness()` and `provider.warn_days`. DD-1 requires per-provider thresholds: Claude's window is ~4 days against Codex's ~10, so one shared constant cannot serve both.

**Files:**
- Modify: `shambles/profiles.py`
- Test: `tests/test_profiles.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 5.
- Produces: `Profile(name, provider, path, active, email, org, plan, liveness)`, `profiles.discover(paths, provider, active_name, now_ms, *, platform=sys.platform)`, `profiles.expiry_label(profile)`, `profiles.expiry_severity(profile)`, `profiles.warning(profile)`, `profiles.validate_profile_name(name, existing)`. Task 11's GUI renders straight off these.

- [ ] **Step 1: Write the failing test**

Replace `tests/test_profiles.py` with:

```python
import pytest

from helpers import DAY_MS, NOW, make_claude_json, make_profile
from shambles import profiles, providers
from shambles.errors import ProfileNameError
from shambles.providers import ABSENT, CLOSED, CLOSING, LIVE


@pytest.fixture
def claude():
    return providers.load("claude")


@pytest.fixture
def codex():
    return providers.load("codex")


def test_discovery_is_case_insensitively_sorted(paths, claude):
    for name in ("zeta", "Alpha", "beta"):
        make_profile(paths, "claude", name, email=f"{name}@example.com")
    found = profiles.discover(paths, claude, None, NOW, platform="linux")
    assert [p.name for p in found] == ["Alpha", "beta", "zeta"]


def test_a_profile_carries_its_provider(paths, codex):
    make_profile(paths, "codex", "Work", email="c@example.com")
    found = profiles.discover(paths, codex, None, NOW, platform="linux")
    assert found[0].provider == "codex"


def test_the_active_profile_is_flagged(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_claude_json(paths, email="w@example.com")

    found = profiles.discover(paths, claude, "Work", NOW, platform="linux")

    assert [(p.name, p.active) for p in found] == [("Personal", False), ("Work", True)]


def test_a_parked_claude_profile_shows_its_own_email_not_the_live_one(paths, claude):
    """~/.claude.json describes only the account signed in right now. Reading
    it for a parked profile would label every row with the active email."""
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_claude_json(paths, email="w@example.com")

    found = {p.name: p.email for p in
             profiles.discover(paths, claude, "Work", NOW, platform="linux")}

    assert found == {"Work": "w@example.com", "Personal": "p@example.com"}


def test_codex_email_comes_out_of_the_jwt(paths, codex):
    make_profile(paths, "codex", "Work", email="c@example.com")
    found = profiles.discover(paths, codex, None, NOW, platform="linux")
    assert found[0].email == "c@example.com"
    assert found[0].plan == "plus"


@pytest.mark.parametrize("days, state, label", [
    (30, LIVE, "30d"),
    (2, CLOSING, "2d"),
    (0, CLOSING, "today"),
    (-3, CLOSED, "expired 3d ago"),
])
def test_the_countdown_reads_from_the_token(paths, claude, days, state, label):
    make_profile(paths, "claude", "Work", email="w@example.com",
                 refresh_expires_ms=NOW + days * DAY_MS)
    found = profiles.discover(paths, claude, None, NOW, platform="linux")[0]
    assert found.liveness.state == state
    assert profiles.expiry_label(found) == label


def test_a_profile_with_no_token_is_absent_not_expired(paths, claude):
    """Added but never logged into. Distinct from a lapsed window, and the
    difference is the whole reason an expired token is never deleted."""
    make_profile(paths, "claude", "Work", token=False)
    found = profiles.discover(paths, claude, None, NOW, platform="linux")[0]
    assert found.liveness.state == ABSENT
    assert profiles.expiry_label(found) is None
    assert profiles.warning(found) is not None


def test_the_warn_threshold_is_per_provider(claude, codex):
    """DD-1: Claude's window is ~4 days against Codex's ~10, so one shared
    constant cannot serve both."""
    assert claude.warn_days != codex.warn_days


def test_a_name_colliding_case_insensitively_is_refused():
    with pytest.raises(ProfileNameError):
        profiles.validate_profile_name("work", ["Work"])


@pytest.mark.parametrize("bad", ["", "  ", ".", "..", ".hidden", "a/b", "a:b"])
def test_unusable_names_are_refused(bad):
    with pytest.raises(ProfileNameError):
        profiles.validate_profile_name(bad, [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_profiles.py -v`
Expected: FAIL with `TypeError: discover() got an unexpected keyword argument 'platform'`

- [ ] **Step 3: Rewrite `shambles/profiles.py`**

```python
"""Discovering profiles and working out who each one belongs to.

Everything provider-specific -- what a token means, where identity lives, when
a window closes -- is delegated. This module decides ordering, naming rules,
and how a computed liveness is worded for the UI, all of which are the same
for every vendor.
"""

import sys
from dataclasses import dataclass
from pathlib import Path

from . import state
from .errors import ProfileNameError
from .providers import ABSENT, CLOSED, CLOSING, NEEDS_LOGIN, Liveness

INVALID_NAME_CHARS = set('/\\:*?"<>|')

#: How loudly the UI draws the countdown chip.
EXPIRY_OK = "ok"
EXPIRY_SOON = "soon"
EXPIRY_GONE = "gone"

SEVERITY = {CLOSING: EXPIRY_SOON, CLOSED: EXPIRY_GONE}

WARNINGS = {
    ABSENT: "No token here yet. Switch to this profile and log in.",
    CLOSED: "Refresh window closed — switch to this profile and log in again.",
}


@dataclass(frozen=True)
class Profile:
    name: str
    provider: str
    path: Path
    active: bool
    email: str | None
    org: str | None
    plan: str | None
    liveness: Liveness


def warning(profile: Profile) -> str | None:
    """The ⚠ tooltip for a profile that cannot be used as-is."""
    return WARNINGS.get(profile.liveness.state)


def expiry_label(profile: Profile) -> str | None:
    """Short countdown for the UI, e.g. ``"29d"`` or ``"expired 3d ago"``.

    ``None`` for a profile with no token and for one whose expiry could not be
    determined -- the VS Code bundle writes Claude credentials without the
    field, and inventing a number there would be worse than showing none.
    """
    days = profile.liveness.days_left
    if days is None:
        return None
    if days < 0:
        return f"expired {abs(days)}d ago"
    if days == 0:
        return "today"
    return f"{days}d"


def expiry_severity(profile: Profile) -> str | None:
    if profile.liveness.days_left is None:
        return None
    return SEVERITY.get(profile.liveness.state, EXPIRY_OK)


def needs_login(profile: Profile) -> bool:
    return profile.liveness.state in NEEDS_LOGIN


def list_profile_names(paths, provider_id: str) -> list[str]:
    """Profile directories, case-insensitively sorted for display."""
    return sorted(state.profile_names(paths, provider_id), key=str.casefold)


def discover(paths, provider, active_name: str | None, now_ms: int, *,
             platform: str = sys.platform) -> list[Profile]:
    found = []
    for name in list_profile_names(paths, provider.id):
        directory = paths.profile_dir(provider.id, name)
        try:
            blob = paths.credentials(provider.id, name).read_bytes()
        except OSError:
            blob = None

        is_active = (name == active_name)
        identity = provider.identity(blob, home=paths.home,
                                     profile_dir=directory, active=is_active)
        found.append(Profile(
            name=name,
            provider=provider.id,
            path=directory,
            active=is_active,
            email=identity.email,
            org=identity.org,
            plan=identity.plan,
            liveness=provider.liveness(blob, now_ms=now_ms),
        ))
    return found


def validate_profile_name(name, existing) -> str:
    """Return the trimmed name, or raise :class:`ProfileNameError`."""
    cleaned = (name or "").strip()
    if not cleaned:
        raise ProfileNameError("Profile name cannot be empty.")
    if cleaned in (".", ".."):
        raise ProfileNameError("Profile name cannot be '.' or '..'.")
    if cleaned.startswith("."):
        raise ProfileNameError("Profile name cannot start with a dot.")
    bad = sorted(set(cleaned) & INVALID_NAME_CHARS)
    if bad:
        raise ProfileNameError("Profile name cannot contain:  " + "  ".join(bad))
    lowered = cleaned.casefold()
    if any(str(other).casefold() == lowered for other in existing):
        raise ProfileNameError(f"A profile named '{cleaned}' already exists.")
    return cleaned
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_profiles.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shambles/profiles.py tests/test_profiles.py
git commit -m "refactor!: compute profile liveness through the provider

token_state and EXPIRY_WARN_DAYS go; provider.liveness() and
provider.warn_days replace them. DD-1 requires per-provider thresholds
-- Claude's window is roughly four days against Codex's ten, so one
shared constant renders everything amber for one of them.

Adds the ABSENT/CLOSED distinction to the UI vocabulary: 'never logged
in here' and 'window closed twelve days ago' are different problems with
different fixes, and conflating them is why an expired token is never
deleted.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Thread `provider` through `switcher.py`

The flow does not change — verify, back up, stash outgoing, restore incoming, splice, record. DD-4 identifies it as already generic. What changes is that each step goes through the provider and its store instead of hardcoded Claude paths.

The ordering guarantee is the product: **the outgoing login is stashed before the incoming one is installed**, so switching away can never strand an account.

**Files:**
- Modify: `shambles/switcher.py`
- Test: `tests/test_switch.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 5, 6.
- Produces: `switcher.now_ms()`, `.stash_live_login(paths, provider, name, *, platform, now_ms_fn, sleep)`, `.switch(paths, provider, target_name, *, platform, now_ms_fn, sleep) -> State`, `.save_current_account(...) -> str`, `.add_empty_account(...) -> str`, `.rename_profile(paths, provider, old, new, *, sleep) -> str`, `.remove_profile(paths, provider, name, *, platform)`, `.forget_active_marker(paths, provider)`. Tasks 10 and 11 call all of them.

- [ ] **Step 1: Write the failing test — the load-bearing one first, parametrized**

Replace `tests/test_switch.py` with:

```python
import json

import pytest

from helpers import (NOW, make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile)
from shambles import providers, state, switcher
from shambles.errors import AlreadyManagedError, ProfileNotFoundError
from shambles.providers import ABSENT

PROVIDER_IDS = ["claude", "codex"]


@pytest.fixture(params=PROVIDER_IDS)
def provider(request):
    return providers.load(request.param)


def seed_live(paths, provider, email):
    """Put a live login in place for whichever provider is under test."""
    if provider.id == "claude":
        make_claude_json(paths, email=email)
        return make_live_claude_login(paths)
    return make_live_codex_login(paths, email=email)


# -- the core promise ---------------------------------------------------

def test_credentials_survive_a_round_trip_unmodified(paths, provider):
    """Work -> Personal -> Work leaves the credential byte-identical.

    THE load-bearing test. If this regresses the tool stops solving the
    problem it exists for: a mutated refresh token costs a verification
    email, which is the entire thing being avoided. Parametrized over every
    provider, per DD-4 -- adding a provider means passing this suite.
    """
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    make_profile(paths, provider.id, "Personal", email="p@example.com")
    seed_live(paths, provider, "w@example.com")

    before = paths.credentials(provider.id, "Work").read_bytes()

    switcher.switch(paths, provider, "Personal", platform="linux", sleep=lambda _: None)
    switcher.switch(paths, provider, "Work", platform="linux", sleep=lambda _: None)

    assert paths.credentials(provider.id, "Work").read_bytes() == before


def test_the_outgoing_login_is_stashed_before_the_incoming_one_lands(paths, provider):
    """Switching away is never lossy, even to a profile with no token."""
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    make_profile(paths, provider.id, "Empty", token=False)
    live = seed_live(paths, provider, "w@example.com")
    original = live.read_bytes()

    switcher.switch(paths, provider, "Empty", platform="linux", sleep=lambda _: None)

    assert paths.credentials(provider.id, "Work").read_bytes() == original


def test_switching_to_a_never_logged_in_profile_clears_the_live_login(paths, provider):
    """Cleared, not left holding the previous account -- otherwise the vendor
    silently keeps using the account you just switched away from."""
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    make_profile(paths, provider.id, "Empty", token=False)
    seed_live(paths, provider, "w@example.com")

    switcher.switch(paths, provider, "Empty", platform="linux", sleep=lambda _: None)

    store = provider.store(home=paths.home, platform="linux")
    assert store.read() is None


def test_the_active_marker_follows_the_switch(paths, provider):
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    make_profile(paths, provider.id, "Personal", email="p@example.com")
    seed_live(paths, provider, "w@example.com")

    switcher.switch(paths, provider, "Personal", platform="linux", sleep=lambda _: None)

    assert state.read_active(paths, provider.id) == "Personal"


def test_switching_one_provider_leaves_the_other_alone(paths):
    claude, codex = providers.load("claude"), providers.load("codex")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_profile(paths, "codex", "Other", email="o@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)
    make_live_codex_login(paths, email="c@example.com")

    claude_before = (paths.claude_dir / ".credentials.json").read_bytes()
    switcher.switch(paths, codex, "Other", platform="linux", sleep=lambda _: None)

    assert (paths.claude_dir / ".credentials.json").read_bytes() == claude_before
    assert state.read_active(paths, "claude") == "Work"


# -- claude's companion splice -----------------------------------------

def test_the_splice_preserves_every_unrelated_key(paths):
    """~/.claude.json holds every project, MCP server and machine ID. A switch
    replaces two keys and nothing else."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    switcher.switch(paths, claude, "Personal", platform="linux", sleep=lambda _: None)

    config = json.loads(paths.claude_json.read_text(encoding="utf-8"))
    assert config["numStartups"] == 42
    assert config["machineID"] == "machine"
    assert config["projects"] == {"/some/dir": {"allowedTools": []}}
    assert config["oauthAccount"]["emailAddress"] == "p@example.com"


def test_an_unreadable_config_aborts_before_anything_moves(paths):
    """Splicing onto unparseable JSON would replace every project and MCP
    server with two keys. Refuse first, move nothing."""
    from shambles.errors import ConfigUnreadableError
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_live_claude_login(paths)
    paths.claude_json.write_text("{ this is not json", encoding="utf-8")

    live_before = (paths.claude_dir / ".credentials.json").read_bytes()

    with pytest.raises(ConfigUnreadableError):
        switcher.switch(paths, claude, "Personal", platform="linux", sleep=lambda _: None)

    assert (paths.claude_dir / ".credentials.json").read_bytes() == live_before
    assert state.read_active(paths, "claude") == "Work"


def test_codex_needs_no_companion_and_writes_none(paths):
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)
    make_profile(paths, "codex", "Other", email="o@example.com")
    make_live_codex_login(paths, email="c@example.com")

    switcher.switch(paths, codex, "Other", platform="linux", sleep=lambda _: None)

    assert not paths.claude_json.exists()


# -- guards -------------------------------------------------------------

def test_switching_to_a_missing_profile_is_refused(paths, provider):
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    with pytest.raises(ProfileNotFoundError):
        switcher.switch(paths, provider, "Ghost", platform="linux", sleep=lambda _: None)


def test_removing_the_active_profile_is_refused(paths, provider):
    """Enforced in code, not only by hiding the button. Hiding a control is
    not a safety property."""
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    with pytest.raises(AlreadyManagedError):
        switcher.remove_profile(paths, provider, "Work", platform="linux")


def test_a_name_escaping_the_store_is_refused(paths, provider):
    """remove_profile deletes a tree, so it re-checks rather than trusting how
    the name arrived."""
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    with pytest.raises(ProfileNotFoundError):
        switcher.remove_profile(paths, provider, "..", platform="linux")


def test_add_creates_an_empty_profile_and_activates_it(paths, provider):
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    seed_live(paths, provider, "w@example.com")

    switcher.add_empty_account(paths, provider, "Fresh", platform="linux",
                               sleep=lambda _: None)

    assert state.read_active(paths, provider.id) == "Fresh"
    assert provider.store(home=paths.home, platform="linux").read() is None


def test_saving_the_current_account_captures_the_live_login(paths, provider):
    live = seed_live(paths, provider, "w@example.com")

    switcher.save_current_account(paths, provider, "Work", platform="linux",
                                  sleep=lambda _: None)

    assert paths.credentials(provider.id, "Work").read_bytes() == live.read_bytes()
    assert state.read_active(paths, provider.id) == "Work"


def test_renaming_carries_the_active_marker(paths, provider):
    make_profile(paths, provider.id, "Work", email="w@example.com", active=True)
    switcher.rename_profile(paths, provider, "Work", "Job", sleep=lambda _: None)
    assert state.read_active(paths, provider.id) == "Job"
    assert paths.profile_dir(provider.id, "Job").is_dir()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_switch.py -v`
Expected: FAIL with `TypeError: switch() got an unexpected keyword argument 'platform'`

- [ ] **Step 3: Rewrite `shambles/switcher.py`**

```python
"""Switching accounts by swapping one credential, and nothing else.

Nothing but the login is account-scoped. Session history, plugins, settings
and project trust are machine-scoped and shared across every account, which is
how both vendors behave on their own.

Every function takes a provider. The *flow* below is identical for all of
them -- verify, back up, stash outgoing, restore incoming, splice, record --
and only its steps differ, which is exactly the split DD-4 describes.
"""

import shutil
import sys
import time

from . import configjson, profiles, retry, state
from .errors import (AlreadyManagedError, ProfileNotFoundError,
                     SwitchFailedError)
from .stores.base import StoreUnavailableError

NOTHING_TO_SAVE = (
    "There is no login to save — {store} has no credentials yet.\n\n"
    "Sign in with {provider} first, then save that account here."
)

SAVE_FIRST = (
    "Save your current account first.\n\n"
    "Otherwise the live login would be replaced with nothing and you would "
    "have to sign in again to get it back."
)

REMOVE_ACTIVE = (
    "'{name}' is the account you are signed in as.\n\n"
    "Switch to another profile first, then remove this one."
)


def now_ms() -> int:
    return int(time.time() * 1000)


def _store(paths, provider, platform):
    return provider.store(home=paths.home, platform=platform)


def stash_live_login(paths, provider, name, *, platform=sys.platform,
                     now_ms_fn=now_ms, sleep=time.sleep) -> None:
    """Capture whatever is logged in right now into profile ``name``."""
    paths.ensure_profile(provider.id, name)
    store = _store(paths, provider, platform)

    blob = retry.with_retry(store.read, f"read {store.describe()}", sleep=sleep)
    if blob is not None:
        _write_credential(paths, provider, name, blob, sleep=sleep)

    companion = provider.companion_read(home=paths.home)
    if companion:
        configjson.write_sidecar(paths.account(provider.id, name), companion,
                                 now_ms_fn())


def _write_credential(paths, provider, name, blob: bytes, *, sleep) -> None:
    """Write a credential into a profile, 0600, atomically.

    Retried: a running session, an antivirus scan or the Windows indexer can
    hold the file for a moment, and a single refusal is not a reason to fail
    the whole switch.
    """
    from .stores import FileStore
    destination = FileStore(paths.credentials(provider.id, name), 0o600)
    retry.with_retry(lambda: destination.write(blob),
                     f"write {paths.credentials(provider.id, name).name}",
                     sleep=sleep)


def switch(paths, provider, target_name: str, *, platform=sys.platform,
           now_ms_fn=now_ms, sleep=time.sleep):
    """Make ``target_name`` the logged-in account for one provider.

    Stashes the outgoing login, restores the incoming one, and writes the
    matching identity into the provider's companion file if it has one.
    Nothing outside the credential moves.
    """
    current = state.inspect(paths, provider, platform=platform)

    if not paths.profile_dir(provider.id, target_name).is_dir():
        raise ProfileNotFoundError(
            f"Profile '{target_name}' no longer exists on disk.")

    # Refuse before anything moves if the companion cannot be parsed. Writing
    # onto an unreadable config would replace the whole file with two keys.
    # A provider with no companion has nothing to check.
    companion_path = _companion_path(provider, paths)
    if companion_path is not None:
        configjson.load_for_write(companion_path)

    stamp = now_ms_fn()
    store = _store(paths, provider, platform)

    # Everything touching the filesystem lives inside one guard, so no path
    # out of here raises a bare OSError. The GUI renders ShamblesError only;
    # anything else reaches the user as a stderr traceback and looks like the
    # switch silently did nothing.
    try:
        if companion_path is not None:
            retry.with_retry(
                lambda: configjson.backup(companion_path, paths.backup_dir, stamp),
                f"back up {companion_path.name}", sleep=sleep)

        # Stash the outgoing login so switching away is never lossy. Skipped
        # when the marker points at a profile that is already gone.
        if current.profile and paths.profile_dir(provider.id, current.profile).is_dir():
            stash_live_login(paths, provider, current.profile, platform=platform,
                             now_ms_fn=lambda: stamp, sleep=sleep)

        incoming = paths.credentials(provider.id, target_name)
        if incoming.exists():
            blob = incoming.read_bytes()
            retry.with_retry(lambda: store.write(blob),
                             f"write {store.describe()}", sleep=sleep)
        else:
            # A profile never signed into: clear the login so the vendor
            # prompts for one rather than reusing the last account.
            retry.with_retry(store.delete, f"clear {store.describe()}", sleep=sleep)
    except StoreUnavailableError:
        raise
    except OSError as exc:
        raise SwitchFailedError(
            f"Could not update the login in {store.describe()}:\n{exc}\n\n"
            "Close any running sessions and try again.") from exc

    provider.companion_write(
        configjson.read_sidecar(paths.account(provider.id, target_name)),
        home=paths.home)
    state.write_active(paths, provider.id, target_name)
    return state.inspect(paths, provider, platform=platform)


def _companion_path(provider, paths):
    """Where this provider's companion file lives, or ``None`` if it has none."""
    from .providers import spec as specmod
    block = provider.spec.get("companion")
    if not block:
        return None
    return specmod.expand(block["path"], home=paths.home)


def save_current_account(paths, provider, name, *, platform=sys.platform,
                         now_ms_fn=now_ms, sleep=time.sleep) -> str:
    """Record the account that is logged in right now as a profile."""
    current = state.inspect(paths, provider, platform=platform)
    if current.kind == state.MANAGED:
        raise AlreadyManagedError(
            f"This login is already saved as '{current.profile}'.")

    store = _store(paths, provider, platform)
    if store.read() is None:
        raise AlreadyManagedError(NOTHING_TO_SAVE.format(
            store=store.describe(), provider=provider.display_name))

    name = profiles.validate_profile_name(
        name, state.profile_names(paths, provider.id))
    stash_live_login(paths, provider, name, platform=platform,
                     now_ms_fn=now_ms_fn, sleep=sleep)
    state.write_active(paths, provider.id, name)
    return name


def add_empty_account(paths, provider, name, *, platform=sys.platform,
                      now_ms_fn=now_ms, sleep=time.sleep) -> str:
    """Create a profile with no login and make it current."""
    current = state.inspect(paths, provider, platform=platform)
    store = _store(paths, provider, platform)
    if current.kind == state.UNMANAGED and store.read() is not None:
        raise AlreadyManagedError(SAVE_FIRST)

    name = profiles.validate_profile_name(
        name, state.profile_names(paths, provider.id))
    paths.ensure_profile(provider.id, name)
    result = switch(paths, provider, name, platform=platform,
                    now_ms_fn=now_ms_fn, sleep=sleep)
    return result.profile or name


def rename_profile(paths, provider, old_name: str, new_name: str, *,
                   sleep=time.sleep) -> str:
    if not paths.profile_dir(provider.id, old_name).is_dir():
        raise ProfileNotFoundError(f"Profile '{old_name}' does not exist.")

    existing = [n for n in state.profile_names(paths, provider.id) if n != old_name]
    new_name = profiles.validate_profile_name(new_name, existing)
    if new_name == old_name:
        return old_name

    try:
        paths.profile_dir(provider.id, old_name).rename(
            paths.profile_dir(provider.id, new_name))
    except OSError as exc:
        raise SwitchFailedError(f"Could not rename the profile:\n{exc}") from exc

    if state.read_active(paths, provider.id) == old_name:
        state.write_active(paths, provider.id, new_name)
    return new_name


def remove_profile(paths, provider, name: str, *, platform=sys.platform) -> None:
    """Delete a profile directory and the login inside it.

    Irreversible in the sense that matters: the refresh token goes with it, so
    that account needs a fresh login and its verification email to come back.

    Refuses the active profile even though the UI hides the control for it.
    Hiding a button is not a safety property.
    """
    current = state.inspect(paths, provider, platform=platform)
    if name == current.profile:
        raise AlreadyManagedError(REMOVE_ACTIVE.format(name=name))

    target = paths.profile_dir(provider.id, name)
    # A name like ".." resolves outside the store. validate_profile_name
    # blocks separators on the way in, but this deletes a tree, so it
    # re-checks rather than trusting how the name arrived.
    try:
        resolved = target.resolve()
        store_root = paths.provider_dir(provider.id).resolve()
    except OSError as exc:
        raise SwitchFailedError(f"Could not resolve '{name}':\n{exc}") from exc
    if resolved.parent != store_root or resolved == store_root:
        raise ProfileNotFoundError(f"'{name}' is not a profile.")
    if not target.is_dir():
        raise ProfileNotFoundError(f"Profile '{name}' does not exist.")

    try:
        shutil.rmtree(target)
    except OSError as exc:
        raise SwitchFailedError(
            f"Could not remove '{name}':\n{exc}\n\n"
            "Close any running sessions and try again.") from exc


def forget_active_marker(paths, provider) -> None:
    """Clear a marker pointing at a profile that no longer exists."""
    state.write_active(paths, provider.id, None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_switch.py -v`
Expected: PASS — 2 providers × the parametrized cases.

- [ ] **Step 5: Commit**

```bash
git add shambles/switcher.py tests/test_switch.py
git commit -m "feat!: switch accounts for any provider, not only Claude

The flow is untouched: verify, back up, stash outgoing, restore
incoming, splice, record. DD-4 was right that it was already generic --
only its steps were Claude-specific, and those now go through the
provider and its store.

test_credentials_survive_a_round_trip_unmodified is parametrized over
providers. It stops being a Claude test and becomes the first case every
provider must pass, which is what makes a third provider cheap.

The ordering guarantee is unchanged and still the product: the outgoing
login is stashed before the incoming one is installed, so switching away
can never strand an account.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 8: Re-stash rotating credentials after use

Codex rotates its refresh token on every use. A snapshot taken before a refresh is **dead** — the rotation invalidated the token it holds. Restoring it does not merely fail; it costs the user a verification email, which is the exact outcome this tool exists to prevent.

Invisible to the user, load-bearing for correctness. DD-3's "silent work must still be correct work".

**Files:**
- Modify: `shambles/switcher.py`
- Test: `tests/test_switch.py`

**Interfaces:**
- Consumes: Task 7.
- Produces: `switcher.restash_active(paths, provider, *, platform=sys.platform, now_ms_fn=now_ms) -> bool` — `True` when it wrote. Task 11's `gui.refresh()` calls it.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_switch.py`:

```python
# -- rotation -----------------------------------------------------------

def test_a_rotating_provider_restashes_a_refreshed_credential(paths):
    """Codex rotates on every use, so the stashed copy goes stale the moment
    the live one refreshes. Switching away would then write back a dead
    refresh token and cost a verification email."""
    from helpers import codex_auth, write_json
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)
    live = make_live_codex_login(paths, email="c@example.com")

    # The vendor refreshes during use, rotating the refresh token.
    rotated = codex_auth(email="c@example.com")
    rotated["tokens"]["refresh_token"] = "refresh-2"
    write_json(live, rotated)

    assert switcher.restash_active(paths, codex, platform="linux") is True

    stashed = json.loads(paths.credentials("codex", "Work").read_text())
    assert stashed["tokens"]["refresh_token"] == "refresh-2"


def test_restash_is_a_no_op_when_nothing_changed(paths):
    codex = providers.load("codex")
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)
    blob = paths.credentials("codex", "Work").read_bytes()
    (paths.home / ".codex").mkdir(parents=True, exist_ok=True)
    (paths.home / ".codex" / "auth.json").write_bytes(blob)

    assert switcher.restash_active(paths, codex, platform="linux") is False


def test_a_non_rotating_provider_is_never_restashed(paths):
    """Claude's refresh token does not rotate, so the live file drifting from
    the stash is normal and re-stashing would be pointless writes."""
    claude = providers.load("claude")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    assert switcher.restash_active(paths, claude, platform="linux") is False


def test_restash_does_nothing_without_an_active_profile(paths):
    codex = providers.load("codex")
    make_live_codex_login(paths, email="c@example.com")
    assert switcher.restash_active(paths, codex, platform="linux") is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_switch.py -k restash -v`
Expected: FAIL with `AttributeError: module 'shambles.switcher' has no attribute 'restash_active'`

- [ ] **Step 3: Add `restash_active` to `shambles/switcher.py`**

```python
def restash_active(paths, provider, *, platform=sys.platform,
                   now_ms_fn=now_ms) -> bool:
    """Refresh the stashed copy of a rotating provider's active credential.

    Returns whether anything was written.

    Codex replaces its refresh token on every use, so a snapshot taken before
    a refresh holds a token the server has already invalidated. Restoring one
    does not fail cleanly -- it silently breaks the account until the user
    logs in again, which is the single outcome this tool exists to prevent.

    A no-op for providers whose refresh token does not rotate: Claude's live
    file drifts from the stash constantly and harmlessly, and re-stashing it
    would be pure write amplification.

    Failures are swallowed. This runs on every window refresh as a background
    correction, and a locked file is a reason to try again next time, not to
    put a dialog in front of someone who did not ask for anything.
    """
    if not provider.rotates:
        return False

    name = state.read_active(paths, provider.id)
    if not name or not paths.profile_dir(provider.id, name).is_dir():
        return False

    try:
        live = _store(paths, provider, platform).read()
        if live is None:
            return False
        stashed_path = paths.credentials(provider.id, name)
        if stashed_path.exists() and stashed_path.read_bytes() == live:
            return False
        _write_credential(paths, provider, name, live, sleep=time.sleep)
    except (OSError, StoreUnavailableError, SwitchFailedError):
        return False

    companion = provider.companion_read(home=paths.home)
    if companion:
        configjson.write_sidecar(paths.account(provider.id, name), companion,
                                 now_ms_fn())
    return True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_switch.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shambles/switcher.py tests/test_switch.py
git commit -m "fix: re-stash rotating credentials before they go stale

Codex replaces its refresh token on every use, so a snapshot taken
before a refresh holds a token the server has already invalidated.
Restoring one does not fail cleanly -- it silently breaks the account
until the user logs in again, which is the one outcome this tool exists
to prevent.

A no-op for Claude, whose refresh token does not rotate. Failures are
swallowed: this runs on every window refresh as a background
correction, and a locked file is a reason to retry next time rather
than to interrupt someone who did not ask for anything.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 9: The login handoff

The only module that knows `subprocess` exists. It spawns the vendor's own login command — which opens the browser and runs its own OAuth callback server — and streams the output back so a fallback URL is visible when the browser cannot be opened (common under WSL and over SSH).

Shambles adds no OAuth code, opens no socket, and never handles a token in flight. That is what keeps DD-2's structural argument intact while changing its conclusion.

**Files:**
- Create: `shambles/login.py`
- Create: `tests/test_login.py`
- Modify: `conftest.py`

**Interfaces:**
- Consumes: Task 2's `provider.login_binary()` / `.login_command()`.
- Produces: `login.available(provider) -> bool`, `login.command(provider, *, email=None) -> list[str]`, `login.LoginProcess(command, *, popen=subprocess.Popen)` with `.start(on_line, on_exit)`, `.cancel(grace=5.0)`, `.running`, and `login.LoginUnavailableError`. Task 12's GUI drives all of it.

- [ ] **Step 1: Add the test fixtures**

Append to `conftest.py`:

```python
posix_only = pytest.mark.skipif(
    os.name == "nt",
    reason="fake vendor binaries are /bin/sh scripts; the real flow is "
           "Linux/WSL-scoped anyway",
)


@pytest.fixture
def fake_vendor(tmp_path, monkeypatch):
    """Put a stand-in vendor binary on PATH.

    Never the real `claude` or `codex`: those would open a browser and try to
    authenticate. This prints what the real ones print when they cannot open a
    browser -- a URL to visit -- and exits with whatever code the test wants.
    """
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    monkeypatch.setenv("PATH", str(bindir))

    def _make(name, *, exit_code=0, lines=("Visit https://example.test/auth",),
              linger=0):
        script = bindir / name
        body = "\n".join(f"echo {line!r}" for line in lines)
        script.write_text(
            f"#!/bin/sh\n{body}\nsleep {linger}\nexit {exit_code}\n",
            encoding="utf-8")
        script.chmod(0o755)
        return script

    return _make
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_login.py`:

```python
import threading

import pytest

from conftest import posix_only
from shambles import login, providers


@pytest.fixture
def codex():
    return providers.load("codex")


def test_the_command_comes_from_the_spec(codex):
    assert login.command(codex) == ["codex", "login"]


def test_an_email_is_appended_only_when_the_provider_supports_it(codex):
    claude = providers.load("claude")
    assert login.command(claude, email="a@example.com") == \
        ["claude", "auth", "login", "--email", "a@example.com"]
    # Codex declares no email flag; the address is silently not passed rather
    # than guessed at.
    assert login.command(codex, email="a@example.com") == ["codex", "login"]


@posix_only
def test_availability_follows_path(codex, fake_vendor):
    assert login.available(codex) is False
    fake_vendor("codex")
    assert login.available(codex) is True


@posix_only
def test_a_successful_login_reports_exit_zero_and_its_output(codex, fake_vendor):
    fake_vendor("codex", lines=("Visit https://example.test/auth", "Signed in"))
    lines, done = [], threading.Event()
    codes = []

    process = login.LoginProcess(login.command(codex))
    process.start(on_line=lines.append,
                  on_exit=lambda code: (codes.append(code), done.set()))

    assert done.wait(timeout=10), "login process never finished"
    assert codes == [0]
    assert "Visit https://example.test/auth" in lines


@posix_only
def test_a_failed_login_reports_its_exit_code(codex, fake_vendor):
    fake_vendor("codex", exit_code=1, lines=("could not reach the server",))
    done, codes = threading.Event(), []

    process = login.LoginProcess(login.command(codex))
    process.start(on_line=lambda _line: None,
                  on_exit=lambda code: (codes.append(code), done.set()))

    assert done.wait(timeout=10)
    assert codes == [1]


@posix_only
def test_cancelling_terminates_the_child(codex, fake_vendor):
    """A user who closes the dialog must not leave a vendor process holding a
    callback port open."""
    fake_vendor("codex", linger=30)
    done, codes = threading.Event(), []

    process = login.LoginProcess(login.command(codex))
    process.start(on_line=lambda _line: None,
                  on_exit=lambda code: (codes.append(code), done.set()))
    process.cancel(grace=2.0)

    assert done.wait(timeout=10)
    assert process.running is False
    assert codes and codes[0] != 0


def test_a_missing_binary_raises_a_readable_error(codex, monkeypatch):
    monkeypatch.setenv("PATH", "")
    process = login.LoginProcess(login.command(codex))
    with pytest.raises(login.LoginUnavailableError) as caught:
        process.start(on_line=lambda _line: None, on_exit=lambda _code: None)
    assert "codex" in str(caught.value)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_login.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'shambles.login'`

- [ ] **Step 4: Write `shambles/login.py`**

```python
"""Handing a lapsed profile to the vendor's own login flow.

The only module in Shambles that spawns a process.

DD-2 concluded that login must not be implemented inside this tool, and that
conclusion still holds completely: **no OAuth code lives here**. Both vendors
ship a one-shot command that opens the browser itself and runs its own
callback server, so this module starts that command, streams what it prints,
and waits. The credential still appears on disk written by the vendor, and
Shambles still only ever finds it there.

What DD-2 also said was that the tool "never opens a browser". That line is
crossed deliberately -- see the design doc -- and the thing it was protecting,
the absence of network and OAuth handling, is untouched. There is still no
``socket``, no ``urllib``, no ``requests``.
"""

import shutil
import subprocess
import threading

from .errors import ShamblesError


class LoginUnavailableError(ShamblesError):
    """The vendor's login command could not be started."""


NOT_ON_PATH = (
    "{binary} is not installed, or not on your PATH.\n\n"
    "Shambles does not sign you in itself — it runs {binary}, which opens "
    "your browser. Install it first, then try again."
)


def binary(provider) -> str:
    return provider.login_binary()


def available(provider) -> bool:
    """Whether this provider's login command can be run at all.

    Probed rather than assumed: offering a provider whose CLI is absent means
    the user only finds out at the moment they expected a browser.
    """
    return shutil.which(provider.login_binary()) is not None


def command(provider, *, email: str | None = None) -> list[str]:
    """The vendor's login argv, optionally pre-filling a known address.

    A provider that declares no ``email_flag`` gets no address rather than a
    guessed flag name.
    """
    argv = provider.login_command()
    flag = provider.spec.get("login", {}).get("email_flag")
    if email and flag:
        argv = argv + [flag, email]
    return argv


class LoginProcess:
    """One run of a vendor login command.

    Output is streamed line by line rather than collected, because the line
    that matters most arrives early: both vendors print a URL to open by hand
    when they cannot launch a browser, which is the normal case under WSL and
    over SSH. A user staring at a spinner while that URL sits in an unread
    buffer would conclude the tool is broken.

    ``on_line`` and ``on_exit`` are invoked **on a worker thread**. Tk callers
    must marshal back with ``widget.after``; a blocking wait on the main
    thread freezes the window and stops the signal pump that makes Ctrl+C
    work.
    """

    def __init__(self, argv, *, popen=subprocess.Popen):
        self._argv = list(argv)
        self._popen = popen
        self._process = None
        self._thread = None
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(self, *, on_line, on_exit) -> None:
        if shutil.which(self._argv[0]) is None:
            raise LoginUnavailableError(NOT_ON_PATH.format(binary=self._argv[0]))
        try:
            self._process = self._popen(
                self._argv,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise LoginUnavailableError(
                f"Could not start {self._argv[0]}:\n{exc}") from exc

        self._thread = threading.Thread(
            target=self._pump, args=(on_line, on_exit), daemon=True)
        self._thread.start()

    def _pump(self, on_line, on_exit) -> None:
        try:
            if self._process.stdout is not None:
                for line in self._process.stdout:
                    on_line(line.rstrip("\n"))
        except (OSError, ValueError):
            # The pipe closed under us, which is what cancel() looks like from
            # here. The exit code below is the real answer either way.
            pass
        code = self._process.wait()
        on_exit(code)

    def cancel(self, *, grace: float = 5.0) -> None:
        """Stop the vendor process.

        SIGTERM first so it can release its callback port, SIGKILL only if it
        will not go. Leaving one running would hold that port and make the
        next attempt fail for a reason the user could not possibly guess.
        """
        self._cancelled = True
        if self._process is None or self._process.poll() is not None:
            return
        self._process.terminate()
        try:
            self._process.wait(timeout=grace)
        except subprocess.TimeoutExpired:
            self._process.kill()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_login.py -v`
Expected: PASS

- [ ] **Step 6: Verify no network imports crept in**

Run: `.venv/bin/python -c "
import ast, pathlib, sys
banned = {'socket', 'urllib', 'requests', 'http', 'ssl'}
bad = []
for f in pathlib.Path('shambles').rglob('*.py'):
    for node in ast.walk(ast.parse(f.read_text())):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split('.')[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split('.')[0]]
        bad += [(str(f), n) for n in names if n in banned]
print(bad or 'clean')
sys.exit(1 if bad else 0)"`
Expected: `clean`, exit 0. This is the README's load-bearing security claim; it must be mechanically true.

- [ ] **Step 7: Commit**

```bash
git add shambles/login.py tests/test_login.py conftest.py
git commit -m "feat: run the vendor's own login command from the app

The only module that spawns a process. No OAuth code lives here: both
vendors ship a one-shot login that opens the browser and runs its own
callback server, so this starts that command and streams what it
prints. The credential still appears on disk written by the vendor.

Output is streamed rather than collected because the line that matters
arrives first -- both vendors print a URL to open by hand when they
cannot launch a browser, which is the normal case under WSL and over
SSH. Buffering it would leave the user watching a spinner.

Cancel sends SIGTERM before SIGKILL so the vendor can release its
callback port; a survivor would hold it and make the next attempt fail
for a reason nobody could guess.

Amends DD-2's 'never opens a browser'. What that line protected -- no
network, no OAuth handling -- is untouched: still no socket, no urllib,
no requests, and a test now asserts it.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 10: Eject across providers

Eject hands the machine back as a stock install for **every** provider, so uninstalling never costs anyone a token.

**Files:**
- Modify: `shambles/eject.py`
- Test: `tests/test_eject.py`

**Interfaces:**
- Consumes: Tasks 1, 3, 5, 7.
- Produces: `eject.survey(paths, providers, *, platform) -> Plan`, `eject.run(paths, providers, *, platform, sleep) -> Plan`, `eject.summary(plan) -> str`, `Plan(providers: list[ProviderPlan], store: Path)`, `ProviderPlan(provider, display_name, active, other_profiles, credentials_kept)`. Task 11's GUI calls all three.

- [ ] **Step 1: Write the failing test**

Replace `tests/test_eject.py` with:

```python
import pytest

from helpers import (make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile)
from shambles import eject, providers, state

ALL = None  # resolved per-test; providers.all_providers() needs no fixtures


def all_providers():
    return providers.all_providers()


def test_ejecting_a_stock_machine_is_a_clean_no_op(paths):
    plan = eject.run(paths, all_providers(), platform="linux")
    assert all(not p.credentials_kept for p in plan.providers)


def test_the_active_login_is_left_installed(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    plan = eject.run(paths, all_providers(), platform="linux")

    assert (paths.claude_dir / ".credentials.json").is_file()
    claude_plan = next(p for p in plan.providers if p.provider == "claude")
    assert claude_plan.credentials_kept is True
    assert claude_plan.active == "Work"


def test_a_missing_live_login_is_restored_from_the_active_profile(paths):
    """Ejecting must never leave the user logged out."""
    make_profile(paths, "codex", "Work", email="c@example.com", active=True)

    eject.run(paths, all_providers(), platform="linux")

    assert (paths.home / ".codex" / "auth.json").is_file()


def test_bookkeeping_goes_and_credentials_stay(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_live_claude_login(paths)

    eject.run(paths, all_providers(), platform="linux")

    assert state.read_active(paths, "claude") is None
    assert paths.credentials("claude", "Personal").is_file()


def test_every_provider_is_ejected_not_just_the_first(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_live_claude_login(paths)
    make_live_codex_login(paths, email="c@example.com")

    eject.run(paths, all_providers(), platform="linux")

    assert state.read_active(paths, "claude") is None
    assert state.read_active(paths, "codex") is None


def test_the_summary_names_the_profiles_left_behind(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_live_claude_login(paths)

    text = eject.summary(eject.run(paths, all_providers(), platform="linux"))

    assert "Personal" in text
    assert str(paths.library_dir) in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_eject.py -v`
Expected: FAIL with `TypeError: run() got an unexpected keyword argument 'platform'`

- [ ] **Step 3: Rewrite `shambles/eject.py`**

```python
"""Leaving cleanly, so uninstalling never costs anyone a token.

The naive way to remove Shambles is to delete the app and its profile store.
That destroys every stashed refresh token, and each one is only recoverable
through a fresh verification email. Eject exists so that is never the required
move.

Afterwards each provider's config is exactly what a stock install expects:
signed in, with history, plugins and settings untouched. The profile
directories are deliberately **left on disk** -- they hold the logins for the
accounts you were not using, and deleting those is the user's decision.
"""

import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import state, switcher
from .errors import ShamblesError
from .stores.base import StoreUnavailableError


class EjectError(ShamblesError):
    """Ejecting could not complete safely."""


@dataclass
class ProviderPlan:
    provider: str
    display_name: str
    #: Profile whose login is left installed.
    active: str | None = None
    #: Profiles left on disk for the user to remove.
    other_profiles: list = field(default_factory=list)
    #: Whether this provider ends up signed in.
    credentials_kept: bool = False


@dataclass
class Plan:
    providers: list = field(default_factory=list)
    #: Where the untouched profile store remains.
    store: Path | None = None


def survey(paths, providers, *, platform: str = sys.platform) -> Plan:
    """Describe what ejecting would do, without touching anything."""
    plan = Plan(store=paths.library_dir)
    for provider in providers:
        active = state.read_active(paths, provider.id)
        names = state.profile_names(paths, provider.id)
        if active not in names:
            active = None
        plan.providers.append(ProviderPlan(
            provider=provider.id,
            display_name=provider.display_name,
            active=active,
            other_profiles=[n for n in names if n != active],
            credentials_kept=_signed_in(paths, provider, active, platform),
        ))
    return plan


def _signed_in(paths, provider, active, platform) -> bool:
    try:
        if provider.store(home=paths.home, platform=platform).read() is not None:
            return True
    except StoreUnavailableError:
        return False
    return bool(active and paths.credentials(provider.id, active).exists())


def run(paths, providers, *, platform: str = sys.platform,
        sleep=time.sleep) -> Plan:
    """Restore a stock installation for every provider.

    Never deletes a credential. Idempotent: running it on an already-stock
    install is a no-op that still reports cleanly.
    """
    plan = survey(paths, providers, platform=platform)

    for provider, entry in zip(providers, plan.providers):
        store = provider.store(home=paths.home, platform=platform)

        # Make sure the provider is actually signed in. If the live credential
        # is missing but the active profile has a copy, put it back -- ejecting
        # must never leave the user logged out.
        try:
            if store.read() is None and entry.active:
                stashed = paths.credentials(provider.id, entry.active)
                if stashed.exists():
                    store.write(stashed.read_bytes())
            entry.credentials_kept = store.read() is not None
        except StoreUnavailableError:
            raise
        except OSError as exc:
            raise EjectError(
                f"Could not restore the {provider.display_name} login:\n{exc}"
            ) from exc

        # Remove Shambles' own bookkeeping. Nothing here belongs to the vendor
        # and nothing here is a credential.
        switcher.forget_active_marker(paths, provider)

    return plan


def summary(plan: Plan) -> str:
    """User-facing description of what just happened."""
    lines = []
    for entry in plan.providers:
        if entry.credentials_kept:
            who = f" as '{entry.active}'" if entry.active else ""
            lines.append(f"{entry.display_name} is a stock install, still "
                         f"signed in{who}. History, plugins and settings are "
                         f"untouched.")
        elif entry.other_profiles or entry.active:
            lines.append(f"{entry.display_name} has no credentials, so it will "
                         f"ask you to sign in. Nothing was deleted to cause that.")

    parked = sorted({name for entry in plan.providers
                     for name in entry.other_profiles})
    if parked:
        lines.append(
            f"\nLogins for {', '.join(parked)} are still in {plan.store}. They "
            "are kept because each one is only recoverable through a new "
            "verification email. Delete that folder yourself once you are sure.")
    elif plan.store:
        lines.append(f"\n{plan.store} can now be deleted.")

    return "\n".join(lines) if lines else "Nothing to eject."
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_eject.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add shambles/eject.py tests/test_eject.py
git commit -m "feat: eject every provider, not just Claude

Eject exists so that uninstalling never costs a token. With a second
provider it has to hand back both, or ejecting leaves one of them
logged out while claiming the machine is stock.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 11: Group the window by provider

The single global header goes. Each provider gets a section whose heading carries its own active account and its own warning state, because those are per-provider now and a fixed-size header cannot render N of them.

**Files:**
- Modify: `shambles/gui.py`
- Test: `tests/test_gui_import.py`

**Interfaces:**
- Consumes: Tasks 3–10.
- Produces: `gui.ShamblesApp(paths=None, providers=None, platform=None)`, `gui.group_heading(provider, current) -> str`, `gui.ShamblesApp.refresh()`. Task 12 extends the same class.

- [ ] **Step 1: Write the failing test**

Replace `tests/test_gui_import.py` with:

```python
import pytest

from helpers import (make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile, make_v1_profile)
from shambles import gui, providers, state


@pytest.fixture
def claude():
    return providers.load("claude")


@pytest.fixture
def codex():
    return providers.load("codex")


def test_the_heading_names_the_active_account(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    text = gui.group_heading(claude, state.inspect(paths, claude, platform="linux"))

    assert "Claude Code" in text and "Work" in text and "w@example.com" in text


def test_the_heading_surfaces_drift(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="other@example.com")

    text = gui.group_heading(claude, state.inspect(paths, claude, platform="linux"))

    assert "⚠" in text and "other@example.com" in text


def test_the_heading_of_an_empty_provider_says_so(paths, codex):
    text = gui.group_heading(codex, state.inspect(paths, codex, platform="linux"))
    assert "Codex" in text
    assert "No accounts saved" in text


def test_the_window_renders_both_providers(paths, make_app):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)
    make_live_codex_login(paths, email="c@example.com")

    app = make_app(paths)
    app.refresh()

    rendered = _all_text(app.rows)
    assert "Work" in rendered and "Side" in rendered


def test_the_window_migrates_a_v1_store_on_open(paths, make_app):
    """The repair is automatic and unprompted, like the v1.0 history merge:
    there is no version of the old layout anyone wants."""
    make_v1_profile(paths, "Work", email="w@example.com", active=True)

    app = make_app(paths)

    assert paths.credentials("claude", "Work").is_file()
    assert state.read_active(paths, "claude") == "Work"


def _all_text(widget):
    """Every string rendered anywhere under a widget."""
    found = []
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except Exception:
            pass
        found.extend(_all_text(child))
    return " ".join(found)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `xvfb-run -a .venv/bin/python -m pytest tests/test_gui_import.py -v`
Expected: FAIL with `AttributeError: module 'shambles.gui' has no attribute 'group_heading'`

- [ ] **Step 3: Rewrite the rendering half of `shambles/gui.py`**

Replace `header_text` with `group_heading`, and replace `refresh` / `_render_card`. Keep `Tooltip`, `tooltip_position`, the signal pump, and `on_close` exactly as they are — `tests/test_shutdown.py` guards them.

```python
GROUP_STATES = {
    state.UNMANAGED: "No accounts saved yet",
    state.UNKNOWN: "⚠ Not sure which account is live",
    state.MISSING_PROFILE: "⚠ Profile '{profile}' is missing from disk",
    state.DRIFTED: "⚠ Signed in as {live_email}, but '{profile}' expects "
                   "{expected_email}",
}


def group_heading(provider, current) -> str:
    """One line naming a provider and whatever is true about it right now.

    Per-provider rather than a single window header: with two providers there
    are two active accounts and two independent warning states, and a
    fixed-size header cannot render N of them without growing every time a
    provider is added.
    """
    if current.kind == state.MANAGED:
        who = current.profile or "unknown"
        email = current.live_email
        return f"{provider.display_name} · {who}" + (f" — {email}" if email else "")
    template = GROUP_STATES.get(current.kind, "")
    detail = template.format(profile=current.profile or "",
                             live_email=current.live_email or "unknown",
                             expected_email=current.expected_email or "unknown")
    return f"{provider.display_name} · {detail}"
```

Then, in `ShamblesApp.__init__`, replace the header block with provider wiring and drop `self.caption` / `self.title_label` / `self.subtitle`:

```python
    def __init__(self, paths=None, providers=None, platform=None):
        super().__init__()
        self.paths = paths or Paths.real()
        self.providers = (providers if providers is not None
                          else provider_registry.all_providers())
        self.platform = platform or sys.platform
        scale_for_display(self)
        self.theme = Theme(self)
        t = self.theme

        self.title(WINDOW_TITLE)
        self.configure(bg=t["window"])
        self.resizable(False, False)

        self.rows = tk.Frame(self, bg=t["window"], padx=GAP_L, pady=GAP_L)
        self.rows.pack(fill="both", expand=True)

        footer = tk.Frame(self, bg=t["window"], padx=GAP_L, pady=GAP_L)
        footer.pack(fill="x")
        ttk.Button(footer, text="＋  Add Account", style="Accent.TButton",
                   command=self.on_add).pack(side="right")
        self.eject_button = ttk.Button(footer, text="Eject",
                                       style="Shambles.TButton",
                                       command=self.on_eject)
        self.eject_button.pack(side="right", padx=(0, GAP_S))
        Tooltip(self.eject_button,
                "Stop using Shambles and hand every account back as a stock "
                "install. Nothing is deleted.", t)

        self.minsize(WINDOW_WIDTH, 0)

        self._pump = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._install_signal_handlers()
        self._pump_signals()
        self._repair_legacy_layout()
        self._migrate_store()
        self.refresh()
```

Add the store-migration hook beside the existing `_repair_legacy_layout`:

```python
    def _migrate_store(self):
        """Move a v1.0 store into the provider-scoped layout, unprompted.

        Not offered as a choice, for the same reason the history merge is not:
        the old layout cannot hold a second provider, so staying on it is not
        an option anyone would pick knowingly. Nothing is deleted -- the old
        store stays on disk and the dialog says where.
        """
        if not migrate.store_migration_needed(self.paths):
            return
        try:
            plan = migrate.migrate_store(self.paths)
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
            return
        if not plan.profiles:
            return
        messagebox.showinfo(
            WINDOW_TITLE,
            f"Your profiles moved to {plan.dest}.\n\n"
            f"{len(plan.profiles)} account(s) are now filed under the provider "
            f"they belong to, which is what lets Shambles hold Codex accounts "
            f"alongside Claude ones.\n\n"
            f"Nothing was deleted — the old {plan.source} is still there, and "
            f"you can remove it once you are satisfied.",
            parent=self)
```

Now `refresh`, which renders one section per provider:

```python
    def refresh(self):
        """Re-read everything from disk. No cached view state, ever."""
        t = self.theme
        for child in self.rows.winfo_children():
            child.destroy()

        for provider in self.providers:
            # Rotating providers go stale in the background; correct that
            # before reading, so the row and the stash agree.
            switcher.restash_active(self.paths, provider, platform=self.platform)

            current = state.inspect(self.paths, provider, platform=self.platform)
            self._render_group(provider, current)

            override = state.config_dir_override(provider, home=self.paths.home)
            if override:
                self._render_override_banner(provider, override)

    def _render_group(self, provider, current):
        t = self.theme
        heading = tk.Frame(self.rows, bg=t["window"])
        heading.pack(fill="x", pady=(GAP_M, GAP_XS))

        warned = current.kind not in (state.MANAGED, state.UNMANAGED)
        tk.Label(heading, text=group_heading(provider, current), font=t.caption,
                 bg=t["window"], fg=t["warn"] if warned else t["faint"],
                 anchor="w", justify="left",
                 wraplength=WINDOW_WIDTH - 2 * GAP_L).pack(side="left")

        if not login.available(provider):
            self._render_missing_vendor(provider)
            return

        if current.kind in (state.UNMANAGED, state.UNKNOWN, state.DRIFTED):
            ttk.Button(heading, text="Save current login",
                       style="Shambles.TButton",
                       command=lambda p=provider: self.on_save(p)).pack(side="right")

        found = profiles.discover(self.paths, provider, current.profile,
                                  switcher.now_ms(), platform=self.platform)
        if not found:
            tk.Label(self.rows, text="No accounts yet.", font=t.body,
                     bg=t["window"], fg=t["faint"], anchor="w").pack(fill="x")
            return

        for profile in found:
            self._render_card(provider, profile)

        if current.kind == state.MISSING_PROFILE:
            ttk.Button(self.rows, text="Forget that profile",
                       style="Shambles.TButton",
                       command=lambda p=provider: self.on_forget_marker(p)
                       ).pack(anchor="w", pady=(GAP_S, 0))

    def _render_missing_vendor(self, provider):
        """Say why the section is empty rather than implying no accounts.

        'No accounts yet' beside an uninstalled CLI is a lie of omission: the
        user would only discover the binary is missing at the moment they
        expected a browser to open.
        """
        t = self.theme
        card = tk.Frame(self.rows, bg=t["card"], padx=GAP_M, pady=GAP_M)
        card.pack(fill="x", pady=(0, GAP_S))
        tk.Label(card, bg=t["card"], fg=t["muted"], font=t.body, anchor="w",
                 justify="left", wraplength=WINDOW_WIDTH - 4 * GAP_L,
                 text=(f"{login.binary(provider)} is not on your PATH.\n"
                       f"Install it to add {provider.display_name} accounts — "
                       f"Shambles runs it to sign you in.")).pack(fill="x")
```

`_render_card` keeps its structure; only its callbacks and its liveness source change:

```python
    def _render_card(self, provider, profile):
        """One profile as a bordered card, accented when it is the active one."""
        t = self.theme
        bg = t["card_active"] if profile.active else t["card"]
        edge = t["border_active"] if profile.active else t["border"]

        shell = tk.Frame(self.rows, bg=edge, highlightthickness=0)
        shell.pack(fill="x", pady=(0, GAP_S))
        tk.Frame(shell, bg=edge if profile.active else t["border"],
                 width=ACCENT_BAR_WIDTH).pack(side="left", fill="y")

        card = tk.Frame(shell, bg=bg, padx=GAP_M, pady=GAP_M)
        card.pack(side="left", fill="both", expand=True)

        top = tk.Frame(card, bg=bg)
        top.pack(fill="x")
        name = tk.Label(top, text=profile.name, font=t.name, bg=bg,
                        fg=t["text"], cursor="hand2")
        name.pack(side="left")
        name.bind("<Double-Button-1>",
                  lambda _e, p=profile: self.on_rename_prompt(provider, p.name))
        Tooltip(name, RENAME_HINT, t)

        if profile.active:
            tk.Label(top, text="ACTIVE", font=t.caption, bg=bg,
                     fg=t["accent"]).pack(side="left", padx=(GAP_S, 0))
        else:
            ttk.Button(top, text="Switch", style="Switch.TButton",
                       command=lambda p=profile: self.on_switch(provider, p.name)
                       ).pack(side="right")
            # Inactive profiles only, so the login you are using cannot be
            # deleted by a misclick. Sits inboard of Switch: the rightmost
            # slot belongs to the action used constantly, not the destructive
            # one.
            remove = ttk.Button(top, text="✕", style="Danger.TButton", width=2,
                                command=lambda p=profile: self.on_remove(provider, p.name))
            remove.pack(side="right", padx=(0, GAP_M))
            Tooltip(remove, f"Remove '{profile.name}'. Its saved login is "
                            "deleted and that account needs a new sign-in.", t)

        bottom = tk.Frame(card, bg=bg)
        bottom.pack(fill="x", pady=(GAP_XS, 0))
        tk.Label(bottom, text=profile.email or "unknown", font=t.body,
                 bg=bg, fg=t["muted"]).pack(side="left")

        label = profiles.expiry_label(profile)
        if label:
            fg_key, bg_key = CHIP_STYLES[profiles.expiry_severity(profile)]
            chip = tk.Label(bottom, text=f" {label} ", font=t.chip,
                            bg=t[bg_key], fg=t[fg_key], padx=GAP_S, pady=1)
            chip.pack(side="left", padx=(GAP_S, 0))
            Tooltip(chip, expiry_tooltip(profile), t)

        warning = profiles.warning(profile)
        if warning:
            badge = tk.Label(bottom, text="⚠", font=t.body, bg=bg, fg=t["warn"])
            badge.pack(side="left", padx=(GAP_S, 0))
            Tooltip(badge, warning, t)
```

Update `expiry_tooltip` to read from `Liveness`, and the action callbacks to take a provider:

```python
def expiry_tooltip(profile) -> str:
    """The exact date behind the short countdown chip."""
    when = datetime.datetime.fromtimestamp(profile.liveness.expires_at_ms / 1000)
    verb = "expired" if profile.liveness.days_left < 0 else "expires"
    return EXPIRY_TOOLTIP.format(verb=verb, date=when.strftime("%d %b %Y, %H:%M"))
```

```python
    def on_switch(self, provider, name):
        self._guarded(lambda: switcher.switch(self.paths, provider, name,
                                              platform=self.platform))

    def on_rename_prompt(self, provider, old_name):
        new_name = simpledialog.askstring(
            "Rename profile", "New name:", initialvalue=old_name, parent=self)
        if new_name is None or new_name.strip() == old_name:
            return
        self._guarded(lambda: switcher.rename_profile(self.paths, provider,
                                                      old_name, new_name))

    def on_forget_marker(self, provider):
        self._guarded(lambda: switcher.forget_active_marker(self.paths, provider))

    def on_remove(self, provider, name):
        if not messagebox.askyesno(
                "Remove Profile",
                f"Are you sure you want to delete the profile '{name}'? "
                "This will permanently destroy its stored login token.",
                parent=self):
            return
        self._guarded(lambda: switcher.remove_profile(self.paths, provider, name,
                                                      platform=self.platform))

    def on_save(self, provider):
        name = simpledialog.askstring(
            f"Save Current {provider.display_name} Account", "Profile name:",
            initialvalue="Default", parent=self)
        if name is not None:
            self._guarded(lambda: switcher.save_current_account(
                self.paths, provider, name, platform=self.platform))

    def on_eject(self):
        """Hand the machine back as a stock install for every provider."""
        plan = eject.survey(self.paths, self.providers, platform=self.platform)
        parked = sorted({n for e in plan.providers for n in e.other_profiles})
        others = (f"\n\nLogins for {', '.join(parked)} stay on disk — they are "
                  f"only recoverable through a new verification email, so "
                  f"removing them is your call." if parked else "")
        if not messagebox.askokcancel(
                WINDOW_TITLE,
                "Stop using Shambles?\n\n"
                "Every account keeps its current login, history, plugins and "
                f"settings, and goes back to being an ordinary install. "
                f"Nothing is deleted.{others}\n\nContinue?",
                parent=self):
            return
        try:
            done = eject.run(self.paths, self.providers, platform=self.platform)
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
            return
        messagebox.showinfo(WINDOW_TITLE, eject.summary(done), parent=self)
        self.refresh()
```

Update `_render_override_banner` to take a provider and name the right variable:

```python
    def _render_override_banner(self, provider, target: str):
        """The provider's config-dir variable is set, so a terminal reads a
        tree Shambles never touches. VS Code is unaffected -- neither extension
        host inherits shell environment variables, which is why this tool
        exists."""
        t = self.theme
        name = provider.spec.get("config_dir", {}).get("env", "the config dir")
        card = tk.Frame(self.rows, bg=t["chip_gone_bg"], padx=GAP_M, pady=GAP_M)
        card.pack(fill="x", pady=(0, GAP_S))
        tk.Label(card, text=f"⚠  {name} is set", font=t.name,
                 bg=t["chip_gone_bg"], fg=t["chip_gone_fg"], anchor="w",
                 justify="left").pack(fill="x")
        tk.Label(card, bg=t["chip_gone_bg"], fg=t["chip_gone_fg"], font=t.body,
                 anchor="w", justify="left",
                 wraplength=WINDOW_WIDTH - 4 * GAP_L,
                 text=(f"Your environment points {provider.display_name} at:\n"
                       f"{target}\n\nShambles swaps the login in the default "
                       f"location, so switches will not affect that terminal. "
                       f"VS Code is unaffected. Unset it in your shell profile "
                       f"to use Shambles from the CLI."),
                 ).pack(fill="x", pady=(GAP_XS, 0))
```

Finally, update the imports at the top of `gui.py`:

```python
import datetime
import signal
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import eject, login, migrate, profiles, state, switcher
from . import providers as provider_registry
from .errors import ShamblesError
from .paths import Paths
from .theme import (ACCENT_BAR_WIDTH, GAP_L, GAP_M, GAP_S, GAP_XS,
                    WINDOW_WIDTH, Theme, scale_for_display)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `xvfb-run -a .venv/bin/python -m pytest tests/test_gui_import.py tests/test_shutdown.py -v`
Expected: PASS. `test_shutdown.py` must stay green — the signal pump and `on_close` were not touched.

- [ ] **Step 5: Commit**

```bash
git add shambles/gui.py tests/test_gui_import.py
git commit -m "feat: group the window by provider

The single global header goes. With two providers there are two active
accounts and two independent warning states, and a fixed-size header
cannot render N of them without growing every time a provider is added.
Each section now carries its own.

Save Current Account moves into the group heading for the same reason:
a footer button has no provider context once there are two.

A provider whose CLI is missing says so rather than showing an empty
list. 'No accounts yet' beside an uninstalled binary is a lie of
omission -- the user would find out only when they expected a browser.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 12: Provider choice and browser login in Add Account

The headline feature. Add Account asks which provider, then drives the vendor's login so the user never leaves the app.

**Files:**
- Modify: `shambles/gui.py`
- Test: `tests/test_gui_add.py`

**Interfaces:**
- Consumes: Tasks 9, 11.
- Produces: `gui.AddAccountDialog(parent, options, theme)` with `.result -> (name, provider_id) | None`, where `options` is `list[tuple[Provider, bool]]`; `gui.LoginDialog(parent, provider, profile_name, theme)` with `.succeeded -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_gui_add.py`:

```python
import pytest

from conftest import posix_only
from helpers import make_profile
from shambles import gui, providers, state, switcher


@pytest.fixture
def both():
    return providers.all_providers()


@posix_only
def test_only_installed_providers_are_selectable(paths, make_app, fake_vendor, both):
    """A provider whose CLI is absent is offered but disabled, with the reason
    visible -- not silently missing, which would look like a bug."""
    fake_vendor("claude")
    app = make_app(paths)

    options = app.add_account_options()

    available = {p.id: ok for p, ok in options}
    assert available == {"claude": True, "codex": False}


@posix_only
def test_a_successful_login_stashes_the_credential(paths, make_app, fake_vendor,
                                                   monkeypatch):
    """The whole point: after the vendor writes its credential, Shambles files
    it under the profile that was just created."""
    from helpers import codex_auth, write_json
    codex = providers.load("codex")
    script = fake_vendor("codex")
    # The stand-in vendor writes a credential where the real one would.
    auth = paths.home / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True, exist_ok=True)
    write_json(auth, codex_auth(email="new@example.com"))

    app = make_app(paths)
    switcher.add_empty_account(paths, codex, "Fresh", platform="linux",
                               sleep=lambda _: None)
    # add_empty_account clears the live credential; the vendor puts one back.
    write_json(auth, codex_auth(email="new@example.com"))

    assert app.stash_after_login(codex, "Fresh") is True
    assert paths.credentials("codex", "Fresh").is_file()

    found = state.inspect(paths, codex, platform="linux")
    assert found.live_email == "new@example.com"


@posix_only
def test_a_cancelled_login_leaves_the_profile_empty(paths, make_app, fake_vendor):
    """Not a new failure mode -- add_empty_account already activates an empty
    profile, and switching back recovers it."""
    codex = providers.load("codex")
    fake_vendor("codex", exit_code=1)
    app = make_app(paths)
    switcher.add_empty_account(paths, codex, "Fresh", platform="linux",
                               sleep=lambda _: None)

    assert app.stash_after_login(codex, "Fresh") is False
    assert not paths.credentials("codex", "Fresh").exists()


def test_the_dialog_returns_a_name_and_a_provider(paths, make_app):
    """The contract on_add depends on."""
    app = make_app(paths)
    assert hasattr(gui.AddAccountDialog, "result")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `xvfb-run -a .venv/bin/python -m pytest tests/test_gui_add.py -v`
Expected: FAIL with `AttributeError: 'ShamblesApp' object has no attribute 'add_account_options'`

- [ ] **Step 3: Rewrite `AddAccountDialog` and add `LoginDialog`**

Replace `AddAccountDialog` in `shambles/gui.py`:

```python
class AddAccountDialog(tk.Toplevel):
    """Asks which provider and what to call the profile.

    ``options`` is ``[(provider, available)]``. An unavailable provider is
    shown and disabled rather than omitted: a missing row reads as a bug,
    while a greyed one with a reason reads as an instruction.
    """

    def __init__(self, parent, options, theme):
        super().__init__(parent)
        self.title("Add Account")
        self.resizable(False, False)
        self.transient(parent)
        self.configure(bg=theme["window"])
        self.result = None

        body = tk.Frame(self, bg=theme["window"], padx=GAP_L, pady=GAP_L)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="PROVIDER", font=theme.caption,
                 bg=theme["window"], fg=theme["muted"]).pack(anchor="w")

        first_available = next((p.id for p, ok in options if ok), None)
        self.provider_var = tk.StringVar(value=first_available or "")
        for provider, ok in options:
            label = provider.display_name if ok else \
                f"{provider.display_name}  —  not installed"
            tk.Radiobutton(
                body, text=label, value=provider.id,
                variable=self.provider_var, state="normal" if ok else "disabled",
                font=theme.body, bg=theme["window"], fg=theme["text"],
                selectcolor=theme["card"], activebackground=theme["window"],
                activeforeground=theme["text"], disabledforeground=theme["faint"],
                anchor="w", highlightthickness=0,
            ).pack(fill="x", pady=(GAP_XS, 0))

        tk.Label(body, text="PROFILE NAME", font=theme.caption,
                 bg=theme["window"], fg=theme["muted"]).pack(anchor="w",
                                                             pady=(GAP_M, 0))
        self.name_var = tk.StringVar()
        entry = tk.Entry(body, textvariable=self.name_var, font=theme.body,
                         width=26, relief="flat", highlightthickness=1,
                         highlightbackground=theme["border"],
                         highlightcolor=theme["accent"],
                         bg=theme["card"], fg=theme["text"], insertwidth=2)
        entry.pack(fill="x", pady=(GAP_XS, GAP_M), ipady=GAP_XS + 2)

        tk.Label(body, font=theme.body, bg=theme["window"], fg=theme["muted"],
                 anchor="w", justify="left", wraplength=260,
                 text=("Your settings, plugins and session history are shared "
                       "with every account — only the login differs.\n\n"
                       "Your browser will open so you can sign in."),
                 ).pack(fill="x")

        buttons = tk.Frame(body, bg=theme["window"])
        buttons.pack(fill="x", pady=(GAP_M, 0))
        ttk.Button(buttons, text="Cancel", style="Shambles.TButton",
                   command=self.destroy).pack(side="right")
        self.create = ttk.Button(buttons, text="Create", style="Accent.TButton",
                                 command=self._accept)
        self.create.pack(side="right", padx=(0, GAP_S))
        if first_available is None:
            self.create.config(state="disabled")

        entry.focus_set()
        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.wait_window(self)

    def _accept(self):
        if self.provider_var.get():
            self.result = (self.name_var.get(), self.provider_var.get())
        self.destroy()


class LoginDialog(tk.Toplevel):
    """Waits while the vendor's own login runs.

    Shows whatever the command prints, because the line that matters arrives
    first: both vendors print a URL to open by hand when they cannot launch a
    browser, which is normal under WSL and over SSH.

    ``succeeded`` is True only on a clean exit.
    """

    def __init__(self, parent, provider, profile_name, theme):
        super().__init__(parent)
        self.title(f"Sign in to {provider.display_name}")
        self.resizable(False, False)
        self.transient(parent)
        self.configure(bg=theme["window"])
        self.succeeded = False
        self._process = None

        body = tk.Frame(self, bg=theme["window"], padx=GAP_L, pady=GAP_L)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=f"Signing in as '{profile_name}'", font=theme.name,
                 bg=theme["window"], fg=theme["text"], anchor="w").pack(fill="x")
        self.status = tk.Label(
            body, font=theme.body, bg=theme["window"], fg=theme["muted"],
            anchor="w", justify="left", wraplength=360,
            text="Your browser should have opened. Complete the sign-in there.")
        self.status.pack(fill="x", pady=(GAP_XS, GAP_S))

        self.output = tk.Text(body, height=6, width=52, font=theme.body,
                              relief="flat", bg=theme["card"], fg=theme["muted"],
                              highlightthickness=1,
                              highlightbackground=theme["border"], wrap="word")
        self.output.pack(fill="both", expand=True)
        self.output.config(state="disabled")

        buttons = tk.Frame(body, bg=theme["window"])
        buttons.pack(fill="x", pady=(GAP_M, 0))
        self.close = ttk.Button(buttons, text="Cancel",
                                style="Shambles.TButton", command=self._cancel)
        self.close.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.after(0, lambda: self._start(provider))
        self.wait_window(self)

    def _start(self, provider):
        try:
            self._process = login.LoginProcess(login.command(provider))
            # Both callbacks fire on a worker thread; `after` marshals them
            # back. Touching Tk from that thread would corrupt the interpreter
            # lock and hang the window.
            self._process.start(
                on_line=lambda line: self.after(0, self._append, line),
                on_exit=lambda code: self.after(0, self._finish, code))
        except ShamblesError as exc:
            self._append(str(exc))
            self._finish(1)

    def _append(self, line):
        self.output.config(state="normal")
        self.output.insert("end", line + "\n")
        self.output.see("end")
        self.output.config(state="disabled")

    def _finish(self, code):
        self.succeeded = (code == 0)
        if self.succeeded:
            self.destroy()
            return
        self.status.config(text="Sign-in did not complete. The profile was "
                                "created but has no login yet.")
        self.close.config(text="Close", command=self.destroy)

    def _cancel(self):
        if self._process is not None:
            self._process.cancel()
        self.succeeded = False
        self.destroy()
```

- [ ] **Step 4: Wire `on_add`**

Replace `on_add` in `ShamblesApp`:

```python
    def add_account_options(self):
        """Every provider, paired with whether its CLI can actually be run."""
        return [(provider, login.available(provider))
                for provider in self.providers]

    def stash_after_login(self, provider, name) -> bool:
        """File whatever the vendor just wrote under the new profile.

        Returns whether a credential was found. The vendor writes to its own
        live location; this is the step that makes it a Shambles profile.
        """
        try:
            switcher.stash_live_login(self.paths, provider, name,
                                      platform=self.platform)
        except ShamblesError:
            return False
        return self.paths.credentials(provider.id, name).exists()

    def on_add(self):
        options = self.add_account_options()
        dialog = AddAccountDialog(self, options, self.theme)
        if dialog.result is None:
            return
        name, provider_id = dialog.result
        provider = next(p for p in self.providers if p.id == provider_id)

        try:
            created = switcher.add_empty_account(self.paths, provider, name,
                                                 platform=self.platform)
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
            self.refresh()
            return

        # The profile is active and empty. The vendor's own command fills it.
        session = LoginDialog(self, provider, created, self.theme)
        if session.succeeded and self.stash_after_login(provider, created):
            messagebox.showinfo(
                WINDOW_TITLE,
                f"'{created}' is signed in and active.\n\n"
                "Start a new session to pick it up — a running one keeps the "
                "token it loaded at startup.",
                parent=self)
        else:
            messagebox.showwarning(
                WINDOW_TITLE,
                f"'{created}' was created but has no login yet.\n\n"
                f"{provider.login_hint()}\n\n"
                "Switching to another profile is safe — nothing was lost.",
                parent=self)
        self.refresh()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `xvfb-run -a .venv/bin/python -m pytest tests/test_gui_add.py -v`
Expected: PASS

- [ ] **Step 6: Run the whole suite**

Run: `xvfb-run -a .venv/bin/python -m pytest`
Expected: PASS, all tests.

- [ ] **Step 7: Commit**

```bash
git add shambles/gui.py tests/test_gui_add.py
git commit -m "feat: choose a provider when adding an account, and sign in

Add Account asks which provider, then runs that vendor's own login so
the browser opens without the user leaving the app. On a clean exit the
credential is filed under the new profile; on cancel or failure the
profile is left empty, which switching back recovers.

Both login callbacks arrive on a worker thread and are marshalled with
after(). Touching Tk from that thread would hang the window.

An unavailable provider is shown disabled rather than omitted: a missing
row reads as a bug, a greyed one with a reason reads as an instruction.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 13: Documentation

Three documents make claims this change falsifies. The README's "no `subprocess`" sentence is the most important, because it is load-bearing for the security argument and DD-2 already drafted its replacement.

**Files:**
- Modify: `README.md`, `docs/design-decisions.md`, `TECH_SPEC.md`

**Interfaces:**
- Consumes: everything.
- Produces: no code.

- [ ] **Step 1: Replace the README's inertness claim**

In `README.md`, under "Is this safe?", replace the paragraph beginning "**It is entirely local...**" with the wording DD-2 drafted, extended for the login handoff:

```markdown
**It is entirely local and cannot touch your Claude or OpenAI account.**

No network: no `socket`, no `urllib`, no `requests`. It cannot reach
Anthropic's or OpenAI's servers, so it cannot affect your login, billing, rate
limits or organisation membership. It only moves bytes between directories on
your own disk.

It executes exactly one kind of external program: the vendor's own login
command — `claude auth login` or `codex login` — and only when you click Add
Account. **Shambles implements no part of signing in.** That command opens
your browser and runs its own callback server; Shambles waits for it to finish
and then files the credential it wrote. No password, no token in flight, and
nothing held that was not already on your disk.
```

- [ ] **Step 2: Update the README's layout, provider and platform sections**

Replace the "What it touches" table paths with `~/.shambles/<provider>/<Name>/`, add a Codex row to the platform table marked **Unverified — no Codex install was available**, and document that Add Account now opens a browser. Update the standalone countdown snippet, which currently globs `~/.claude-profiles`:

```bash
.venv/bin/python -c "
import json,datetime,pathlib
root = pathlib.Path.home()/'.shambles'
for provider in sorted(p for p in root.iterdir() if p.is_dir() and p.name[0]!='.'):
    for d in sorted(p for p in provider.iterdir() if p.is_dir()):
        c = d/'credentials.json'
        if not c.exists(): print(f'{provider.name}/{d.name:<12} no token'); continue
        print(f'{provider.name}/{d.name:<12} has a token')"
```

- [ ] **Step 3: Amend DD-2 and mark DD-4 implemented**

In `docs/design-decisions.md`, change DD-2's status to **Decided, amended 2026-08-07** and add:

```markdown
### Amendment, 2026-08-07 — the handoff is automated

Shambles now *starts* the vendor's login command instead of printing it. The
conclusion "do not implement login inside the tool" is unchanged and still
absolute: no OAuth code, no client secret, no callback server, no network
import. Both vendors ship a one-shot command that does all of that itself.

The consequence bullet reading "never opens a browser" no longer holds, and
was given up deliberately. What it was protecting — the absence of network
reach and token handling — is untouched, and `tests/test_login.py` now asserts
mechanically that no networking module is imported anywhere in the package.

The lapsed-profile handoff survives as the fallback: when the vendor's binary
is not on PATH, or its login exits non-zero, the UI names the exact command.
```

Replace DD-4's "NOT IMPLEMENTED" banner with a pointer to the shipped modules and to `docs/superpowers/specs/2026-08-07-multi-provider-design.md`.

- [ ] **Step 4: Update TECH_SPEC.md**

It is the stated definitive reference and currently describes a single-provider tool. Update the architecture, on-disk layout, and test-coverage sections to match, and add the provider/store layering. Where TECH_SPEC and the design doc disagree, TECH_SPEC wins — so it must not be left stale.

- [ ] **Step 5: Verify every documented path exists**

Run: `.venv/bin/python -m pytest && grep -rn 'claude-profiles' README.md TECH_SPEC.md`
Expected: tests PASS; the only `claude-profiles` mentions left are historical ones describing the migration.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/design-decisions.md TECH_SPEC.md
git commit -m "docs: record multi-provider support and the login handoff

The 'no subprocess' claim is now false and is replaced with the wording
DD-2 drafted for exactly this moment. The load-bearing half of that
paragraph -- no network reach -- is unchanged and is now asserted by a
test rather than only by prose.

DD-2 gains an amendment rather than a rewrite: its conclusion stands,
one of its consequences was given up deliberately, and the reasoning for
both is on the record. DD-4 stops saying NOT IMPLEMENTED.

Codex is documented as unverified. No Codex install was available, and
its spec was researched on macOS with Linux marked source-only.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage.** Every spec section maps to a task: §4 architecture → Task 1; §5 layout → Tasks 3, 4; §6.1 switch → Task 7; §6.2 add+login → Tasks 9, 12; §6.3 rotation → Task 8; §6.4 migration → Task 4; §7 error handling → Tasks 7, 9, 12; §8 UI → Tasks 11, 12; §9 modules → all; §10 testing → every task's test step; §12 out-of-scope respected (no keychain/credman wiring, no Swift, no MCP policy change); §13 verification note → Task 13 Step 3.

**Type consistency.** `provider` is always a `Provider` object, never an id string, except in `paths.*(provider_id, ...)` and `state.read_active/write_active/profile_names(paths, provider_id)`, which take the id — these are the storage-layer calls and take a plain string throughout. `platform` is a `sys.platform` string everywhere, keyword-only, defaulting to `sys.platform`. `AddAccountDialog.result` is `(name, provider_id)` in Task 12 and is unpacked as such in `on_add`.

**Known gaps, deliberate.** `KeychainStore` and `CredmanStore` ship unreferenced (spec §12). Codex's live path is exercised only through fixtures and a fake binary (spec §13). `tests/test_configjson.py`, `tests/test_migrate.py`, `tests/test_retry.py` and `tests/test_packaging.py` are not rewritten — they test modules whose interfaces do not change, and any that fail after Task 3 need only the new `Paths` accessors.

---

## Verification

After Task 13, end to end on a real machine:

```bash
.venv/bin/pip install -e ".[dev]"
xvfb-run -a .venv/bin/python -m pytest
```

1. Back up `~/.claude-profiles/` and `~/.claude.json` first.
2. `python3 shambles.py` — confirm the migration dialog, and that `~/.shambles/claude/` mirrors the old profiles with the original left intact.
3. Confirm the Codex group shows the "not on your PATH" hint.
4. **＋ Add Account** — Codex is disabled with a reason. Pick Claude, name it, confirm the browser opens and the credential is stashed with an email and expiry chip.
5. Cancel a second login mid-flow; confirm the child process dies (`pgrep -f 'claude auth login'` is empty) and the profile is left empty rather than half-written.
6. Switch between two Claude profiles; confirm `~/.claude.json` keeps `numStartups`, `projects` and `machineID`, and that the heading email follows.
7. Ctrl+C in the launching terminal still exits cleanly with a login thread alive.
