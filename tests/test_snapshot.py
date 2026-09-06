"""The view model, and the wire contract it serialises to.

Everything a native shell displays is decided here rather than in the shell, so
these tests are what stop a Swift or C# client re-deriving a rule and drifting
from it.
"""

import json

import pytest

from helpers import (DAY_MS, NOW, make_claude_json, make_live_claude_login,
                     make_profile)
from shambles import providers, state
from shambles.app import cli, snapshot as snap
from shambles.app.service import ActionResult


@pytest.fixture
def claude():
    return providers.load("claude")


def build(paths, *, now_ms=NOW):
    return snap.build(paths=paths, providers=providers.all_providers(),
                      platform="linux", now_ms=now_ms)


def group_of(paths, provider_id, **kw):
    return next(g for g in build(paths, **kw).groups
                if g.provider == provider_id)


# -- structure ----------------------------------------------------------------


def test_every_provider_gets_a_group_even_with_no_accounts(paths):
    result = build(paths)
    assert [g.provider for g in result.groups] == providers.ids()
    assert all(g.accounts == [] for g in result.groups)


def test_a_group_lists_the_surfaces_one_switch_moves(paths):
    """Shown as pills. Without them nobody can tell that switching Codex also
    changes ChatGPT.app, or that Terminal and VS Code cannot hold different
    accounts at all."""
    groups = {g.provider: g for g in build(paths).groups}
    assert [s.id for s in groups["claude"].surfaces] == ["terminal", "vscode"]
    assert [s.id for s in groups["codex"].surfaces] == \
        ["terminal", "vscode", "chatgpt"]
    assert all(s.label for group in groups.values() for s in group.surfaces)


def test_profiles_are_listed_in_a_stable_order(paths):
    for name in ("zeta", "Alpha", "middle"):
        make_profile(paths, "claude", name)
    assert [a.name for a in group_of(paths, "claude").accounts] == \
        ["Alpha", "middle", "zeta"]


# -- per-account state --------------------------------------------------------


def test_the_active_profile_is_the_one_the_marker_names(paths):
    make_profile(paths, "claude", "Work", active=True)
    make_profile(paths, "claude", "Personal")
    assert [(a.name, a.active) for a in group_of(paths, "claude").accounts] == \
        [("Personal", False), ("Work", True)]


def test_a_profile_with_no_credential_needs_login(paths, claude):
    make_profile(paths, "claude", "Empty", token=False)
    account = group_of(paths, "claude").accounts[0]
    assert account.needs_login is True
    assert account.login_hint == claude.login_hint()


def test_a_lapsed_profile_carries_the_command_that_fixes_it(paths):
    """A closed window is a handoff, so the row has to say what to run."""
    make_profile(paths, "claude", "Old", refresh_expires_ms=NOW - DAY_MS)
    account = group_of(paths, "claude").accounts[0]
    assert account.needs_login is True
    assert account.login_hint


def test_a_healthy_profile_does_not_ask_for_login(paths):
    make_profile(paths, "claude", "Work", refresh_expires_ms=NOW + 30 * DAY_MS)
    account = group_of(paths, "claude").accounts[0]
    assert account.needs_login is False
    assert account.login_hint is None, "a healthy row must carry no hint"


def test_identity_and_plan_reach_the_contract(paths):
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com", extra={
        "oauthAccount": {"emailAddress": "work@example.com",
                         "organizationRateLimitTier": "default_claude_max_5x"}})
    account = group_of(paths, "claude").accounts[0]
    assert account.email == "work@example.com"
    assert account.plan == "default_claude_max_5x"


def test_a_parked_profile_shows_its_own_email(paths):
    """Claude keeps identity outside the credential. Reading the live file for
    every row would label them all with whoever is signed in now."""
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="personal@example.com")
    make_claude_json(paths, email="work@example.com")

    by_name = {a.name: a for a in group_of(paths, "claude").accounts}
    assert by_name["Personal"].email == "personal@example.com"


def test_a_corrupt_credential_still_lists_the_profile(paths):
    """One bad file must not take down a whole panel."""
    make_profile(paths, "claude", "Broken")
    paths.credentials("claude", "Broken").write_text("{ not json")
    assert "Broken" in [a.name for a in group_of(paths, "claude").accounts]


# -- quota --------------------------------------------------------------------


def test_usage_reaches_the_contract_when_there_is_any(paths):
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": {
            "fetchedAtMs": NOW, "accountUuid": "uuid-a",
            "utilization": {"limits": [
                {"kind": "session", "percent": 22, "severity": "normal"},
                {"kind": "weekly_all", "percent": 87, "severity": "warning"}]}}})

    account = group_of(paths, "claude").accounts[0]
    assert [(w.label, w.used_percent) for w in account.usage] == \
        [("session", 22), ("week", 87)]


