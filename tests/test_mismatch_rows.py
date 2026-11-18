"""Rows while the live login is not the one marked in use (F4, F5).

F4: the live login's usage, plan and login date were filed under whichever
account the marker named, so after a sign-in outside Shambles the marked
row showed numbers that belonged to whoever was really signed in. Live
figures now go to the account the live login provably belongs to -- the
bytes, else the lineage, the rule stashing follows -- and to nobody when no
account can be shown to own it. The marker still decides which row is in
use.

F5: with the marked account deleted (or the marker cleared), a live login
that is already saved as another account was offered for saving under a
new name, "Work 2". When the login is provably that account's, it is now
offered as what it is: "Use Work". A login only the address ties to an
account is not provably saved, and is still offered for saving.
"""

import json

import pytest

from helpers import NOW, account, credentials, make_codex_session, \
    make_profile, write_json
from shambles import providers, state, switcher
from shambles.app import snapshot
from shambles.app.qt import presenter
from shambles.errors import AlreadyManagedError


def usage_cache(percent, uuid):
    return {"accountUuid": uuid,
            "utilization": {"five_hour": {"utilization": percent}}}


def claude_profile(paths, name, *, email, percent=None, plan=None,
                   active=False, deadline=None):
    """A saved Claude account with an account id of its own."""
    make_profile(paths, "claude", name, email=email, active=active,
                 refresh_expires_ms=deadline)
    path = paths.account("claude", name)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["oauthAccount"]["accountUuid"] = f"uuid-{name}"
    if percent is not None:
        data["cachedUsageUtilization"] = usage_cache(percent, f"uuid-{name}")
    if plan is not None:
        data["oauthAccount"]["organizationRateLimitTier"] = plan
    path.write_text(json.dumps(data), encoding="utf-8")


def live_claude(paths, *, blob, email, uuid, plan="live_plan", percent=77):
    """The live login, and ~/.claude.json describing account ``uuid``."""
    write_json(paths.claude_dir / ".credentials.json", blob)
    write_json(paths.claude_json, {
        "oauthAccount": {**account(email, uuid=uuid),
                         "organizationRateLimitTier": plan},
        "cachedUsageUtilization": usage_cache(percent, uuid),
    })


def saved_blob(paths, name):
    return json.loads(paths.credentials("claude", name).read_text())


