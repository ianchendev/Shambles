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

from helpers import NOW, account, make_profile, write_json
from shambles import providers, state, switcher
from shambles.errors import ShamblesError


def claude():
    return providers.load("claude", env={})


def login(refresh):
    return {"claudeAiOauth": {"accessToken": f"a-{refresh}",
                              "refreshToken": refresh, "expiresAt": NOW,
                              "refreshTokenExpiresAt": NOW + 20 * 86_400_000}}


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
