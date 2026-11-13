"""A switch waits for a Claude Code refresh that is already in flight.

Claude Code 2.1.300 refreshes under a lock: it creates
``<config dir>/.oauth_refresh.lock`` (and the older ``<config dir>.lock``),
re-reads the stored login, posts its refresh token, and saves the result only
if the stored refresh token is still the one it posted. The server rotates
the token as soon as it is posted.

So a switch landing between the post and the save loses the account switched
away from: Shambles stashes the token that was just spent, writes the other
account into the live file, and the save is then refused because the stored
token changed. The new token existed only in that process. Taking the same
lock makes the switch wait for the refresh to land, and stash the new token.
"""

import json
import os
import threading
import time

import pytest

from helpers import NOW, account, make_profile, signed_in_at, write_json
from shambles import providers, state, switcher
from shambles.errors import ShamblesError
from shambles.stores import FileStore


def claude():
    return providers.load("claude", env={})


def login(refresh):
    """One account's login. The part before the dash names the account, so
    'o-old' and 'o-new' are one login refreshed (same sign-in deadline) and
    'w-1' is another."""
    account_key = refresh.split("-")[0]
    return {"claudeAiOauth": {"accessToken": f"a-{refresh}",
                              "refreshToken": refresh, "expiresAt": NOW,
                              "refreshTokenExpiresAt": signed_in_at(account_key)}}


@pytest.fixture
def work_live(paths):
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    write_json(paths.credentials("claude", "Work"), login("r-old"))
    write_json(paths.claude_dir / ".credentials.json", login("r-old"))
    write_json(paths.claude_json, {"oauthAccount": account("w@example.test")})
    return paths


def refresh_in_flight(paths, *, lands_after_s):
    """Claude Code: lock held, token posted, the response not back yet."""
    lock = paths.claude_dir / ".oauth_refresh.lock"
    lock.mkdir()
    live = paths.claude_dir / ".credentials.json"

    def response_arrives():
        stored = json.loads(live.read_text(encoding="utf-8"))
        if stored["claudeAiOauth"]["refreshToken"] == "r-old":   # its CAS
            write_json(live, login("r-new"))
        lock.rmdir()

    timer = threading.Timer(lands_after_s, response_arrives)
    timer.start()
    return timer


def test_a_switch_waits_for_a_refresh_in_flight(work_live):
    paths = work_live
    timer = refresh_in_flight(paths, lands_after_s=0.3)

    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)
    timer.join()

    saved = json.loads(paths.credentials("claude", "Work").read_text())
    assert saved["claudeAiOauth"]["refreshToken"] == "r-new", (
        "Work's saved login is the token the refresh had already spent")
    assert state.read_active(paths, "claude") == "Other"
    assert not (paths.claude_dir / ".oauth_refresh.lock").exists()


def test_a_lock_left_by_a_client_that_died_does_not_block(work_live):
    """Claude Code touches its lock every five seconds and treats one a
    minute old as abandoned. So does Shambles."""
    paths = work_live
    lock = paths.claude_dir / ".oauth_refresh.lock"
    lock.mkdir()
    long_ago = time.time() - 120
    os.utime(lock, (long_ago, long_ago))

    started = time.monotonic()
    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)

    assert time.monotonic() - started < 2
    assert state.read_active(paths, "claude") == "Other"
    assert not lock.exists()


def test_a_refresh_that_does_not_finish_refuses_the_switch(work_live,
                                                          monkeypatch):
    paths = work_live
    monkeypatch.setattr(switcher, "REFRESH_LOCK_WAIT_S", 0.2)
    (paths.claude_dir / ".oauth_refresh.lock").mkdir()
    before = (paths.claude_dir / ".credentials.json").read_bytes()

    with pytest.raises(ShamblesError) as raised:
        switcher.switch(paths, claude(), "Other", platform="linux",
                        sleep=lambda _: None)

    assert "Claude Code" in str(raised.value)
    assert (paths.claude_dir / ".credentials.json").read_bytes() == before
    assert state.read_active(paths, "claude") == "Work"
    assert (paths.claude_dir / ".oauth_refresh.lock").exists(), (
        "removed a lock that was not ours")


