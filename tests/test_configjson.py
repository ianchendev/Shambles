import json
import os
import stat

import pytest

from conftest import posix_modes_only
from helpers import NOW, account, make_claude_json, write_json
from shambles import configjson
from shambles.errors import ConfigUnreadableError


def test_load_missing_file_returns_empty(tmp_path):
    assert configjson.load(tmp_path / "nope.json") == {}


def test_load_malformed_file_returns_empty(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{ not json", encoding="utf-8")
    assert configjson.load(bad) == {}


def test_load_non_dict_returns_empty(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2]", encoding="utf-8")
    assert configjson.load(arr) == {}


def test_extract_pulls_only_account_keys(paths):
    data = make_claude_json(paths)
    got = configjson.extract_account_keys(data)
    assert set(got) == {"oauthAccount", "cachedUsageUtilization"}


def test_apply_preserves_every_other_key_and_order(paths):
    make_claude_json(paths, email="old@example.com")
    before = json.loads(paths.claude_json.read_text(encoding="utf-8"))

    configjson.apply_account_keys(
        paths.claude_json,
        {"oauthAccount": account("new@example.com"),
         "cachedUsageUtilization": {"accountUuid": "uuid-b"}},
    )

    after = json.loads(paths.claude_json.read_text(encoding="utf-8"))
    assert list(after.keys()) == list(before.keys())
    assert after["numStartups"] == before["numStartups"]
    assert after["projects"] == before["projects"]
    assert after["machineID"] == before["machineID"]
    assert after["oauthAccount"]["emailAddress"] == "new@example.com"
    assert after["cachedUsageUtilization"]["accountUuid"] == "uuid-b"


def test_apply_with_empty_account_deletes_both_keys(paths):
    make_claude_json(paths)
    configjson.apply_account_keys(paths.claude_json, {})
    after = json.loads(paths.claude_json.read_text(encoding="utf-8"))
    assert "oauthAccount" not in after
    assert "cachedUsageUtilization" not in after
    assert after["projects"] == {"/some/dir": {"allowedTools": []}}


def test_apply_leaves_no_temp_file(paths):
    make_claude_json(paths)
    configjson.apply_account_keys(paths.claude_json, {})
    leftovers = list(paths.home.glob(".claude.json.*"))
    assert leftovers == []


def test_sidecar_round_trip(paths):
    sidecar = paths.account("claude", "Work")
    sidecar.parent.mkdir(parents=True)
    configjson.write_sidecar(sidecar, {"oauthAccount": account("w@example.com")}, NOW)

    got = configjson.read_sidecar(sidecar)
    assert got["oauthAccount"]["emailAddress"] == "w@example.com"
    assert "stashed_at" not in got  # read_sidecar returns account keys only
    assert json.loads(sidecar.read_text(encoding="utf-8"))["stashed_at"] == NOW


def test_read_missing_sidecar_returns_empty(paths):
    assert configjson.read_sidecar(paths.account("claude", "Ghost")) == {}


def test_backup_copies_and_returns_path(paths):
    make_claude_json(paths)
    dest = configjson.backup(paths.claude_json, paths.backup_dir, NOW)
    assert dest == paths.backup_dir / f"claude.json.{NOW}"
    assert dest.exists()


def test_backup_of_missing_file_is_none(paths):
    assert configjson.backup(paths.claude_json, paths.backup_dir, NOW) is None


def test_backup_prunes_to_ten_newest(paths):
    make_claude_json(paths)
    for i in range(14):
        configjson.backup(paths.claude_json, paths.backup_dir, NOW + i)
    kept = sorted(p.name for p in paths.backup_dir.glob("claude.json.*"))
    assert len(kept) == 10
    assert f"claude.json.{NOW + 13}" in kept
    assert f"claude.json.{NOW}" not in kept


# ---- refusing to clobber an unreadable config ---------------------------
# ~/.claude.json holds every project, MCP server and machine ID. Claude Code
# rewrites it on its own schedule, so a read landing mid-write sees truncated
# JSON. load() answers {} for anything unusable, which is right for merely
# displaying a profile -- but splicing on top of that {} and writing it back
# would replace the user's entire config with two keys.

def test_refuses_to_splice_onto_an_unparseable_config(paths):
    paths.claude_json.write_text('{"projects": {"a": 1}, "mcpServers": {trunc')
    before = paths.claude_json.read_text()

    with pytest.raises(ConfigUnreadableError):
        configjson.apply_account_keys(paths.claude_json, {"oauthAccount": {"x": 1}})

    assert paths.claude_json.read_text() == before, "config was modified anyway"


def test_refuses_when_the_config_is_a_json_array(paths):
    paths.claude_json.write_text('["not", "an", "object"]')
    with pytest.raises(ConfigUnreadableError):
        configjson.apply_account_keys(paths.claude_json, {})


def test_still_creates_a_config_that_does_not_exist(paths):
    """Absent is not the same as corrupt: a fresh machine must still work."""
    assert not paths.claude_json.exists()
    configjson.apply_account_keys(paths.claude_json, {"oauthAccount": {"e": 1}})
    assert configjson.load(paths.claude_json)["oauthAccount"] == {"e": 1}


def test_treats_an_empty_file_as_absent(paths):
    paths.claude_json.write_text("")
    configjson.apply_account_keys(paths.claude_json, {"oauthAccount": {"e": 2}})
    assert configjson.load(paths.claude_json)["oauthAccount"] == {"e": 2}


def test_preserves_every_unrelated_key_when_splicing(paths):
    original = {
        "projects": {"/a": {"history": ["one", "two"]}},
        "mcpServers": {"srv": {"cmd": "x"}},
        "userID": "abc123",
        "oauthAccount": {"emailAddress": "old@example.com"},
    }
    paths.claude_json.write_text(json.dumps(original))

    configjson.apply_account_keys(
        paths.claude_json, {"oauthAccount": {"emailAddress": "new@example.com"}})

    after = configjson.load(paths.claude_json)
    assert after["projects"] == original["projects"], "prompt history lost"
    assert after["mcpServers"] == original["mcpServers"]
    assert after["userID"] == "abc123"
    assert after["oauthAccount"]["emailAddress"] == "new@example.com"


@posix_modes_only
def test_a_leftover_temp_file_does_not_expose_the_next_write(tmp_path, monkeypatch):
    """Same defect as ``FileStore.write``, in ``write_atomic``'s own temp
    file: ``O_CREAT``'s mode argument is ignored when the file already
    exists, so a ``*.shambles-tmp`` left at a loose mode by a crashed run
    would take the next write's full plaintext payload before anything
    restricted it.

    Observed at the ``chmod`` call, filtered to regular non-empty files: the
    one vantage point that catches the bytes at rest under both the old
    buffered-text implementation and the current descriptor-based one. An
    earlier version spied on ``os.write``, which the old code never called at
    all -- so reverting the fix failed with "os.write was never called"
    rather than with a loose mode, detecting an implementation change instead
    of an exposure.
    """
    target = tmp_path / "config.json"
    tmp = target.with_name(target.name + configjson.TMP_SUFFIX)
    tmp.write_bytes(b"stale content from a crashed run")
    os.chmod(tmp, 0o644)

    observed = {}
    real_chmod = os.chmod

    def spy(path, mode, *args, **kwargs):
        try:
            info = os.stat(path)
            if stat.S_ISREG(info.st_mode) and info.st_size:
                observed.setdefault("mode", oct(info.st_mode)[-3:])
        except OSError:
            pass
        return real_chmod(path, mode, *args, **kwargs)

    monkeypatch.setattr(os, "chmod", spy)
    previous = os.umask(0o022)
    try:
        configjson.write_atomic(target, {"oauthAccount": {"emailAddress": "a@b.com"}})
    finally:
        os.umask(previous)

    assert observed.get("mode") == "600", (
        f"config was on disk at {observed.get('mode')} before being "
        f"restricted to 0600")


@posix_modes_only
def test_backups_are_locked_down_like_the_rest_of_the_store(paths):
    """They are copies of ~/.claude.json: no token, but the account's email,
    organisation and UUIDs. The README promises 0700 throughout the store, and
    this directory was the one place that promise was not kept."""
    make_claude_json(paths)
    dest = configjson.backup(paths.claude_json, paths.backup_dir, NOW)

    assert oct(os.stat(paths.backup_dir).st_mode)[-3:] == "700"
    assert oct(os.stat(dest).st_mode)[-3:] == "600"


@posix_modes_only
def test_a_loose_source_does_not_produce_a_loose_backup(paths):
    """shutil.copy2 carries the source's mode across, so a config the vendor
    happened to write 0644 would otherwise be snapshotted 0644."""
    make_claude_json(paths)
    os.chmod(paths.claude_json, 0o644)

    dest = configjson.backup(paths.claude_json, paths.backup_dir, NOW)

    assert oct(os.stat(dest).st_mode)[-3:] == "600"
