"""U2: the window re-reads files by itself, and never the Keychain.

On macOS every Keychain read can raise a password prompt, so anything that
runs without the user asking -- focus, a file changing, the minute timer --
reads files only. Stores that are not plain files (the Keychain, Windows
Credential Manager) are answered from the last explicit read: Refresh, a
switch, a sign-in.
"""

import os

from helpers import (NOW, account, make_claude_json, make_live_claude_login,
                     make_profile, write_json)
from shambles import providers
from shambles.app.service import ShamblesService
from shambles.providers.claude import ClaudeProvider
from shambles.stores.fallback import FallbackStore
from shambles.stores.file import FileStore


class SecretStore:
    """Stands in for the Keychain: not a file, and every read is counted."""

    def __init__(self):
        self.reads = 0
        self.blob = None

    def read(self):
        self.reads += 1
        return self.blob

    def write(self, payload):
        self.blob = payload

    def delete(self):
        self.blob = None

    def describe(self):
        return "the test keychain"


class KeychainClaude(ClaudeProvider):
    """Claude with its login layered over a secret store, as on macOS."""

    def __init__(self, secret, **kw):
        super().__init__(env={}, **kw)
        self.secret = secret

    def store(self, *, home, platform):
        plain = super().store(home=home, platform=platform)
        return FallbackStore(self.secret, plain)


def keychain_service(paths, secret):
    codex = providers.load("codex", env={})
    return ShamblesService(paths=paths,
                           providers=(KeychainClaude(secret), codex),
                           platform="darwin", clock_ms=lambda: NOW)


def file_service(paths):
    return ShamblesService(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux", clock_ms=lambda: NOW)


def work_is_live(paths):
    make_profile(paths, "claude", "Work", email="work@example.test",
                 active=True)
    make_profile(paths, "claude", "Dev", email="dev@example.test")
    make_live_claude_login(paths, access_token="tok-Work")
    make_claude_json(paths, email="work@example.test")


# -- never the Keychain --------------------------------------------------------


def test_a_files_only_refresh_never_reads_the_keychain(paths):
    secret = SecretStore()
    work_is_live(paths)
    app = keychain_service(paths, secret)
    app.refresh()
    assert secret.reads > 0, "the explicit refresh should read it"
    secret.reads = 0

    result = app.refresh_files()

    assert result.ok and result.snapshot is not None
    assert secret.reads == 0


def test_a_files_only_refresh_says_what_the_last_full_read_said(paths):
    """Answered from memory, the store must give the same picture, not a
    blank one: an unanswered store reads as signed out."""
    secret = SecretStore()
    work_is_live(paths)
    app = keychain_service(paths, secret)

    full = app.snapshot()
    files = app.refresh_files().snapshot

    assert files == full


def test_before_any_full_read_a_files_only_refresh_reads_nothing(paths):
    """No memory yet means no answer. Guessing "nothing there" would show
    the live account as signed out, so it does not refresh at all."""
    secret = SecretStore()
    work_is_live(paths)
    app = keychain_service(paths, secret)

    result = app.refresh_files()

    assert result.snapshot is None
    assert secret.reads == 0


def test_a_files_only_refresh_never_writes_a_credential(paths):
    """No adoption, no re-stash: those read the live store and move bytes.
    Only the usage sidecar is written, as an explicit refresh does."""
    work_is_live(paths)
    app = file_service(paths)
    app.refresh()
    before = {p: p.read_bytes() for p in paths.library_dir.rglob("*") if p.is_file()
              and p.name != "account.json"}

    app.refresh_files()

    after = {p: p.read_bytes() for p in paths.library_dir.rglob("*") if p.is_file()
             and p.name != "account.json"}
    assert after == before


def test_a_files_only_refresh_picks_up_new_usage(paths):
    work_is_live(paths)
    app = file_service(paths)
    app.refresh()
    make_claude_json(paths, email="work@example.test", extra={
        "cachedUsageUtilization": {
            "fetchedAtMs": NOW, "accountUuid": "uuid-a",
            "utilization": {"limits": [
                {"kind": "session", "percent": 64, "severity": "normal"}]}}})

    live = next(a for a in app.refresh_files().snapshot.groups[0].accounts
                if a.active)

    assert [w.used_percent for w in live.usage] == [64]


# -- noticing a change -----------------------------------------------------------


def test_the_watch_signature_moves_when_claude_code_writes_its_files(paths):
    work_is_live(paths)
    app = file_service(paths)
    app.refresh()
    first = app.watch_signature()
    assert app.watch_signature() == first

    claude_json = paths.claude_json
    stamp = claude_json.stat().st_mtime_ns + 5_000_000_000
    os.utime(claude_json, ns=(stamp, stamp))

    assert app.watch_signature() != first


def test_the_watch_signature_moves_when_the_login_file_changes(paths):
    work_is_live(paths)
    app = file_service(paths)
    first = app.watch_signature()

    make_live_claude_login(paths, access_token="tok-Dev-rotated-longer")

    assert app.watch_signature() != first


def test_the_watch_signature_moves_when_another_shambles_switches(paths):
    work_is_live(paths)
    app = file_service(paths)
    first = app.watch_signature()

    paths.active_marker("claude").write_text("Dev\n", encoding="utf-8")

    assert app.watch_signature() != first


def test_the_watch_signature_follows_codex_session_logs(paths):
    from helpers import make_codex_session, make_live_codex_login
    make_profile(paths, "codex", "Main", email="m@example.test", active=True)
    make_live_codex_login(paths, email="m@example.test")
    make_codex_session(paths, used_5h=10.0)
    app = file_service(paths)
    app.refresh()
    first = app.watch_signature()

    sessions = sorted((paths.home / ".codex" / "sessions").rglob("*.jsonl"))
    with sessions[-1].open("a", encoding="utf-8") as handle:
        handle.write("{}\n")

    assert app.watch_signature() != first


def test_the_watch_signature_never_reads_the_keychain(paths):
    secret = SecretStore()
    work_is_live(paths)
    app = keychain_service(paths, secret)
    app.refresh()
    secret.reads = 0

    app.watch_signature()

    assert secret.reads == 0
