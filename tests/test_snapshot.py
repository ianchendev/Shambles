"""The view model, and the wire contract it serialises to.

Everything the panel displays is decided here rather than in a shell, so these
tests are what stop a Swift or C# client re-deriving a rule and drifting from
it.
"""

import json

import pytest

from shambles import providers
from shambles.app import snapshot as snap
from shambles.app import usage as usage_mod
from shambles.providers import ABSENT, CLOSED, LIVE

NOW = 1_785_000_000_000
DAY_MS = 86_400_000


def make_profile(home, provider_id, name, *, blob=None, active=False):
    directory = home / ".shambles" / provider_id / name
    directory.mkdir(parents=True, exist_ok=True)
    if blob is not None:
        (directory / "credential").write_bytes(blob)
    if active:
        (directory.parent / "active").write_text(name + "\n", encoding="utf-8")
    return directory


def claude_blob(refresh_expires_ms=NOW + 3 * DAY_MS):
    return json.dumps({"claudeAiOauth": {
        "accessToken": "tok", "refreshToken": "ref",
        "refreshTokenExpiresAt": refresh_expires_ms}}).encode()


def claude_identity(home, email="a@example.com", plan="default_claude_max_5x"):
    (home / ".claude.json").write_text(json.dumps({"oauthAccount": {
        "emailAddress": email, "displayName": "Ada",
        "organizationName": "Acme",
        "organizationRateLimitTier": plan}}), encoding="utf-8")


def build(home, **kw):
    return snap.build(home=home, platform="linux", now_ms=NOW, env={}, **kw)


# -- structure ----------------------------------------------------------------


def test_every_provider_gets_a_group_even_with_no_accounts(tmp_path):
    result = build(tmp_path)
    assert [g.provider for g in result.groups] == providers.ids()
    assert all(g.accounts == [] for g in result.groups)


def test_a_group_lists_the_surfaces_one_switch_moves(tmp_path):
    """The panel shows these as pills; without them a user cannot tell that
    switching Codex also changes ChatGPT.app."""
    groups = {g.provider: g for g in build(tmp_path).groups}
    assert [s.id for s in groups["claude"].surfaces] == ["terminal", "vscode"]
    assert [s.id for s in groups["codex"].surfaces] == \
        ["terminal", "vscode", "chatgpt"]
    assert all(s.label for group in groups.values() for s in group.surfaces)


def test_profiles_are_listed_case_insensitively_sorted(tmp_path):
    for name in ("zeta", "Alpha", "middle"):
        make_profile(tmp_path, "claude", name)
    group = next(g for g in build(tmp_path).groups if g.provider == "claude")
    assert [a.name for a in group.accounts] == ["Alpha", "middle", "zeta"]


# -- per-account state --------------------------------------------------------


def test_the_active_profile_is_the_one_the_marker_names(tmp_path):
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    make_profile(tmp_path, "claude", "Personal", blob=claude_blob())
    group = next(g for g in build(tmp_path).groups if g.provider == "claude")
    assert [(a.name, a.active) for a in group.accounts] == \
        [("Personal", False), ("Work", True)]


def test_a_profile_with_no_credential_needs_login(tmp_path):
    make_profile(tmp_path, "claude", "Empty")
    group = next(g for g in build(tmp_path).groups if g.provider == "claude")
    account = group.accounts[0]
    assert account.state == ABSENT
    assert account.needs_login is True
    assert account.login_hint and "login" in account.login_hint.lower()


def test_a_lapsed_profile_needs_login_and_carries_the_command(tmp_path):
    make_profile(tmp_path, "claude", "Old",
                 blob=claude_blob(NOW - DAY_MS))
    account = next(g for g in build(tmp_path).groups
                   if g.provider == "claude").accounts[0]
    assert account.state == CLOSED
    assert account.needs_login is True
    assert account.login_hint


def test_a_healthy_profile_does_not_ask_for_login(tmp_path):
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(NOW + 30 * DAY_MS))
    account = next(g for g in build(tmp_path).groups
                   if g.provider == "claude").accounts[0]
    assert account.state == LIVE
    assert account.needs_login is False
    assert account.login_hint is None


def test_identity_and_plan_come_from_the_provider(tmp_path):
    claude_identity(tmp_path)
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    account = next(g for g in build(tmp_path).groups
                   if g.provider == "claude").accounts[0]
    assert account.email == "a@example.com"
    assert account.plan == "default_claude_max_5x"


