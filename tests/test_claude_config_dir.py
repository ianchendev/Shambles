"""CLAUDE_CONFIG_DIR moves the config file too, and Shambles follows it.

Claude Code 2.1.300 keeps its global config at
``$CLAUDE_CONFIG_DIR/.claude.json`` when that variable is set, and at
``~/.claude.json`` only when it is not. Shambles already followed the
variable for the login (``{config_dir}/.credentials.json``) but read and
spliced ``~/.claude.json`` regardless: with the variable set it showed and
filed the identity of whatever account last used the default location, and
spliced the switched-to account into a file Claude Code was not reading.

Two more rules from the same client: a non-empty legacy ``.config.json``
inside the config directory wins over both, and a custom OAuth endpoint
(``CLAUDE_CODE_CUSTOM_OAUTH_URL``) gives the file a ``-custom-oauth`` suffix.
"""

import json

import pytest

from helpers import (NOW, account, make_profile, write_json)
from shambles import providers, state, switcher, usage


def claude(env):
    return providers.load("claude", env=env)


@pytest.fixture
def relocated(paths):
    """CLAUDE_CONFIG_DIR points at ~/alt; a stale ~/.claude.json names
    somebody else, as it would after the variable was introduced."""
    alt = paths.home / "alt"
    alt.mkdir()
    write_json(paths.claude_json, {"oauthAccount": account("stale@example.test"),
                                   "keep": "untouched"})
    return paths, alt, {"CLAUDE_CONFIG_DIR": str(alt)}


def login(paths, alt, email, token):
    write_json(alt / ".claude.json", {"oauthAccount": account(email),
                                      "projects": {"/p": {}}})
    write_json(alt / ".credentials.json", {"claudeAiOauth": {
        "accessToken": token, "refreshToken": f"r-{token}",
        "refreshTokenExpiresAt": NOW + 20 * 86_400_000}})


def test_the_live_identity_comes_from_the_relocated_config(relocated):
    paths, alt, env = relocated
    login(paths, alt, "w@example.test", "tok-w")

    assert state.live_email(paths, claude(env),
                            platform="linux") == "w@example.test"


def test_a_switch_splices_the_relocated_config_and_leaves_home_alone(
        relocated):
    paths, alt, env = relocated
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    login(paths, alt, "w@example.test", "tok-w")
    home_config = paths.claude_json.read_bytes()

    switcher.switch(paths, claude(env), "Personal", platform="linux",
                    sleep=lambda _: None)

    spliced = json.loads((alt / ".claude.json").read_text(encoding="utf-8"))
    assert spliced["oauthAccount"]["emailAddress"] == "p@example.test"
    assert spliced["projects"] == {"/p": {}}
    assert paths.claude_json.read_bytes() == home_config


def test_the_outgoing_identity_is_filed_from_the_relocated_config(relocated):
    paths, alt, env = relocated
    make_profile(paths, "claude", "Work", active=True)       # no identity yet
    make_profile(paths, "claude", "Personal", email="p@example.test")
    login(paths, alt, "w@example.test", "tok-w")

    switcher.switch(paths, claude(env), "Personal", platform="linux",
                    sleep=lambda _: None)

    assert state.profile_email(paths, claude(env), "Work") == "w@example.test"


def test_usage_is_read_from_the_relocated_config(relocated):
    paths, alt, env = relocated
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    login(paths, alt, "w@example.test", "tok-w")
    data = json.loads((alt / ".claude.json").read_text(encoding="utf-8"))
    data["cachedUsageUtilization"] = {
        "accountUuid": "uuid-a", "fetchedAtMs": NOW,
        "utilization": {"five_hour": {"utilization": 42}}}
    write_json(alt / ".claude.json", data)

    assert usage.capture_live(paths, "claude", "Work", now_ms=NOW,
                              provider=claude(env)) is True
    stored = json.loads(paths.account("claude", "Work").read_text())
    assert stored["usage"]["utilization"]["five_hour"]["utilization"] == 42


def test_a_legacy_config_file_in_the_config_dir_wins(paths):
    """Older installs kept the global config as ~/.claude/.config.json, and
    Claude Code still reads that first when it is not empty."""
    env = {}
    write_json(paths.claude_json, {"oauthAccount": account("new@example.test")})
    write_json(paths.claude_dir / ".config.json",
               {"oauthAccount": account("legacy@example.test")})
    (paths.claude_dir / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "t", "refreshToken": "r"}}),
        encoding="utf-8")

    assert state.live_email(paths, claude(env),
                            platform="linux") == "legacy@example.test"


