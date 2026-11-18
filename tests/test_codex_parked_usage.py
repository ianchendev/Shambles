"""Parked Codex accounts keep their last usage reading (F6).

Claude stashes its usage cache with the login, so a parked Claude row shows
its last figures. Codex keeps no cache of its own: it writes the 5-hour and
weekly windows onto session logs under ``~/.codex/sessions``, which every
account shares. So a parked Codex row said "No usage recorded yet" forever.

At a switch the outgoing account now keeps the newest reading, but only one
taken while it was the account in use: anything older was written by
whoever was signed in before it. The account in use is held to the same
rule, so it never shows the previous account's last figures as its own.
"""

import datetime
import json
import os

from helpers import NOW, make_codex_session, make_profile
from shambles import providers, state, switcher
from shambles.app import snapshot

READ_AT = "2026-09-08T12:00:00.000Z"


def epoch(iso):
    return datetime.datetime.fromisoformat(
        iso.replace("Z", "+00:00")).timestamp()


def codex():
    return providers.load("codex", env={})


def live_auth(paths):
    return paths.home / ".codex" / "auth.json"


def signed_in(paths, name, *, since):
    """``name``'s login is live and has been marked in use since ``since``."""
    live = live_auth(paths)
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_bytes(paths.credentials("codex", name).read_bytes())
    state.write_active(paths, "codex", name)
    os.utime(paths.active_marker("codex"), (epoch(since), epoch(since)))


def two_accounts(paths):
    make_profile(paths, "codex", "Work", email="work@example.test")
    make_profile(paths, "codex", "Personal", email="personal@example.test")


def rows(paths, now_ms=NOW):
    built = snapshot.build(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux", now_ms=now_ms)
    group = next(g for g in built.groups if g.provider == "codex")
    return {a.name: [w.used_percent for w in a.usage] for a in group.accounts}


def switch(paths, name):
    switcher.switch(paths, codex(), name, platform="linux",
                    sleep=lambda _: None)


def test_a_parked_codex_account_shows_its_last_reading(paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, used_week=7.0, timestamp=READ_AT)

    switch(paths, "Personal")

    assert rows(paths)["Work"] == [42, 7]


def test_a_reading_from_before_the_account_was_in_use_is_not_kept(paths):
    """The newest log was written while someone else was signed in."""
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T13:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)

    switch(paths, "Personal")

    assert rows(paths)["Work"] == []


def test_the_account_in_use_never_shows_the_previous_accounts_figures(paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)

    switch(paths, "Personal")

    assert rows(paths)["Personal"] == [], "Work's figures shown as Personal's"


def test_switching_back_shows_the_accounts_own_reading_until_a_new_one(
        paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, used_week=7.0, timestamp=READ_AT)
    switch(paths, "Personal")

    switch(paths, "Work")

    assert rows(paths)["Work"] == [42, 7]


def test_a_new_session_replaces_the_kept_reading_for_the_account_in_use(
        paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)

    later = datetime.datetime.now(datetime.timezone.utc) + \
        datetime.timedelta(minutes=1)
    switch(paths, "Personal")
    make_codex_session(paths, used_5h=13.0,
                       timestamp=later.isoformat().replace("+00:00", "Z"))

    shown = rows(paths)
    assert shown["Personal"][:1] == [13]
    assert shown["Work"][:1] == [42]


def test_the_reading_is_kept_owner_only_beside_the_login(paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)

    switch(paths, "Personal")

    kept = paths.profile_dir("codex", "Work") / "usage.json"
    assert json.loads(kept.read_text(encoding="utf-8"))["fetchedAtMs"] == \
        int(epoch(READ_AT) * 1000)
    if os.name == "posix":
        assert kept.stat().st_mode & 0o777 == 0o600


def test_keeping_the_reading_never_stops_a_switch(paths, monkeypatch):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)

    def refuse(*_args, **_kwargs):
        raise OSError("read-only")

    monkeypatch.setattr(switcher.configjson, "write_atomic", refuse)

    switch(paths, "Personal")

    assert state.read_active(paths, "codex") == "Personal"
    assert live_auth(paths).read_bytes() == \
        paths.credentials("codex", "Personal").read_bytes()


def test_marking_the_account_already_in_use_keeps_its_readings(paths):
    """The marker's time says when the account became the one in use, so a
    write that changes nothing must not move it: a switch to the account
    already in use would otherwise hide its own figures until its next
    session."""
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)
    before = paths.active_marker("codex").stat().st_mtime_ns

    state.write_active(paths, "codex", "Work")

    assert paths.active_marker("codex").stat().st_mtime_ns == before
    assert rows(paths)["Work"][:1] == [42]