def test_a_corrupt_credential_still_lists_the_profile(tmp_path):
    """One bad file must not take down the whole panel."""
    make_profile(tmp_path, "claude", "Broken", blob=b"{ not json")
    account = next(g for g in build(tmp_path).groups
                   if g.provider == "claude").accounts[0]
    assert account.name == "Broken"


# -- quota --------------------------------------------------------------------


def write_claude_usage(path, *, five_hour=21, seven_day=9,
                       five_resets="2099-01-01T00:00:00Z",
                       seven_resets="2099-01-01T00:00:00Z", fetched=NOW):
    existing = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    existing["cachedUsageUtilization"] = {
        "fetchedAtMs": fetched,
        "utilization": {
            "five_hour": {"utilization": five_hour, "resets_at": five_resets},
            "seven_day": {"utilization": seven_day, "resets_at": seven_resets},
        },
    }
    path.write_text(json.dumps(existing), encoding="utf-8")


def test_quota_is_read_for_the_active_account(tmp_path):
    claude_identity(tmp_path)
    write_claude_usage(tmp_path / ".claude.json")
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    account = next(g for g in build(tmp_path).groups
                   if g.provider == "claude").accounts[0]
    assert [(w.label, w.used_percent) for w in account.usage] == \
        [("5h", 21), ("7d", 9)]


def test_a_window_that_has_already_reset_reports_no_figure(tmp_path):
    """Showing a percentage from a window that has since rolled over would
    misinform the decision the user is about to make."""
    claude_identity(tmp_path)
    write_claude_usage(tmp_path / ".claude.json",
                       five_resets="2020-01-01T00:00:00Z")
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    account = next(g for g in build(tmp_path).groups
                   if g.provider == "claude").accounts[0]
    windows = {w.label: w for w in account.usage}
    assert windows["5h"].used_percent is None
    assert windows["7d"].used_percent == 9


def test_no_quota_data_is_a_supported_state_not_an_error(tmp_path):
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    account = next(g for g in build(tmp_path).groups
                   if g.provider == "claude").accounts[0]
    assert account.usage == []


@pytest.mark.parametrize("source", [usage_mod.ClaudeUsageSource(),
                                    usage_mod.CodexUsageSource()])
@pytest.mark.parametrize("damage", [
    b"", b"not json", b"[]", b'{"cachedUsageUtilization": "wrong type"}',
    b'{"cachedUsageUtilization": {"utilization": null}}',
])
def test_a_usage_source_never_raises(source, damage, tmp_path):
    """The single most important property of this layer.

    Both sources read vendor by-products -- a display cache and an internal
    debug log -- that can change or vanish without notice. Every failure has to
    degrade to "no figures shown", never to an exception.
    """
    (tmp_path / ".claude.json").write_bytes(damage)
    profile = tmp_path / "profile"
    profile.mkdir()
    (profile / "account.json").write_bytes(damage)
    assert source.read(home=tmp_path, profile_dir=profile, active=True) is None


def test_codex_has_no_usage_source_for_parked_accounts(tmp_path):
    """The Codex log is global to the install, so it only ever describes
    whoever is signed in now."""
    profile = tmp_path / "profile"
    profile.mkdir()
    assert usage_mod.CodexUsageSource().read(
        home=tmp_path, profile_dir=profile, active=False) is None


# -- the wire contract --------------------------------------------------------


def test_the_contract_carries_a_version(tmp_path):
    """A shell that meets an unknown version must say "update Shambles"
    rather than guess; the app bundle and the CLI ship separately."""
    payload = snap.to_dict(build(tmp_path))
    assert payload["version"] == snap.CONTRACT_VERSION
    assert isinstance(payload["version"], int)


def test_the_contract_is_json_serialisable(tmp_path):
    claude_identity(tmp_path)
    write_claude_usage(tmp_path / ".claude.json")
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    make_profile(tmp_path, "codex", "Personal")
    text = json.dumps(snap.to_dict(build(tmp_path)))
    assert json.loads(text)["version"] == snap.CONTRACT_VERSION


