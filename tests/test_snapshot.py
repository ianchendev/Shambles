"""The view model, and the wire contract it serialises to.

Everything a native shell displays is decided here rather than in the shell, so
these tests are what stop a Swift or C# client re-deriving a rule and drifting
from it.
"""

import json

import pytest

from conftest import posix_only
from helpers import (DAY_MS, NOW, healthy_ms, make_claude_json,
                     make_live_claude_login, make_profile)
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
    """No Codex session log means an empty list, which the card already handles."""
    make_profile(paths, "codex", "Personal", active=True)
    assert group_of(paths, "codex").accounts[0].usage == []


def test_codex_session_logs_reach_the_contract(paths):
    from helpers import make_codex_session

    make_profile(paths, "codex", "Personal", active=True)
    make_codex_session(paths, used_5h=2.0, used_week=4.0)
    assert [(w.label, w.used_percent) for w in
            group_of(paths, "codex").accounts[0].usage] == \
        [("session", 2), ("week", 4)]


def test_a_parked_codex_profile_does_not_inherit_the_live_session(paths):
    from helpers import make_codex_session

    make_profile(paths, "codex", "Personal", active=True)
    make_profile(paths, "codex", "Work")
    make_codex_session(paths)
    by_name = {a.name: a for a in group_of(paths, "codex").accounts}
    assert by_name["Personal"].usage
    assert by_name["Work"].usage == []


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
    assert set(group) == {"provider", "display_name", "surfaces", "accounts",
                          "state", "live_email", "can_save", "notices",
                          "can_sign_in", "cli"}
    assert set(group["surfaces"][0]) == {"id", "label", "detail"}
    assert set(group["accounts"][0]) == {
        "name", "email", "display_name", "plan", "active", "state",
        "needs_login", "login_hint", "usage", "expires_at_ms",
        "status_label", "publishes_usage", "renewed_by_use", "sign_in_due",
        "expires_label"}
    assert set(group["accounts"][0]["usage"][0]) == {
        "label", "used_percent", "resets_at_ms", "resets_label",
        "age_label", "stale", "severity"}


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
    result_snapshot = snap.Snapshot(snap.CONTRACT_VERSION, [
        snap.Group("claude", "Claude", accounts=[snap.Account("Work")]),
    ])
    monkeypatch.setattr(
        "shambles.app.cli.ShamblesService.switch",
        lambda self, provider, account:
            called.append((provider, account))
            or ActionResult(True, "switch", snapshot=result_snapshot))
    assert cli.main(["--home", str(paths.home), "switch",
                     "claude", "Work"]) == 0
    assert called == [("claude", "Work")]