def test_no_usage_is_a_supported_state_not_a_gap(paths):
    """Codex publishes nothing readable, so an empty list has to be normal."""
    make_profile(paths, "codex", "Personal", active=True)
    assert group_of(paths, "codex").accounts[0].usage == []


# -- the wire contract --------------------------------------------------------


def test_the_contract_carries_a_version(paths):
    """A shell meeting an unknown version must say "update Shambles" rather
    than guess: the app bundle and the CLI ship separately."""
    payload = snap.to_dict(build(paths))
    assert payload["version"] == snap.CONTRACT_VERSION
    assert isinstance(payload["version"], int)


def test_the_contract_is_json_serialisable(paths):
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_profile(paths, "codex", "Personal")
    text = json.dumps(snap.to_dict(build(paths)))
    assert json.loads(text)["version"] == snap.CONTRACT_VERSION


def test_the_contract_exposes_every_field_a_shell_renders(paths):
    """A field missing here is a field the shell will derive instead, and that
    derivation is untested."""
    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": {
            "fetchedAtMs": NOW, "accountUuid": "uuid-a",
            "utilization": {"limits": [
                {"kind": "session", "percent": 5, "severity": "normal"}]}}})

    group = snap.to_dict(build(paths))["groups"][0]
    assert set(group) == {"provider", "display_name", "surfaces", "accounts"}
    assert set(group["surfaces"][0]) == {"id", "label", "detail"}
    assert set(group["accounts"][0]) == {
        "name", "email", "display_name", "plan", "active", "state",
        "needs_login", "login_hint", "usage"}
    assert set(group["accounts"][0]["usage"][0]) == {
        "label", "used_percent", "resets_at_ms", "resets_label",
        "age_label", "stale"}


def test_the_panel_and_the_window_agree_about_disk(paths):
    """Both read through profiles.discover, so a shell can never show a
    different set of accounts than the window does."""
    from shambles import profiles as profiles_mod
    make_profile(paths, "claude", "Work", active=True)
    make_profile(paths, "claude", "Personal")

    direct = profiles_mod.discover(paths, providers.load("claude"),
                                   state.read_active(paths, "claude"), NOW,
                                   platform="linux")
    assert [a.name for a in group_of(paths, "claude").accounts] == \
        [p.name for p in direct]


# -- command line -------------------------------------------------------------


@pytest.mark.parametrize("argv", [
    ["--home", "{home}", "list", "--json"],   # flag before the subcommand
    ["list", "--home", "{home}", "--json"],   # and after
])
def test_home_is_honoured_from_either_position(argv, paths, capsys):
    """A shared argparse argument defined on both parent and subparser is
    written twice, and the subparser's default wins. Suppressing that default
    is what keeps both orders working -- native shells use the first."""
    from shambles.__main__ import main
    make_profile(paths, "claude", "Work", active=True)

    assert main([a.format(home=str(paths.home)) for a in argv]) == 0
    payload = json.loads(capsys.readouterr().out)
    claude = next(g for g in payload["groups"] if g["provider"] == "claude")
    assert [a["name"] for a in claude["accounts"]] == ["Work"]


def test_the_json_flag_emits_one_line_for_easy_piping(paths, capsys):
    from shambles.__main__ import main
    main(["--home", str(paths.home), "list", "--json"])
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


def test_cli_switch_calls_application_service(paths, monkeypatch):
    called = []
    monkeypatch.setattr(
        "shambles.app.cli.ShamblesService.switch",
        lambda self, provider, account:
            called.append((provider, account)) or ActionResult(True, "switch"))
    assert cli.main(["--home", str(paths.home), "switch",
                     "claude", "Work"]) == 0
    assert called == [("claude", "Work")]


def test_switching_through_the_cli_uses_the_shared_switcher(paths):
    """The CLI does not reimplement the switch. A second implementation is a
    second chance to get the ordering wrong, and the ordering is what stops a
    failure destroying the account being switched away from."""
    from shambles.__main__ import main
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_live_claude_login(paths)

    assert main(["--home", str(paths.home), "switch", "claude", "Personal"]) == 0
    assert state.read_active(paths, "claude") == "Personal"


def test_a_refused_switch_reports_why_and_exits_non_zero(paths, capsys):
    from shambles.__main__ import main
    assert main(["--home", str(paths.home), "switch", "claude", "Nope",
                 "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert "Nope" in payload["error"]["message"]


def test_an_unknown_provider_still_exits_non_zero(paths, capsys):
    from shambles.__main__ import main

    assert main(["--home", str(paths.home), "switch", "unknown", "Work",
                 "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_provider"
