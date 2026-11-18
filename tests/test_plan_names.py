"""Claude plan names a person recognises, not rate-limit tiers.

Rows read "Default ai" and "Default raven": the plan came from
``oauthAccount.organizationRateLimitTier``, which is a rate-limit tier, not a
plan. Claude Code (2.1.300) stores the organisation type and, for Team, the
seat tier beside it, filled from its bootstrap call, and names plans from
the type itself ("Claude Pro", "Claude Team", ...). The shapes below are the
ones found in real ``~/.claude.json`` files, plan fields only.
"""

import json

import pytest

from helpers import NOW, make_claude_json, make_profile
from shambles import providers
from shambles.app import snapshot
from shambles.app.qt import presenter
from shambles.paths import Paths


PRO = {"organizationType": "claude_pro", "seatTier": None,
       "organizationRateLimitTier": "default_claude_ai",
       "userRateLimitTier": None}
TEAM_STANDARD = {"organizationType": "claude_team",
                 "seatTier": "team_standard",
                 "organizationRateLimitTier": "default_raven",
                 "userRateLimitTier": "default_raven"}
TEAM_PREMIUM = {"organizationType": "claude_team",
                "seatTier": "team_tier_1",
                "organizationRateLimitTier": "default_raven",
                "userRateLimitTier": "default_claude_max_5x"}


def identity_plan(tmp_path, oauth_account):
    provider = providers.load("claude", env={})
    (tmp_path / ".claude.json").write_text(json.dumps({"oauthAccount": {
        "emailAddress": "a@example.test", **oauth_account}}),
        encoding="utf-8")
    return provider.identity(None, home=tmp_path).plan


@pytest.mark.parametrize("oauth_account, plan", [
    (PRO, "Pro"),
    (TEAM_STANDARD, "Team"),
    (TEAM_PREMIUM, "Team Premium"),
    ({"organizationType": "claude_max",
      "organizationRateLimitTier": "default_claude_max_5x"}, "Max 5x"),
    ({"organizationType": "claude_max",
      "organizationRateLimitTier": "default_claude_max_20x"}, "Max 20x"),
    ({"organizationType": "claude_enterprise",
      "organizationRateLimitTier": "default_raven"}, "Enterprise"),
], ids=["pro", "team-standard", "team-premium", "max-5x", "max-20x",
        "enterprise"])
def test_a_claude_plan_is_named_from_the_organisation_type(
        tmp_path, oauth_account, plan):
    assert identity_plan(tmp_path, oauth_account) == plan


def test_a_known_plan_with_an_unknown_variant_keeps_its_plan_name(tmp_path):
    """A Team seat or Max tier this table does not know is still Team or
    Max: the organisation type is certain, only the detail is new."""
    assert identity_plan(tmp_path, {**TEAM_STANDARD,
                                    "seatTier": "team_tier_9"}) == "Team"
    assert identity_plan(tmp_path, {
        "organizationType": "claude_max",
        "organizationRateLimitTier": "default_claude_max_99x"}) == "Max"


@pytest.mark.parametrize("oauth_account", [
    {"organizationType": "claude_something_new",
     "organizationRateLimitTier": "default_raven"},
    {"organizationRateLimitTier": "default_raven"},
    {"organizationType": None, "organizationRateLimitTier": "default_raven"},
], ids=["unknown-type", "no-type", "null-type"])
def test_an_unknown_plan_falls_back_to_todays_text(tmp_path, oauth_account):
    """Nothing goes blank: without a known type the tier is shown, as
    before, and the window still makes it readable."""
    assert identity_plan(tmp_path, oauth_account) == "default_raven"
    assert presenter.plan_label("default_raven") == "Default raven"


def test_no_plan_at_all_is_still_no_plan(tmp_path):
    assert identity_plan(tmp_path, {}) is None


def test_a_parked_account_is_named_from_its_own_stashed_identity(tmp_path):
    paths = Paths.for_home(tmp_path)
    make_profile(paths, "claude", "Personal", email="p@example.test",
                 active=True)
    make_claude_json(paths, email="p@example.test",
                     extra={"oauthAccount": {"emailAddress": "p@example.test",
                                             **PRO}})
    make_profile(paths, "claude", "Admin", email="admin@example.test")
    stashed = paths.account("claude", "Admin")
    data = json.loads(stashed.read_text(encoding="utf-8"))
    data["oauthAccount"].update(TEAM_PREMIUM)
    stashed.write_text(json.dumps(data), encoding="utf-8")

    built = snapshot.build(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux", now_ms=NOW)

    claude = next(g for g in built.groups if g.provider == "claude")
    plans = {a.name: a.plan for a in claude.accounts}
    assert plans == {"Personal": "Pro", "Admin": "Team Premium"}
    assert [presenter.plan_label(plans[n]) for n in ("Personal", "Admin")] \
        == ["Pro", "Team Premium"]