def group(paths, provider_id="claude"):
    built = snapshot.build(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux", now_ms=NOW)
    return next(g for g in built.groups if g.provider == provider_id)


def rows(paths, provider_id="claude"):
    return {a.name: a for a in group(paths, provider_id).accounts}


def window(paths):
    return presenter.view(snapshot.Snapshot(
        snapshot.CONTRACT_VERSION, [group(paths)]))["groups"][0]


def five_hour(row):
    return [w.used_percent for w in row.usage][:1]


def claude():
    return providers.load("claude", env={})


# -- F4: live figures follow proof, not the marker ---------------------------

def test_a_marked_row_does_not_show_the_live_logins_usage(paths):
    """Signed in as Personal outside Shambles while Work is marked."""
    claude_profile(paths, "Work", email="work@example.test", percent=10,
                   active=True)
    claude_profile(paths, "Personal", email="personal@example.test",
                   percent=20)
    live_claude(paths, blob=saved_blob(paths, "Personal"),
                email="personal@example.test", uuid="uuid-Personal")
    assert state.inspect(paths, claude(),
                         platform="linux").kind == state.DRIFTED

    shown = rows(paths)

    assert five_hour(shown["Work"]) == [10], "Work showed someone else's usage"
    assert five_hour(shown["Personal"]) == [77]
    assert shown["Work"].active, "the marker still decides the row in use"


def test_a_marked_row_keeps_its_own_plan_and_login_date(paths):
    claude_profile(paths, "Work", email="work@example.test",
                   plan="default_claude_max_5x", active=True,
                   deadline=NOW + 20 * 86_400_000)
    claude_profile(paths, "Personal", email="personal@example.test",
                   plan="default_claude_ai", deadline=NOW + 3 * 86_400_000)
    live_claude(paths, blob=saved_blob(paths, "Personal"),
                email="personal@example.test", uuid="uuid-Personal",
                plan="default_claude_ai")

    shown = rows(paths)

    assert shown["Work"].plan == "default_claude_max_5x"
    assert shown["Work"].expires_at_ms == NOW + 20 * 86_400_000
    assert shown["Personal"].expires_at_ms == NOW + 3 * 86_400_000


def test_a_refreshed_login_still_counts_as_proof(paths):
    """The lineage: the live copy was refreshed since Personal was saved, so
    the bytes differ but the sign-in deadline is the same."""
    claude_profile(paths, "Work", email="work@example.test", percent=10,
                   active=True)
    claude_profile(paths, "Personal", email="personal@example.test",
                   percent=20)
    refreshed = saved_blob(paths, "Personal")
    refreshed["claudeAiOauth"]["accessToken"] = "tok-Personal-refreshed"
    live_claude(paths, blob=refreshed, email="personal@example.test",
                uuid="uuid-Personal")

    shown = rows(paths)

    assert five_hour(shown["Work"]) == [10]
    assert five_hour(shown["Personal"]) == [77]


def test_usage_of_a_login_nobody_can_prove_is_shown_under_nobody(paths):
    """A stranger's login, or one only the address ties to an account: the
    figures may well be that account's, but nothing shows they are."""
    claude_profile(paths, "Work", email="work@example.test", percent=10,
                   active=True)
    claude_profile(paths, "Personal", email="personal@example.test",
                   percent=20)
    live_claude(paths, blob=credentials(access_token="tok-new-sign-in"),
                email="personal@example.test", uuid="uuid-Personal")

    shown = rows(paths)

    assert five_hour(shown["Work"]) == [10]
    assert five_hour(shown["Personal"]) == [20]


def test_the_managed_row_still_shows_live_usage(paths):
    claude_profile(paths, "Work", email="work@example.test", percent=10,
                   active=True)
    live_claude(paths, blob=saved_blob(paths, "Work"),
                email="work@example.test", uuid="uuid-Work")

    assert five_hour(rows(paths)["Work"]) == [77]


def test_a_live_usage_cache_for_another_account_is_not_shown(paths):
    """~/.claude.json can hold the previous account's cache just after a
    switch, or a cache written by a session still running as someone else.
    The account id in it says whose it is, as capture_live already checks."""
    claude_profile(paths, "Work", email="work@example.test", percent=10,
                   active=True)
    live_claude(paths, blob=saved_blob(paths, "Work"),
                email="work@example.test", uuid="uuid-Someone-else")

    assert five_hour(rows(paths)["Work"]) == [10]


def test_a_proven_row_shows_its_own_address_not_the_config_files(paths):
    """The config file is rewritten from memory by any session still
    running; only the marked row of a settled login trusts it."""
    claude_profile(paths, "Home", email="home@example.test")
    claude_profile(paths, "Work", email="work@example.test")
    live_claude(paths, blob=saved_blob(paths, "Home"),
                email="work@example.test", uuid="uuid-Work")
    state.write_active(paths, "claude", None)

    shown = rows(paths)

    assert shown["Home"].email == "home@example.test"
    assert shown["Work"].email == "work@example.test"


def test_codex_live_usage_follows_proof_too(paths):
    make_profile(paths, "codex", "Work", email="work@example.test",
                 active=True)
    make_profile(paths, "codex", "Personal", email="personal@example.test")
    live = paths.home / ".codex" / "auth.json"
    live.parent.mkdir(parents=True, exist_ok=True)
    live.write_bytes(paths.credentials("codex", "Personal").read_bytes())
    make_codex_session(paths, used_5h=42.0)

    shown = rows(paths, "codex")

    assert shown["Work"].usage == []
    assert [w.used_percent for w in shown["Personal"].usage][:1] == [42]


@pytest.mark.parametrize("kind", ["managed", "unmanaged"])
def test_a_settled_state_asks_for_no_owner(paths, monkeypatch, kind):
    """Asking reads the live store again: on macOS, the Keychain. Only the
    states where the answer is used pay for it."""
    if kind == "managed":
        claude_profile(paths, "Work", email="work@example.test", active=True)
        live_claude(paths, blob=saved_blob(paths, "Work"),
                    email="work@example.test", uuid="uuid-Work")
    else:
        live_claude(paths, blob=credentials(access_token="tok-first"),
                    email="first@example.test", uuid="uuid-first")
    asked = []
    real = state.owner_of_live
    monkeypatch.setattr(state, "owner_of_live",
                        lambda *a, **k: asked.append(1) or real(*a, **k))

    group(paths)

    assert asked == []


# -- F5: a deleted marked account and a login that is already saved --------

def mark_deleted(paths, name="Old"):
    paths.ensure_provider("claude")
    paths.active_marker("claude").write_text(name + "\n", encoding="utf-8")


def unmark(paths, marker):
    if marker == "deleted":
        mark_deleted(paths)
    else:
        state.write_active(paths, "claude", None)


@pytest.mark.parametrize("marker", ["deleted", "cleared"])
@pytest.mark.parametrize("proof", ["bytes", "lineage"])
def test_a_saved_login_is_offered_as_use_not_as_a_new_save(
        paths, marker, proof):
    claude_profile(paths, "Work", email="work@example.test")
    claude_profile(paths, "Personal", email="personal@example.test")
    blob = saved_blob(paths, "Work")
    if proof == "lineage":
        blob["claudeAiOauth"]["accessToken"] = "tok-Work-refreshed"
    live_claude(paths, blob=blob, email="work@example.test",
                uuid="uuid-Work")
    unmark(paths, marker)

    found = group(paths)
    view = window(paths)

    assert not found.can_save
    assert view["save"] is None, "offered to save Work again as a new name"
    assert view["settle"]["account"] == "Work"
    assert view["settle"]["label"] == "Use Work"
    codes = [n.code for n in found.notices]
    assert "unsaved_login" not in codes
    assert "missing_profile" not in codes


@pytest.mark.parametrize("marker", ["deleted", "cleared"])
@pytest.mark.parametrize("proof", ["bytes", "lineage"])
def test_use_carries_on_with_the_saved_account(paths, marker, proof):
    claude_profile(paths, "Work", email="work@example.test")
    saved = saved_blob(paths, "Work")
    live = dict(saved)
    if proof == "lineage":
        live = json.loads(json.dumps(saved))
        live["claudeAiOauth"]["accessToken"] = "tok-Work-refreshed"
    live_claude(paths, blob=live, email="work@example.test",
                uuid="uuid-Work")
    unmark(paths, marker)

    switcher.switch(paths, claude(), "Work", platform="linux",
                    sleep=lambda _: None)

    assert state.read_active(paths, "claude") == "Work"
    assert saved_blob(paths, "Work") == live
    assert json.loads((paths.claude_dir / ".credentials.json").read_text()) \
        == live


@pytest.mark.parametrize("marker", ["deleted", "cleared"])
def test_a_login_only_the_address_ties_to_an_account_is_offered_for_saving(
        paths, marker):
    """Not provably that account's login: the same address can belong to
    another organisation, and the file is rewritten from memory by any
    session still running. Using it would file it over the saved login."""
    claude_profile(paths, "Work", email="work@example.test")
    live_claude(paths, blob=credentials(access_token="tok-Work-again"),
                email="work@example.test", uuid="uuid-Work")
    unmark(paths, marker)

    found = group(paths)

    assert found.can_save
    assert window(paths)["settle"] is None
    with pytest.raises(AlreadyManagedError):
        switcher.switch(paths, claude(), "Work", platform="linux",
                        sleep=lambda _: None)


@pytest.mark.parametrize("marker", ["deleted", "cleared"])
def test_a_signed_out_machine_is_not_described_as_signed_in(paths, marker):
    """The address in ~/.claude.json outlives a sign-out."""
    claude_profile(paths, "Work", email="work@example.test")
    write_json(paths.claude_json,
               {"oauthAccount": account("work@example.test",
                                        uuid="uuid-Work")})
    unmark(paths, marker)

    found = group(paths)

    assert window(paths)["settle"] is None
    assert not any(n.code == "signed_in_elsewhere" for n in found.notices)
    if marker == "deleted":
        assert any(n.code == "missing_profile" for n in found.notices)


def test_a_login_no_account_matches_is_still_offered_for_saving(paths):
    claude_profile(paths, "Work", email="work@example.test")
    live_claude(paths, blob=credentials(access_token="tok-stranger"),
                email="stranger@example.test", uuid="uuid-stranger")
    mark_deleted(paths)

    found = group(paths)

    assert found.can_save
    assert [n.code for n in found.notices][:1] == ["missing_profile"]


def test_switching_elsewhere_with_no_marker_still_asks_to_save_first(paths):
    claude_profile(paths, "Work", email="work@example.test")
    claude_profile(paths, "Personal", email="personal@example.test")
    live_claude(paths, blob=credentials(access_token="tok-Work-again"),
                email="work@example.test", uuid="uuid-Work")
    mark_deleted(paths)

    with pytest.raises(AlreadyManagedError):
        switcher.switch(paths, claude(), "Personal", platform="linux",
                        sleep=lambda _: None)