def test_an_empty_legacy_config_file_does_not(paths):
    write_json(paths.claude_json, {"oauthAccount": account("new@example.test")})
    paths.claude_dir.mkdir(exist_ok=True)
    (paths.claude_dir / ".config.json").write_text("", encoding="utf-8")
    (paths.claude_dir / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": "t", "refreshToken": "r"}}),
        encoding="utf-8")

    assert state.live_email(paths, claude({}),
                            platform="linux") == "new@example.test"


def test_a_custom_oauth_endpoint_has_its_own_config_file(paths):
    env = {"CLAUDE_CODE_CUSTOM_OAUTH_URL": "https://auth.example.test"}

    assert claude(env).config_file(home=paths.home) == (
        paths.home / ".claude-custom-oauth.json")


def test_without_the_variable_nothing_moves(paths):
    assert claude({}).config_file(home=paths.home) == paths.claude_json


# -- found by an independent review of the first version ---------------------

def test_setting_the_variable_to_its_default_still_moves_the_config_file(
        paths):
    """CLAUDE_CONFIG_DIR=~/.claude changes nothing for the login, but the
    config file moves from ~/.claude.json to ~/.claude/.claude.json, which
    the VS Code extension (no inherited environment) never reads. So it is
    an override worth a banner."""
    env = {"CLAUDE_CONFIG_DIR": str(paths.home / ".claude")}

    assert state.config_dir_override(claude(env), home=paths.home,
                                     env=env) is not None


def test_the_migration_files_the_identity_claude_code_is_using(paths):
    """A non-empty legacy .config.json in the linked profile is what Claude
    Code reads; ~/.claude.json is stale beside it."""
    import os
    from helpers import make_claude_json, make_legacy_profile
    from shambles import migrate

    make_legacy_profile(paths, "Admin", email="admin@example.test", sessions=5)
    make_legacy_profile(paths, "Work", email="work@example.test", sessions=2)
    write_json(paths.legacy_profiles_dir / "Admin" / ".config.json",
               {"oauthAccount": account("admin@example.test")})
    make_claude_json(paths, email="stale@example.test")
    os.symlink(str(paths.legacy_profiles_dir / "Admin"), str(paths.claude_dir),
               target_is_directory=True)

    migrate.run(paths, now_ms=NOW)

    assert state.profile_email(paths, claude({}), "Admin") == \
        "admin@example.test"


def test_an_unreadable_relocated_config_is_named_in_the_refusal(relocated):
    from shambles.errors import ShamblesError

    paths, alt, env = relocated
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    (alt / ".claude.json").write_text("{not json", encoding="utf-8")
    (alt / ".credentials.json").write_bytes(
        paths.credentials("claude", "Work").read_bytes())

    with pytest.raises(ShamblesError) as raised:
        switcher.switch(paths, claude(env), "Other", platform="linux",
                        sleep=lambda _: None)

    assert str(alt / ".claude.json") in str(raised.value)


def test_the_backup_is_taken_of_the_relocated_config(relocated):
    paths, alt, env = relocated
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.test")
    login(paths, alt, "w@example.test", "tok-w")
    before = (alt / ".claude.json").read_text(encoding="utf-8")

    switcher.switch(paths, claude(env), "Personal", platform="linux",
                    sleep=lambda _: None)

    backups = sorted(paths.backup_dir.glob("claude.json.*"))
    assert backups and backups[-1].read_text(encoding="utf-8") == before


def test_a_parked_profiles_usage_is_read_from_the_relocated_config(relocated):
    from shambles import profiles

    paths, alt, env = relocated
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    login(paths, alt, "w@example.test", "tok-w")
    data = json.loads((alt / ".claude.json").read_text(encoding="utf-8"))
    data["cachedUsageUtilization"] = {
        "accountUuid": "uuid-a", "fetchedAtMs": NOW,
        "utilization": {"five_hour": {"utilization": 61}}}
    write_json(alt / ".claude.json", data)

    found = profiles.resolve_usage(paths, claude(env), "Work", "Work")

    assert [bar.percent for bar in found.bars] == [61]


def test_an_empty_writable_legacy_file_wins_while_the_new_one_is_missing(
        paths):
    paths.claude_dir.mkdir()
    (paths.claude_dir / ".config.json").write_text("", encoding="utf-8")

    assert claude({}).config_file(home=paths.home) == (
        paths.claude_dir / ".config.json")