def test_switch_json_keeps_the_native_shell_contract(paths, capsys):
    """The macOS SwitchOutcome decoder consumes these exact legacy fields."""
    make_profile(paths, "claude", "Work", active=True)
    make_profile(paths, "claude", "Personal", token=False)
    make_live_claude_login(paths)

    assert cli.main(["--home", str(paths.home), "switch", "claude",
                     "Personal", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {
        "version": snap.CONTRACT_VERSION,
        "ok": True,
        "provider": "claude",
        "switched_to": "Personal",
        "needs_login": True,
        "warnings": [],
    }


@pytest.mark.parametrize("as_json", [False, True])
def test_switch_cli_survives_an_unavailable_snapshot(paths, capsys, monkeypatch,
                                                   as_json):
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    make_profile(paths, "codex", "Personal", token=False)

    def broken_snapshot(self):
        raise OSError("snapshot-private-sentinel")

    monkeypatch.setattr("shambles.app.service.ShamblesService.snapshot",
                        broken_snapshot)
    args = ["--home", str(paths.home), "switch", "codex", "Personal"]
    if as_json:
        args.append("--json")
    assert cli.main(args) == 0
    out = capsys.readouterr()
    assert "snapshot-private-sentinel" not in out.out + out.err
    if as_json:
        data = json.loads(out.out)
        assert data["ok"] is True
        assert data["switched_to"] == "Personal"
        assert data["needs_login"] is None
        assert data["warnings"]
    else:
        assert out.out.startswith("Switched codex to Personal.\n")


def test_switch_text_keeps_provider_and_login_hint(paths, capsys):
    make_profile(paths, "claude", "Work", active=True)
    make_profile(paths, "claude", "Personal", token=False)
    make_live_claude_login(paths)

    assert cli.main(["--home", str(paths.home), "switch", "claude",
                     "Personal"]) == 0
    assert capsys.readouterr().out == (
        "Switched claude to Personal.\n"
        "  Run 'claude auth login' in a terminal.\n"
    )


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
    assert payload["error"]["code"] == "refused"
    assert "Nope" in payload["error"]["message"]


def test_an_unknown_provider_still_exits_non_zero(paths, capsys):
    from shambles.__main__ import main

    assert main(["--home", str(paths.home), "switch", "unknown", "Work",
                 "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "unknown_provider"


# -- what is true about the provider, not only its accounts --------------------
#
# Reproduced with `shambles list` and the terminal UI: signed in as an account
# nobody saved, both showed the marked profile as active under the stranger's
# address, and neither said anything was wrong. On a first run with a login
# already present they said "no accounts yet" and nothing about the login.

def notice_codes(group):
    return [n.code for n in group.notices]


def test_a_live_login_nobody_saved_can_be_saved(paths):
    make_claude_json(paths, email="me@example.com")
    make_live_claude_login(paths)

    group = group_of(paths, "claude")

    assert group.state == state.UNMANAGED
    assert group.live_email == "me@example.com"
    assert group.can_save is True
    assert notice_codes(group) == ["unsaved_login"]
    assert "me@example.com" in group.notices[0].message


def test_nothing_to_save_on_a_clean_machine(paths):
    group = group_of(paths, "claude")
    assert group.can_save is False
    assert group.notices == []


def test_a_managed_provider_has_nothing_to_say(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths, access_token="tok-Work")

    group = group_of(paths, "claude")

    assert group.state == state.MANAGED
    assert group.can_save is False
    assert group.notices == []


def test_a_stranger_signed_in_is_named_and_not_shown_as_the_profile(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="stranger@example.com")
    make_live_claude_login(paths, access_token="tok-stranger")

    group = group_of(paths, "claude")
    work = group.accounts[0]

    assert group.state == state.DRIFTED
    assert group.can_save is True
    assert notice_codes(group) == ["unsaved_login"]
    assert "stranger@example.com" in group.notices[0].message
    assert "'Work'" in group.notices[0].message
    # The card is Work's; the stranger belongs in the notice.
    assert work.email == "w@example.com"


def test_a_saved_account_signed_in_under_the_wrong_marker_says_how_to_settle(
        paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Home", email="h@example.com")
    make_claude_json(paths, email="h@example.com")
    (paths.claude_dir).mkdir(parents=True, exist_ok=True)
    (paths.claude_dir / ".credentials.json").write_bytes(
        paths.credentials("claude", "Home").read_bytes())

    group = group_of(paths, "claude")

    assert notice_codes(group) == ["signed_in_elsewhere"]
    assert group.notices[0].account == "Home"
    assert group.can_save is False


def test_a_marker_naming_a_deleted_profile_offers_to_save_the_live_login(
        paths):
    make_profile(paths, "claude", "Work", email="w@example.com")
    make_claude_json(paths, email="gone@example.com")
    make_live_claude_login(paths, access_token="tok-gone")
    paths.active_marker("claude").write_text("Gone\n", encoding="utf-8")

    group = group_of(paths, "claude")

    assert group.state == state.MISSING_PROFILE
    assert group.can_save is True
    assert notice_codes(group) == ["missing_profile", "unsaved_login"]
    assert "'Gone'" in group.notices[0].message


def test_an_unreadable_store_is_said_rather_than_hidden(paths, monkeypatch):
    from shambles.stores import FileStore
    from shambles.stores.base import StoreUnavailableError

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths, access_token="tok-Work")

    def locked(self):
        if self.path.name == ".credentials.json":
            raise StoreUnavailableError("Permission denied")
        return original(self)

    original = FileStore.read
    monkeypatch.setattr(FileStore, "read", locked)

    group = group_of(paths, "claude")

    assert notice_codes(group) == ["store_unreadable"]
    assert ".credentials.json" in group.notices[0].message
    assert "Permission denied" not in group.notices[0].message
    assert group.notices[0].remedy


def test_a_config_dir_override_is_said(paths, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(paths.home / "elsewhere"))
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)

    group = group_of(paths, "claude")

    assert "config_override" in notice_codes(group)
    notice = next(n for n in group.notices if n.code == "config_override")
    assert "CLAUDE_CONFIG_DIR" in notice.message
    assert "elsewhere" in notice.message


def test_notices_reach_the_wire(paths):
    make_claude_json(paths, email="me@example.com")
    make_live_claude_login(paths)

    group = snap.to_dict(build(paths))["groups"][0]

    assert group["can_save"] is True
    assert group["live_email"] == "me@example.com"
    assert set(group["notices"][0]) == {"code", "message", "remedy", "account"}


def test_list_says_an_unsaved_login_is_there_and_how_to_keep_it(paths,
                                                                 capsys):
    """Reproduced on a first run while signed in: 'no accounts yet', and
    nothing about the login that was right there to save."""
    make_claude_json(paths, email="me@example.com")
    make_live_claude_login(paths)

    assert cli.main(["--home", str(paths.home), "list"]) == 0
    out = capsys.readouterr().out

    assert "Signed in as me@example.com, which is not saved yet." in out
    assert "Run 'shambles' and press s to save it." in out


def test_list_names_the_command_that_settles_a_stale_marker(paths, capsys):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Home", email="h@example.com")
    make_claude_json(paths, email="h@example.com")
    paths.claude_dir.mkdir(parents=True, exist_ok=True)
    (paths.claude_dir / ".credentials.json").write_bytes(
        paths.credentials("claude", "Home").read_bytes())

    assert cli.main(["--home", str(paths.home), "list"]) == 0
    out = capsys.readouterr().out

    assert "shambles switch claude Home" in out
    # And the command it names works, rather than being refused with advice
    # to run it.
    assert cli.main(["--home", str(paths.home), "switch", "claude",
                     "Home"]) == 0
    assert state.read_active(paths, "claude") == "Home"


def test_switch_warns_when_this_terminal_reads_another_login(paths, capsys,
                                                             monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(paths.home / "elsewhere"))
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Home", email="h@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths, access_token="tok-Work")

    assert cli.main(["--home", str(paths.home), "switch", "claude",
                     "Home"]) == 0
    out = capsys.readouterr().out

    assert "CLAUDE_CONFIG_DIR is set" in out


def test_an_unknown_provider_names_the_ones_that_exist(paths, capsys):
    """Reproduced: 'shambles switch claud Work' printed only "claud"."""
    assert cli.main(["--home", str(paths.home), "switch", "claud",
                     "Work"]) == 1
    err = capsys.readouterr().err

    assert "Unknown provider 'claud'" in err
    assert "claude, codex" in err


# -- what a window needs beyond the list --------------------------------------


@posix_only
def test_a_group_says_whether_its_vendor_cli_can_sign_in(paths, fake_vendor):
    """A window disables Sign in and Add rather than letting them fail."""
    fake_vendor("claude")

    claude_group = group_of(paths, "claude")
    codex_group = group_of(paths, "codex")

    assert (claude_group.can_sign_in, claude_group.cli) == (True, "claude")
    assert (codex_group.can_sign_in, codex_group.cli) == (False, "codex")


def test_an_account_carries_its_expiry_date_and_the_word_for_its_state(paths):
    """DD-1 keeps the date off the face but available on request."""
    lapsed_at = NOW - DAY_MS
    make_profile(paths, "claude", "Lapsed", email="l@example.test",
                 refresh_expires_ms=lapsed_at)
    make_profile(paths, "claude", "Fine", email="f@example.test",
                 refresh_expires_ms=NOW + 30 * DAY_MS)

    accounts = {a.name: a for a in group_of(paths, "claude").accounts}

    assert accounts["Lapsed"].expires_at_ms == lapsed_at
    assert accounts["Lapsed"].status_label == "needs login"
    assert accounts["Fine"].expires_at_ms == NOW + 30 * DAY_MS
    assert accounts["Fine"].status_label is None


def test_usage_windows_carry_a_severity_and_when_they_reset(paths):
    """The colour rule lives here, not in each frontend."""
    from helpers import account, write_json

    make_profile(paths, "claude", "Busy", email="b@example.test")
    write_json(paths.account("claude", "Busy"), {
        "oauthAccount": account("b@example.test", uuid="uuid-b"),
        "usage": {
            "accountUuid": "uuid-b",
            "fetchedAtMs": NOW,
            "utilization": {"limits": [
                {"kind": "session", "percent": 12, "severity": "normal",
                 "resets_at": "2026-09-01T10:00:00+00:00"},
                {"kind": "weekly_all", "percent": 85, "severity": "normal",
                 "resets_at": None},
            ]},
        },
    })

    session, week = group_of(paths, "claude").accounts[0].usage

    assert (session.severity, week.severity) == ("ok", "gone")
    assert session.resets_at_ms == 1_788_256_800_000
    assert week.resets_at_ms is None


@posix_only
def test_the_window_fields_reach_the_wire(paths, fake_vendor):
    fake_vendor("claude")
    make_profile(paths, "claude", "Work", email="w@example.test",
                 refresh_expires_ms=NOW - DAY_MS)

    wire = snap.to_dict(build(paths))["groups"][0]

    assert wire["can_sign_in"] is True and wire["cli"] == "claude"
    assert wire["accounts"][0]["expires_at_ms"] == NOW - DAY_MS
    assert wire["accounts"][0]["status_label"] == "needs login"


def test_an_account_says_whether_its_provider_publishes_usage_at_all(paths):
    """Blank space reads as a broken widget; a frontend needs to know whether
    there is something to explain."""
    make_profile(paths, "claude", "Work", email="w@example.test")

    work = group_of(paths, "claude").accounts[0]

    assert work.usage == [] and work.publishes_usage is True


def test_an_account_says_whether_using_it_moves_its_expiry_date(paths):
    """Codex replaces its token when used; Claude's date is fixed at sign-in.
    A frontend must not tell a Claude user that using the account keeps it."""
    make_profile(paths, "claude", "Work", email="w@example.test")
    make_profile(paths, "codex", "Home", email="h@example.test")

    claude_account = group_of(paths, "claude").accounts[0]
    codex_account = group_of(paths, "codex").accounts[0]

    assert claude_account.renewed_by_use is False
    assert codex_account.renewed_by_use is True
    wire = snap.to_dict(build(paths))["groups"]
    assert wire[0]["accounts"][0]["renewed_by_use"] is False


# -- a Claude login's fixed deadline ------------------------------------------
#
# Claude ends every login about 30 days after it was signed in, however much
# it is used (measured 2026-11-13, review lane). Reproduced on a synthetic
# home: an account two days from that date read exactly like a healthy one
# in `shambles list` and in the terminal UI, and the window coloured a chip
# whose reason was only in a tooltip. Nothing anywhere offered the one thing
# that keeps it: signing in again.

#: Liveness here is judged on the real clock (the CLI reads it), so these
#: dates are relative to it, as healthy_ms's are.
REAL_NOW = healthy_ms(0)


def closing_home(paths):
    make_profile(paths, "claude", "Work", email="w@example.test", active=True,
                 refresh_expires_ms=healthy_ms(2))
    make_profile(paths, "claude", "Fine", email="f@example.test")
    make_profile(paths, "claude", "Gone", email="g@example.test",
                 refresh_expires_ms=REAL_NOW - DAY_MS)
    make_profile(paths, "codex", "Laptop", email="c@example.test",
                 refresh_expires_ms=healthy_ms(1))
    # Work is live, as the account in daily use is.
    make_claude_json(paths, email="w@example.test")
    paths.claude_dir.mkdir(parents=True, exist_ok=True)
    (paths.claude_dir / ".credentials.json").write_bytes(
        paths.credentials("claude", "Work").read_bytes())


def test_a_claude_login_near_its_deadline_is_due_a_sign_in(paths):
    closing_home(paths)
    groups = {g.provider: g for g in build(paths, now_ms=REAL_NOW).groups}
    claude_ = {a.name: a for a in groups["claude"].accounts}
    codex_ = {a.name: a for a in groups["codex"].accounts}

    assert claude_["Work"].sign_in_due is True
    # Healthy, already lapsed (that is needs_login), and a provider whose
    # date use renews are none of them due.
    assert claude_["Fine"].sign_in_due is False
    assert claude_["Gone"].sign_in_due is False
    assert claude_["Gone"].needs_login is True
    assert codex_["Laptop"].sign_in_due is False


def test_an_account_carries_its_expiry_as_words(paths):
    closing_home(paths)
    work = next(a for a in group_of(paths, "claude", now_ms=REAL_NOW).accounts
                if a.name == "Work")
    assert work.expires_label
    assert work.expires_label != str(work.expires_at_ms)


def test_a_due_sign_in_is_a_notice_that_says_why(paths):
    closing_home(paths)
    notices = [n for n in group_of(paths, "claude", now_ms=REAL_NOW).notices
               if n.code == "sign_in_soon"]

    assert [n.account for n in notices] == ["Work"]
    notice = notices[0]
    assert "'Work'" in notice.message
    # Why, in the user's terms: a fixed date that use does not move.
    assert "30 days" in notice.message
    assert "however much you use it" in notice.message
    assert "Sign in to 'Work' again" in notice.remedy


def test_a_closing_codex_login_gets_no_sign_in_notice(paths):
    closing_home(paths)
    assert not [n for n in group_of(paths, "codex", now_ms=REAL_NOW).notices
                if n.code == "sign_in_soon"]


def test_the_sign_in_fields_reach_the_wire(paths):
    closing_home(paths)
    group = next(g for g in snap.to_dict(build(paths, now_ms=REAL_NOW))["groups"]
                 if g["provider"] == "claude")
    work = next(a for a in group["accounts"] if a["name"] == "Work")
    assert work["sign_in_due"] is True
    assert work["expires_label"]
    assert "sign_in_soon" in [n["code"] for n in group["notices"]]


def test_list_says_which_logins_end_soon_and_how_to_keep_them(paths, capsys):
    closing_home(paths)
    assert cli.main(["--home", str(paths.home), "list"]) == 0
    out = capsys.readouterr().out
    lines = {line.split()[1] if line.startswith("  *") else line.split()[0]:
             line for line in out.splitlines() if line.startswith("  ")
             and not line.startswith("  !") and line.split()}

    assert "expires soon" in lines["Work"]
    assert "expires soon" in lines["Laptop"]
    assert "expires soon" not in lines["Fine"]
    assert "however much you use it" in out
    assert "Run 'shambles', select 'Work' and press l to sign in again." in out


def test_the_soonest_deadline_comes_first(paths):
    """f in the terminal UI acts on the first notice, so the first is the one
    that runs out first, not the first in alphabetical order."""
    closing_home(paths)
    make_profile(paths, "claude", "Alpha", email="a@example.test",
                 refresh_expires_ms=healthy_ms(3))
    notices = [n.account for n in group_of(paths, "claude",
                                           now_ms=REAL_NOW).notices
               if n.code == "sign_in_soon"]
    assert notices == ["Work", "Alpha"]
