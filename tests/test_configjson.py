import json

import pytest

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


def test_extract_pulls_only_the_identity(paths):
    """Usage figures are deliberately not captured -- they are a cache with a
    server-side truth, and a stashed copy is stale the moment it is written."""
    data = make_claude_json(paths)
    got = configjson.extract_account_keys(data)
    assert set(got) == {"oauthAccount"}


def test_apply_preserves_every_other_key_and_order(paths):
    make_claude_json(paths, email="old@example.com")
    before = json.loads(paths.claude_json.read_text(encoding="utf-8"))

    configjson.apply_account_keys(
        paths.claude_json, {"oauthAccount": account("new@example.com")})

    after = json.loads(paths.claude_json.read_text(encoding="utf-8"))
    # cachedUsageUtilization is dropped on purpose, so compare the rest
    expected = [k for k in before if k != "cachedUsageUtilization"]
    assert list(after.keys()) == expected
    assert after["numStartups"] == before["numStartups"]
    assert after["projects"] == before["projects"]
    assert after["machineID"] == before["machineID"]
    assert after["oauthAccount"]["emailAddress"] == "new@example.com"


def test_apply_with_empty_account_deletes_identity_and_cache(paths):
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
    sidecar = paths.account("Work")
    sidecar.parent.mkdir(parents=True)
    configjson.write_sidecar(sidecar, {"oauthAccount": account("w@example.com")}, NOW)

    got = configjson.read_sidecar(sidecar)
    assert got["oauthAccount"]["emailAddress"] == "w@example.com"
    assert "stashed_at" not in got  # read_sidecar returns account keys only
    assert json.loads(sidecar.read_text(encoding="utf-8"))["stashed_at"] == NOW


def test_read_missing_sidecar_returns_empty(paths):
    assert configjson.read_sidecar(paths.account("Ghost")) == {}


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


# ---- usage figures are a cache, not identity ----------------------------
# cachedUsageUtilization carries its own fetchedAtMs and is refetched from the
# server. Restoring a profile's stashed copy re-displays whatever the numbers
# were when that profile was last active -- hours or days out of date -- which
# is worse than having none, because the UI cannot tell stale from current.

def test_switching_clears_cached_usage_rather_than_restoring_it(paths):
    stale = {"oauthAccount": account("work@example.com"),
             "cachedUsageUtilization": {"fetchedAtMs": 1, "accountUuid": "uuid-a",
                                        "utilization": {"five_hour": {"utilization": 11}}}}
    write_json(paths.account("Work"), stale)
    make_claude_json(paths, email="someone@example.com")

    configjson.apply_account_keys(
        paths.claude_json, configjson.read_sidecar(paths.account("Work")))

    after = configjson.load(paths.claude_json)
    assert after["oauthAccount"]["emailAddress"] == "work@example.com"
    assert "cachedUsageUtilization" not in after, \
        "restored a stale usage cache; Claude Code should refetch instead"


def test_the_outgoing_accounts_usage_never_lingers(paths):
    """The original reason this key was handled at all: leaving account A's
    figures behind shows the wrong account's usage under account B."""
    make_claude_json(paths, email="a@example.com")
    assert "cachedUsageUtilization" in configjson.load(paths.claude_json)

    configjson.apply_account_keys(
        paths.claude_json, {"oauthAccount": account("b@example.com")})

    assert "cachedUsageUtilization" not in configjson.load(paths.claude_json)


def test_stashing_does_not_capture_usage(paths):
    """No point stashing what is never restored."""
    make_claude_json(paths, email="work@example.com")
    captured = configjson.extract_account_keys(
        configjson.load(paths.claude_json))
    assert "oauthAccount" in captured
    assert "cachedUsageUtilization" not in captured