def test_the_lock_is_released_when_the_switch_fails(work_live, monkeypatch):
    paths = work_live

    def disk_full(*args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(state, "write_active", disk_full)
    with pytest.raises(ShamblesError):
        switcher.switch(paths, claude(), "Other", platform="linux",
                        sleep=lambda _: None)

    assert not (paths.claude_dir / ".oauth_refresh.lock").exists()
    assert not paths.home.joinpath(".claude.lock").exists()


def test_codex_takes_no_lock(paths):
    codex = providers.load("codex", env={})
    assert codex.refresh_locks(home=paths.home) == []


# == found by an independent review of the first version ==================

def saved_refresh(paths, name):
    return json.loads(paths.credentials("claude", name).read_text())[
        "claudeAiOauth"]["refreshToken"]


# -- the outgoing profile is decided before the lock -------------------------

def test_a_refresh_landing_while_the_switch_waits_is_kept(paths):
    """The live bytes are exactly Other's stash, the marker still says Work
    (a switch that stopped before moving the marker, or another window).
    _outgoing_profile reads the store before the lock and answers 'Other
    already holds these bytes, nothing to stash'. Claude Code is mid-refresh
    of Other's token; the switch waits for it, then overwrites the store."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    make_profile(paths, "claude", "Third", email="t@example.test")
    write_json(paths.credentials("claude", "Work"), login("w-1"))
    write_json(paths.credentials("claude", "Other"), login("o-old"))
    write_json(paths.credentials("claude", "Third"), login("t-1"))
    live = paths.claude_dir / ".credentials.json"
    write_json(live, login("o-old"))
    write_json(paths.claude_json, {"oauthAccount": account("o@example.test")})

    lock = paths.claude_dir / ".oauth_refresh.lock"
    lock.mkdir()

    def response_arrives():
        stored = json.loads(live.read_text(encoding="utf-8"))
        if stored["claudeAiOauth"]["refreshToken"] == "o-old":   # its CAS
            write_json(live, login("o-new"))
        lock.rmdir()

    timer = threading.Timer(0.3, response_arrives)
    timer.start()
    # Refusing is a right answer here: once the refresh lands, the live
    # login is plainly Other's while the marker names Work. Losing the
    # token it was given is not.
    try:
        switcher.switch(paths, claude(), "Third", platform="linux",
                        sleep=lambda _: None)
    except ShamblesError:
        pass
    timer.join()

    everywhere = [p.read_text() for p in paths.library_dir.rglob("*")
                  if p.is_file()] + [live.read_text()]
    assert any("o-new" in text for text in everywhere), (
        "Other's refreshed token was overwritten and is saved nowhere; "
        f"Other's stash holds the spent {saved_refresh(paths, 'Other')!r}")


# -- a stale lock that cannot be removed spins forever -----------------------

@pytest.mark.parametrize("kind", ["file", "nonempty-dir", "dangling-symlink"])
def test_an_unremovable_stale_lock_does_not_hang_the_switch(paths, monkeypatch,
                                                            kind):
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    write_json(paths.claude_dir / ".credentials.json",
               json.loads(paths.credentials("claude", "Work").read_text()))
    write_json(paths.claude_json, {"oauthAccount": account("w@example.test")})
    monkeypatch.setattr(switcher, "REFRESH_LOCK_WAIT_S", 0.5)

    legacy = paths.home / ".claude.lock"
    if kind == "file":
        legacy.write_text("x")
    elif kind == "nonempty-dir":
        legacy.mkdir()
        (legacy / "junk").write_text("x")
    else:
        os.symlink(paths.home / "nowhere", legacy)
    long_ago = time.time() - 120
    if kind != "dangling-symlink":
        os.utime(legacy, (long_ago, long_ago))

    outcome = []

    def run():
        try:
            switcher.switch(paths, claude(), "Other", platform="linux",
                            sleep=lambda _: None)
            outcome.append("switched")
        except ShamblesError as exc:
            outcome.append(f"refused: {exc}")

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(timeout=5)
    stuck = worker.is_alive()
    # Let the spinning thread out before the test ends.
    if legacy.is_symlink() or legacy.is_file():
        legacy.unlink()
    elif legacy.is_dir():
        (legacy / "junk").unlink()
    worker.join(timeout=5)

    assert not stuck, (
        "switch still spinning after 5 s with REFRESH_LOCK_WAIT_S=0.5, "
        "holding .oauth_refresh.lock the whole time")


# -- no heartbeat, unconditional release -------------------------------------

def test_a_lock_claude_code_took_over_is_not_removed(paths, monkeypatch):
    """Shambles never touches its lock's mtime. If its hold outlasts the
    60 s stale interval (simulated: aged inside the critical section),
    Claude Code clears it and takes it as its own; Shambles' finally then
    rmdirs Claude Code's live lock."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    write_json(paths.claude_dir / ".credentials.json",
               json.loads(paths.credentials("claude", "Work").read_text()))
    write_json(paths.claude_json, {"oauthAccount": account("w@example.test")})
    lock = paths.claude_dir / ".oauth_refresh.lock"
    real_write = FileStore.write

    def slow_write(self, payload):
        if lock.exists():
            long_ago = time.time() - 61
            os.utime(lock, (long_ago, long_ago))
            # Claude Code: stale, so remove and take it.
            lock.rmdir()
            lock.mkdir()
        return real_write(self, payload)

    monkeypatch.setattr(FileStore, "write", slow_write)
    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)

    assert lock.exists(), "removed the lock Claude Code now holds"


# -- "no config directory: no lock is taken" ---------------------------------

