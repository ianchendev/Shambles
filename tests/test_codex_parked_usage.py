"""Parked Codex accounts keep their last usage reading (F6).

Claude stashes its usage cache with the login, so a parked Claude row shows
its last figures. Codex keeps no cache of its own: it writes the 5-hour and
weekly windows onto session logs under ``~/.codex/sessions``, which every
account shares. So a parked Codex row said "No usage recorded yet" forever.

An account now keeps its newest reading, at a switch and each time the
window re-reads, but only one taken while it was the account in use:
anything older was written by whoever was signed in before it. The account
in use is held to the same rule, so it never shows the previous account's
last figures as its own.
"""

import datetime
import json
import os

from helpers import (NOW, make_codex_session, make_live_codex_login,
                     make_profile)
from shambles import providers, state, switcher
from shambles import usage as usage_mod
from shambles.app import snapshot
from shambles.app.service import ShamblesService
from shambles.providers.codex import CodexProvider

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


# -- kept on every re-read, not only at a switch ---------------------------
#
# A reading kept only at a switch made in Shambles misses an account left
# any other way: signed out of in the Codex extension, or replaced by
# ``codex login`` in a terminal. And the account in use reads its figures
# from the newest log, so a session just opened, with no reading on it yet,
# showed it as having none. The window re-reads every minute, so it keeps
# the reading then, held to the same rules as the switch.


def service(paths, providers_=None):
    return ShamblesService(
        paths=paths, providers=providers_ or providers.all_providers(env={}),
        platform="linux", clock_ms=lambda: NOW)


def kept(paths, name):
    path = paths.usage("codex", name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))["fetchedAtMs"]


def signed_in_outside(paths, name):
    """``name``'s login put in place by Codex itself, not by a switch."""
    live_auth(paths).write_bytes(
        paths.credentials("codex", name).read_bytes())


def a_new_session_with_no_reading(paths):
    """A session just opened: Codex has written its log, but no turn yet."""
    log = paths.home / ".codex" / "sessions" / "2026" / "09" / "08" / \
        "rollout-new.jsonl"
    log.write_text(json.dumps({"timestamp": READ_AT,
                               "type": "session_meta",
                               "payload": {"id": "new"}}) + "\n",
                   encoding="utf-8")
    later = os.stat(log.with_name("rollout-test.jsonl")).st_mtime + 60
    os.utime(log, (later, later))


def test_an_account_left_outside_shambles_keeps_what_a_refresh_saw(paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, used_week=7.0, timestamp=READ_AT)
    service(paths).refresh_files()

    signed_in_outside(paths, "Personal")

    assert rows(paths)["Work"] == [42, 7]


def test_a_new_session_with_no_reading_yet_keeps_the_last_figures(paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, used_week=7.0, timestamp=READ_AT)
    service(paths).refresh_files()

    a_new_session_with_no_reading(paths)

    assert rows(paths)["Work"] == [42, 7]


def test_refresh_keeps_it_too(paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)

    service(paths).refresh()

    assert kept(paths, "Work") == int(epoch(READ_AT) * 1000)


def test_nothing_is_kept_while_another_saved_login_is_live(paths):
    """Signed in as Personal outside Shambles, the marker still on Work: the
    newest reading is Personal's, taken after the marker moved."""
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    signed_in_outside(paths, "Personal")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)

    service(paths).refresh_files()

    assert kept(paths, "Work") is None
    assert kept(paths, "Personal") is None


def test_nothing_is_kept_for_a_login_no_saved_account_provably_holds(paths):
    """A login nobody saved, under the marker of a profile never signed in:
    the window may show its figures, but they are not filed as anyone's."""
    make_profile(paths, "codex", "Work", token=False)
    state.write_active(paths, "codex", "Work")
    os.utime(paths.active_marker("codex"),
             (epoch("2026-09-08T11:00:00.000Z"),) * 2)
    make_live_codex_login(paths, email="someone@example.test")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)

    service(paths).refresh_files()

    assert kept(paths, "Work") is None


def test_a_reading_from_before_the_account_was_in_use_is_not_kept_either(
        paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T13:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)

    service(paths).refresh_files()

    assert kept(paths, "Work") is None


def test_the_reading_is_written_only_when_it_changes(paths, monkeypatch):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)
    writes = []
    real = usage_mod.configjson.write_atomic

    def counted(path, data):
        writes.append(path)
        return real(path, data)

    monkeypatch.setattr(usage_mod.configjson, "write_atomic", counted)
    window = service(paths)

    window.refresh_files()
    window.refresh_files()
    assert len(writes) == 1

    make_codex_session(paths, used_5h=43.0,
                       timestamp="2026-09-08T12:05:00.000Z")
    window.refresh_files()
    assert len(writes) == 2


def test_an_older_reading_never_replaces_a_newer_one(paths):
    """Codex resuming an old session makes its log the newest, while the
    last reading on it is older than the one already kept."""
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=50.0,
                       timestamp="2026-09-08T12:30:00.000Z")
    window = service(paths)
    window.refresh_files()

    resumed = make_codex_session(paths, used_5h=42.0, timestamp=READ_AT,
                                 name="rollout-resumed.jsonl")
    later = os.stat(resumed.with_name("rollout-test.jsonl")).st_mtime + 60
    os.utime(resumed, (later, later))
    window.refresh_files()

    assert kept(paths, "Work") == int(
        epoch("2026-09-08T12:30:00.000Z") * 1000)


def test_keeping_it_adds_no_walk_of_the_session_logs(paths, monkeypatch):
    """The window re-reads every minute and whenever a log changes, which
    is every turn of a Codex session in use. One walk finds the newest log
    to watch, and the row reads it; keeping the reading reuses that."""
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)
    walks = []
    real = usage_mod.latest_codex_session

    def counted(config_dir):
        walks.append(config_dir)
        return real(config_dir)

    monkeypatch.setattr(usage_mod, "latest_codex_session", counted)

    service(paths).refresh_files()

    assert kept(paths, "Work") is not None
    assert len(walks) <= 2


class _SecretStore:
    """Not a file, and every read is counted, as the Keychain would be."""

    def __init__(self, blob):
        self.blob, self.reads = blob, 0

    def read(self):
        self.reads += 1
        return self.blob

    def describe(self):
        return "the test keychain"


def test_a_files_only_refresh_never_reads_a_store_that_is_not_a_file(
        paths):
    two_accounts(paths)
    signed_in(paths, "Work", since="2026-09-08T11:00:00.000Z")
    make_codex_session(paths, used_5h=42.0, timestamp=READ_AT)
    secret = _SecretStore(paths.credentials("codex", "Work").read_bytes())

    class SecretCodex(CodexProvider):
        def store(self, *, home, platform):
            return secret

    window = service(paths, (SecretCodex(env={}),))
    window.snapshot()
    reads = secret.reads

    window.refresh_files()

    assert secret.reads == reads
    assert kept(paths, "Work") == int(epoch(READ_AT) * 1000)
