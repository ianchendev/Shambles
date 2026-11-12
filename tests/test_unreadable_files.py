"""Files Shambles reads but does not own, in states it did not expect.

The vendor's credential store, ``~/.claude.json`` and the session logs are
written by other programs on their own schedule. A read can land mid-write,
find a file locked, or find a value no version of this tool has seen. None of
that is an error the user caused, and none of it may take the window down:
every card is drawn from these files on every refresh, so one unreadable file
is otherwise the whole application.
"""

import base64
import json

import pytest

from helpers import (NOW, healthy_ms, make_claude_json,
                     make_live_claude_login, make_live_codex_login,
                     make_profile)
from shambles import configjson, providers, state, switcher, usage
from shambles.app.service import ShamblesService
from shambles.errors import ConfigUnreadableError
from shambles.providers import UNKNOWN


def codex():
    return providers.load("codex", env={})


def claude():
    return providers.load("claude", env={})


def service(paths):
    return ShamblesService(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux", clock_ms=lambda: NOW)


# -- a live store that cannot be read -------------------------------------
#
# FileStore turns every failure except absence into StoreUnavailableError,
# which is a ShamblesError and not an OSError. The read paths below were
# written to swallow OSError, so the one exception the store actually raises
# went straight through them.

@pytest.fixture
def unreadable_codex_store(paths):
    """A Codex login the store cannot read: its path is a directory.

    Stands in for a file locked by another process or with the wrong owner.
    Chosen because it fails the same way on every platform and for root.
    """
    make_profile(paths, "codex", "Work", email="w@example.test", active=True)
    (paths.home / ".codex" / "auth.json").mkdir(parents=True)
    return paths


def test_inspect_classifies_without_the_live_store(unreadable_codex_store):
    """'Classify one provider's login without touching anything' -- and
    without raising, or the window cannot draw a single card."""
    paths = unreadable_codex_store

    current = state.inspect(paths, codex(), platform="linux")

    assert (current.kind, current.profile) == (state.MANAGED, "Work")
    assert state.live_email(paths, codex(), platform="linux") is None


def test_restash_swallows_an_unreadable_store(unreadable_codex_store):
    """'Failures are swallowed', says its docstring: it runs on every refresh
    as a background correction. The identity check sat outside the guard."""
    paths = unreadable_codex_store
    before = paths.credentials("codex", "Work").read_bytes()

    assert switcher.restash_active(paths, codex(), platform="linux") is False
    assert paths.credentials("codex", "Work").read_bytes() == before


def test_refresh_reports_instead_of_raising(unreadable_codex_store):
    result = service(unreadable_codex_store).refresh()

    assert result.ok is True
    assert result.snapshot is not None


def test_the_window_opens_with_an_unreadable_store(unreadable_codex_store,
                                                   make_app):
    """It used to die in its constructor, before drawing anything."""
    app = make_app(unreadable_codex_store)

    app.refresh()


def test_an_unreadable_store_still_refuses_a_switch(unreadable_codex_store):
    """Surviving a read is not permission to write: the outgoing login could
    not be copied out, so nothing may replace it."""
    from shambles.errors import ShamblesError

    paths = unreadable_codex_store
    make_profile(paths, "codex", "Other", email="o@example.test")

    with pytest.raises(ShamblesError):
        switcher.switch(paths, codex(), "Other", platform="linux",
                        sleep=lambda _: None)

    assert state.read_active(paths, "codex") == "Work"
    assert (paths.home / ".codex" / "auth.json").is_dir()


# -- ~/.claude.json caught mid-write ---------------------------------------

MID_WRITE = [
    # Cut inside a multi-byte character: every project path, prompt and
    # display name in this file can hold one.
    b'{"oauthAccount": {"displayName": "Zo\xc3',
    # Not text at all.
    b"\xff\xfe\x00\x00",
]


@pytest.mark.parametrize("payload", MID_WRITE)
def test_a_config_cut_mid_character_reads_as_empty(paths, payload):
    """load() promises {} for anything unusable. Invalid UTF-8 is a
    UnicodeDecodeError, not a JSONDecodeError, and escaped."""
    paths.claude_json.write_bytes(payload)

    assert configjson.load(paths.claude_json) == {}


@pytest.mark.parametrize("payload", MID_WRITE)
def test_a_config_cut_mid_character_is_refused_for_writing(paths, payload):
    """...and load_for_write promises ConfigUnreadableError, which is what
    every frontend knows how to show."""
    paths.claude_json.write_bytes(payload)

    with pytest.raises(ConfigUnreadableError):
        configjson.load_for_write(paths.claude_json)
    assert paths.claude_json.read_bytes() == payload


def test_a_switch_refuses_cleanly_on_a_config_cut_mid_character(paths):
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    live = make_live_claude_login(paths, access_token="tok-Work")
    before = live.read_bytes()
    paths.claude_json.write_bytes(MID_WRITE[0])

    with pytest.raises(ConfigUnreadableError):
        switcher.switch(paths, claude(), "Personal", platform="linux",
                        sleep=lambda _: None)

    assert live.read_bytes() == before
    assert state.read_active(paths, "claude") == "Work"


def test_the_listing_survives_a_config_cut_mid_character(paths):
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_live_claude_login(paths, access_token="tok-Work")
    paths.claude_json.write_bytes(MID_WRITE[0])

    snapshot = service(paths).snapshot()

    assert [a.name for a in snapshot.groups[0].accounts] == ["Work"]


# -- the active marker ------------------------------------------------------

def test_a_marker_that_is_not_text_reads_as_no_marker(paths):
    """A torn write or a bad sector. The profiles are all still there."""
    make_profile(paths, "claude", "Work", email="w@example.test")
    paths.active_marker("claude").write_bytes(b"\xff\xfe\xfa")

    assert state.read_active(paths, "claude") is None
    assert state.inspect(paths, claude(), platform="linux").kind == state.UNKNOWN


# -- numbers that are not numbers -------------------------------------------
#
# Python's JSON parser accepts NaN and Infinity, and turns 1e400 into inf.
# int() of either raises, and it raised inside the code that draws a card.

NONSENSE = ["NaN", "Infinity", "-Infinity", "1e400", "1" + "0" * 400]


@pytest.mark.parametrize("value", NONSENSE)
def test_claude_expiry_that_is_not_a_number_is_unknown(value):
    blob = ('{"claudeAiOauth": {"refreshToken": "r", '
            f'"refreshTokenExpiresAt": {value}}}}}').encode()

    assert claude().liveness(blob, now_ms=NOW).state == UNKNOWN


def _codex_blob(exp_literal: str) -> bytes:
    raw = ('{"exp": %s}' % exp_literal).encode()
    token = "h." + base64.urlsafe_b64encode(raw).rstrip(b"=").decode() + ".s"
    return json.dumps({"tokens": {"access_token": token,
                                  "refresh_token": "r"}}).encode()


@pytest.mark.parametrize("value", NONSENSE)
def test_codex_expiry_that_is_not_a_number_is_unknown(value):
    assert codex().liveness(_codex_blob(value), now_ms=NOW).state == UNKNOWN


def test_a_sane_expiry_is_still_read(paths):
    """The guard must not swallow the ordinary case with the nonsense."""
    seconds = healthy_ms(5) // 1000
    liveness = codex().liveness(_codex_blob(str(seconds)),
                                now_ms=healthy_ms(0))
    assert liveness.expires_at_ms == seconds * 1000
    assert liveness.days_left in (4, 5)


@pytest.mark.parametrize("value", NONSENSE + ["1e30", "-1e30"])
def test_codex_reset_time_that_is_not_a_date_is_dropped(value):
    limits = json.loads('{"primary": {"used_percent": 2, "window_minutes": 300,'
                        ' "resets_at": %s}}' % value)

    parsed = usage.parse_codex_rate_limits(limits)

    assert parsed.bars[0].percent == 2
    assert parsed.bars[0].resets_at is None


@pytest.mark.parametrize("value", NONSENSE)
def test_codex_usage_that_is_not_a_number_is_dropped(value):
    limits = json.loads('{"primary": {"used_percent": %s, "window_minutes": 300},'
                        ' "secondary": {"used_percent": 4,'
                        ' "window_minutes": 10080}}' % value)

    parsed = usage.parse_codex_rate_limits(limits)

    assert [bar.label for bar in parsed.bars] == ["week"]


@pytest.mark.parametrize("blob", [
    '{"fetchedAtMs": %s, "utilization": {"five_hour": {"utilization": 5}}}',
    '{"utilization": {"limits": [{"kind": "session", "percent": %s}],'
    ' "five_hour": {"utilization": 5}}}',
    '{"utilization": {"five_hour": {"utilization": %s},'
    ' "limits": [{"kind": "session", "percent": 5}]}}',
])
@pytest.mark.parametrize("value", NONSENSE)
def test_claude_usage_survives_numbers_that_are_not(blob, value):
    parsed = usage.parse(json.loads(blob % value))

    assert [(bar.label, bar.percent) for bar in parsed.bars] == [("session", 5)]
    assert parsed.fetched_at_ms is None


# -- the usage figures filed on every refresh -------------------------------

def test_recording_usage_survives_a_sidecar_that_cannot_be_written(
        paths, monkeypatch):
    """capture_live runs while the window draws, to give the active card
    something to show. It is display only: a sidecar held by a virus scanner
    is a figure not recorded this time, not a window that fails to open."""
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_claude_json(paths, email="w@example.test")
    before = paths.account("claude", "Work").read_bytes()

    def locked(path, config):
        raise PermissionError("the file is in use")

    monkeypatch.setattr(configjson, "write_atomic", locked)

    assert usage.capture_live(paths, "claude", "Work", now_ms=NOW) is False
    assert paths.account("claude", "Work").read_bytes() == before
