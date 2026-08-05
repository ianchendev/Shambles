import json
import os

import pytest

from helpers import NOW, make_claude_json, make_profile, write_json
from shambles import configjson, links, profiles, switcher
from shambles.errors import ForeignLinkError, ProfileNotFoundError


def _clock():
    return NOW


def _no_sleep(_seconds):
    pass


def _setup(paths, active="Work"):
    """Two profiles, ~/.claude pointing at `active`, a live ~/.claude.json."""
    make_profile(paths, "Work", email="work@example.com")
    make_profile(paths, "Personal", email="personal@example.com")
    make_claude_json(paths, email="work@example.com")
    os.symlink(str(paths.profile_dir(active)), str(paths.claude_dir),
               target_is_directory=True)


def _switch(paths, name):
    return switcher.switch(paths, name, now_ms_fn=_clock, sleep=_no_sleep)


# ---- the core promise ---------------------------------------------------

def test_credentials_survive_a_round_trip_unmodified(paths):
    """The whole point: switching away and back must not disturb the refresh
    token, or the user is sent back to the email verification flow."""
    _setup(paths)
    before = (paths.profile_dir("Work") / ".credentials.json").read_bytes()

    _switch(paths, "Personal")
    _switch(paths, "Work")

    after = (paths.profile_dir("Work") / ".credentials.json").read_bytes()
    assert after == before
    payload = json.loads(after)["claudeAiOauth"]
    assert payload["refreshToken"] == "refresh"
    assert payload["refreshTokenExpiresAt"] == NOW + 30 * 86_400_000


# ---- link and identity --------------------------------------------------

def test_switch_repoints_the_link(paths):
    _setup(paths)
    state = _switch(paths, "Personal")
    assert state.kind == links.MANAGED
    assert state.profile == "Personal"


def test_switch_stashes_the_outgoing_identity(paths):
    _setup(paths)
    _switch(paths, "Personal")
    stashed = configjson.read_sidecar(paths.sidecar("Work"))
    assert stashed["oauthAccount"]["emailAddress"] == "work@example.com"
    assert stashed["cachedUsageUtilization"]["accountUuid"] == "uuid-a"


def test_switch_splices_the_incoming_identity(paths):
    _setup(paths)
    _switch(paths, "Personal")
    live = configjson.load(paths.claude_json)
    assert live["oauthAccount"]["emailAddress"] == "personal@example.com"


def test_switch_preserves_shared_state(paths):
    _setup(paths)
    _switch(paths, "Personal")
    live = configjson.load(paths.claude_json)
    assert live["projects"] == {"/some/dir": {"allowedTools": []}}
    assert live["numStartups"] == 42
    assert live["machineID"] == "machine"


def test_switch_to_profile_without_sidecar_clears_identity(paths):
    _setup(paths)
    make_profile(paths, "Fresh", token=False)
    _switch(paths, "Fresh")
    live = configjson.load(paths.claude_json)
    assert "oauthAccount" not in live
    assert "cachedUsageUtilization" not in live
    assert live["projects"] == {"/some/dir": {"allowedTools": []}}


def test_switching_to_a_lapsed_profile_is_not_an_error(paths):
    """A dead refresh token needs no cleanup. Shambles does not validate
    tokens -- it moves a symlink. Claude Code then fails its refresh and
    prompts /login, which overwrites .credentials.json anyway. So a stale
    file is never in the way, and deleting it would only destroy the
    evidence of which account the profile belonged to."""
    _setup(paths)
    stale = make_profile(paths, "Lapsed", email="lapsed@example.com",
                         refresh_expires_ms=NOW - 12 * 86_400_000)
    before = (stale / ".credentials.json").read_bytes()

    state = _switch(paths, "Lapsed")

    assert state.kind == links.MANAGED
    assert state.profile == "Lapsed"
    assert (stale / ".credentials.json").read_bytes() == before
    # the UI still knows whose account it was, and says so plainly
    p = [x for x in profiles.discover(paths, "Lapsed", NOW) if x.name == "Lapsed"][0]
    assert p.email == "lapsed@example.com"
    assert p.token_state == profiles.TOKEN_EXPIRED
    assert profiles.expiry_label(p) == "expired 12d ago"


def test_switch_backs_up_claude_json(paths):
    _setup(paths)
    _switch(paths, "Personal")
    assert (paths.backup_dir / f"claude.json.{NOW}").exists()


# ---- guards -------------------------------------------------------------

def test_switch_to_active_profile_is_a_noop(paths):
    _setup(paths)
    before = paths.claude_json.read_bytes()
    state = _switch(paths, "Work")
    assert state.profile == "Work"
    assert paths.claude_json.read_bytes() == before
    assert not paths.backup_dir.exists()


def test_switch_to_unknown_profile_raises(paths):
    _setup(paths)
    with pytest.raises(ProfileNotFoundError):
        _switch(paths, "Nope")


def test_switch_refuses_a_foreign_link(paths, tmp_path):
    make_profile(paths, "Work", email="work@example.com")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    os.symlink(str(elsewhere), str(paths.claude_dir), target_is_directory=True)
    with pytest.raises(ForeignLinkError):
        _switch(paths, "Work")


def test_switch_repairs_a_dangling_link(paths):
    _setup(paths, active="Work")
    make_profile(paths, "Spare", email="spare@example.com")
    for child in paths.profile_dir("Work").iterdir():
        child.unlink()
    paths.profile_dir("Work").rmdir()
    assert links.inspect(paths).kind == links.DANGLING

    state = _switch(paths, "Spare")
    assert state.kind == links.MANAGED
    assert state.profile == "Spare"


# ---- VS Code handshake --------------------------------------------------

def test_switch_carries_ide_lock_files(paths):
    _setup(paths)
    write_json(paths.profile_dir("Work") / "ide" / "60144.lock",
               {"pid": 1120, "ideName": "Visual Studio Code",
                "transport": "ws", "authToken": "uuid"})

    _switch(paths, "Personal")

    carried = paths.profile_dir("Personal") / "ide" / "60144.lock"
    assert carried.exists()
    assert json.loads(carried.read_text(encoding="utf-8"))["pid"] == 1120
    # copied, not moved -- the source stays valid for switching back
    assert (paths.profile_dir("Work") / "ide" / "60144.lock").exists()


def test_ide_lock_failure_does_not_break_the_switch(paths):
    """A profile whose 'ide' path is a file, not a directory, makes mkdir
    raise. The switch itself must still complete."""
    _setup(paths)
    write_json(paths.profile_dir("Work") / "ide" / "1.lock", {"pid": 1})
    (paths.profile_dir("Personal") / "ide").write_text("not a dir", encoding="utf-8")

    state = _switch(paths, "Personal")

    assert state.profile == "Personal"
    assert configjson.load(paths.claude_json)["oauthAccount"]["emailAddress"] == \
        "personal@example.com"


def test_carry_ide_locks_is_silent_when_source_has_none(paths):
    a = make_profile(paths, "A")
    b = make_profile(paths, "B")
    switcher.carry_ide_locks(a, b)
    assert not (b / "ide").exists()