def test_no_config_directory_takes_no_lock(paths, monkeypatch):
    """No ~/.claude at all (nothing signed in, nothing installed). The PR
    says no lock is taken; the legacy one is still made in the home
    directory, where Claude Code (proper-lockfile, realpath of a missing
    directory: ENOENT) never would."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    assert not paths.claude_dir.exists()
    seen = []
    real_write = FileStore.write

    def watching_write(self, payload):
        seen.append(sorted(p.name for p in paths.home.iterdir()
                           if p.name.endswith(".lock")))
        return real_write(self, payload)

    monkeypatch.setattr(FileStore, "write", watching_write)
    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)

    assert seen and seen[-1] == [], f"locks present during the switch: {seen}"


# -- what the lock is: the paths, the order, and that it is held ------------

def test_both_locks_are_held_while_the_live_login_is_replaced(work_live,
                                                              monkeypatch):
    paths = work_live
    live = paths.claude_dir / ".credentials.json"
    seen = []
    real_write = FileStore.write

    def watching(store, payload):
        if store.path == live:
            seen.append(((paths.claude_dir / ".oauth_refresh.lock").is_dir(),
                         (paths.home / ".claude.lock").is_dir()))
        return real_write(store, payload)

    monkeypatch.setattr(FileStore, "write", watching)
    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None)

    assert seen == [(True, True)]
    assert not (paths.claude_dir / ".oauth_refresh.lock").exists()
    assert not (paths.home / ".claude.lock").exists()


def test_the_locks_are_taken_in_the_clients_order(paths):
    paths.claude_dir.mkdir()
    locks = claude().refresh_locks(home=paths.home)

    assert locks == [paths.claude_dir / ".oauth_refresh.lock",
                     paths.home / ".claude.lock"]


def test_the_legacy_lock_follows_a_linked_config_dir(paths):
    real = paths.home / "elsewhere" / "claude"
    real.mkdir(parents=True)
    os.symlink(real, paths.claude_dir, target_is_directory=True)

    assert claude().refresh_locks(home=paths.home)[1] == real.with_name(
        "claude.lock")


def test_the_secure_storage_directory_decides_where_the_lock_is(paths):
    other = paths.home / "secure"
    other.mkdir()
    provider = providers.load(
        "claude", env={"CLAUDE_SECURESTORAGE_CONFIG_DIR": str(other)})

    assert provider.refresh_locks(home=paths.home)[0] == (
        other / ".oauth_refresh.lock")


def test_a_timeout_on_the_second_lock_releases_the_first(work_live,
                                                         monkeypatch):
    paths = work_live
    monkeypatch.setattr(switcher, "REFRESH_LOCK_WAIT_S", 0.2)
    (paths.home / ".claude.lock").mkdir()

    with pytest.raises(ShamblesError):
        switcher.switch(paths, claude(), "Other", platform="linux",
                        sleep=lambda _: None)

    assert not (paths.claude_dir / ".oauth_refresh.lock").exists()
    assert (paths.home / ".claude.lock").is_dir(), "removed a lock not ours"


# -- saying so while it waits -------------------------------------------------
#
# Reproduced in the terminal UI on a synthetic home with the lock held: Enter
# on another account, then fifteen seconds in which nothing on screen changed
# and the list still moved as if no switch had started, then a refusal. The
# switch now says, once, that it is waiting and on what.

def test_a_switch_that_has_to_wait_says_so_once(work_live):
    paths = work_live
    timer = refresh_in_flight(paths, lands_after_s=0.3)
    waits = []

    switcher.switch(paths, claude(), "Other", platform="linux",
                    sleep=lambda _: None, on_wait=lambda: waits.append(1))
    timer.join()

    assert waits == [1]
    assert state.read_active(paths, "claude") == "Other"


def test_a_switch_that_does_not_wait_says_nothing(work_live):
    waits = []
    switcher.switch(work_live, claude(), "Other", platform="linux",
                    sleep=lambda _: None, on_wait=lambda: waits.append(1))
    assert waits == []


def test_a_broken_wait_callback_does_not_break_the_switch(work_live):
    timer = refresh_in_flight(work_live, lands_after_s=0.2)

    def broken():
        raise RuntimeError("the screen went away")

    switcher.switch(work_live, claude(), "Other", platform="linux",
                    sleep=lambda _: None, on_wait=broken)
    timer.join()
    assert state.read_active(work_live, "claude") == "Other"


def test_the_service_passes_the_wait_on(work_live):
    from shambles.app.service import ShamblesService

    service = ShamblesService(paths=work_live,
                              providers=providers.all_providers(env={}),
                              platform="linux", clock_ms=lambda: NOW)
    timer = refresh_in_flight(work_live, lands_after_s=0.3)
    waits = []

    result = service.switch("claude", "Other",
                            on_wait=lambda: waits.append(1))
    timer.join()

    assert result.ok, result
    assert waits == [1]


def test_the_cli_says_it_is_waiting_rather_than_sitting_silent(work_live,
                                                                capsys):
    from shambles.app import cli

    timer = refresh_in_flight(work_live, lands_after_s=0.3)
    code = cli.main(["--home", str(work_live.home), "switch", "claude",
                     "Other"])
    timer.join()
    captured = capsys.readouterr()

    assert code == 0
    assert "Waiting for Claude Code" in captured.err
    assert "Waiting" not in captured.out      # stdout stays parseable