def test_the_contract_exposes_every_field_a_shell_renders(tmp_path):
    """A shell must never compute these itself. If a field is missing here,
    the shell will derive it, and that derivation is untested."""
    claude_identity(tmp_path)
    write_claude_usage(tmp_path / ".claude.json")
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)

    group = snap.to_dict(build(tmp_path))["groups"][0]
    assert set(group) == {"provider", "display_name", "surfaces", "accounts"}
    assert set(group["surfaces"][0]) == {"id", "label", "detail"}
    assert set(group["accounts"][0]) == {
        "name", "email", "display_name", "plan", "active", "state",
        "needs_login", "login_hint", "usage"}
    assert set(group["accounts"][0]["usage"][0]) == {
        "label", "used_percent", "resets_at_ms", "stale"}


def test_a_parked_profile_shows_its_own_email_not_the_active_one(tmp_path):
    """Claude keeps identity outside the credential, so a parked profile has
    to be read from its stashed sidecar. Reading the live ~/.claude.json for
    every row labels them all with whoever is signed in now."""
    claude_identity(tmp_path, email="work@example.com")
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)
    parked = make_profile(tmp_path, "claude", "Personal", blob=claude_blob())
    (parked / "account.json").write_text(json.dumps({
        "oauthAccount": {"emailAddress": "personal@example.com"}}),
        encoding="utf-8")

    by_name = {a.name: a for a in next(
        g for g in build(tmp_path).groups if g.provider == "claude").accounts}
    assert by_name["Work"].email == "work@example.com"
    assert by_name["Personal"].email == "personal@example.com"


# -- command line dispatch ----------------------------------------------------


def test_a_subcommand_after_a_global_flag_still_reaches_the_cli(tmp_path, capsys):
    """Regression: dispatching on argv[0] alone sent `--home X list` to the
    window, which then failed on a machine without Tkinter. Native shells pass
    flags in exactly this order."""
    from shambles.__main__ import main
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)

    assert main(["--home", str(tmp_path), "list", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["version"] == snap.CONTRACT_VERSION


def test_the_json_flag_emits_one_line_for_easy_piping(tmp_path, capsys):
    from shambles.__main__ import main
    main(["--home", str(tmp_path), "list", "--json"])
    assert len(capsys.readouterr().out.strip().splitlines()) == 1


@pytest.mark.parametrize("argv", [
    ["--home", "{home}", "list", "--json"],   # flag before the subcommand
    ["list", "--home", "{home}", "--json"],   # and after
])
def test_home_is_honoured_from_either_position(argv, tmp_path, capsys):
    """A shared argparse argument defined on both the parent and the subparser
    is written twice, and the subparser's default wins. Suppressing the default
    is what keeps both orders working — native shells use the first."""
    from shambles.__main__ import main
    make_profile(tmp_path, "claude", "Work", blob=claude_blob(), active=True)

    assert main([a.format(home=str(tmp_path)) for a in argv]) == 0
    payload = json.loads(capsys.readouterr().out)
    claude = next(g for g in payload["groups"] if g["provider"] == "claude")
    assert [a["name"] for a in claude["accounts"]] == ["Work"]


# -- the warning threshold adapts to the window it is given --------------------


@pytest.mark.parametrize("window_days, days_left, expected", [
    # macOS / Max 5x regime: a ~4 day window warns inside about a day.
    (4, 3, LIVE),
    (4, 1, "closing"),
    # Linux / Team regime: a ~28 day window must not warn at 3 days left, and
    # a fixed 1-day threshold would never warn at all.
    (28, 20, LIVE),
    (28, 5, "closing"),
    (28, 3, "closing"),
])
def test_the_closing_threshold_scales_with_the_measured_window(
        window_days, days_left, expected):
    """The refresh window is not a constant — 3.55 days on macOS/Max 5x against
    28.3 days on Linux/Team. Any fixed threshold is permanently amber under one
    regime and silent under the other, so it is derived from the blob."""
    claude = providers.load("claude", env={})
    access_expires = NOW + 1 * 3_600_000
    blob = json.dumps({"claudeAiOauth": {
        "accessToken": "t",
        "expiresAt": access_expires,
        "refreshTokenExpiresAt": access_expires + window_days * DAY_MS,
    }}).encode()
    # Re-point "now" so the requested amount of the window remains.
    now = access_expires + window_days * DAY_MS - days_left * DAY_MS
    assert claude.liveness(blob, now_ms=now).state == expected
