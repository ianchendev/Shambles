"""What the window says and offers, decided without a display.

The QML draws what :mod:`shambles.app.qt.presenter` hands it and decides
nothing, so these tests are the window's behaviour: which button a card
gets, when it is disabled and why, and what each sheet says.
"""

from types import SimpleNamespace

from shambles.app.qt import presenter
from shambles.app.service import ActionError, ActionResult
from shambles.app.snapshot import (Account, Group, Notice, Snapshot, Surface,
                                   Window)

HOUR = 3_600_000


def account(name, *, active=False, state="live", needs_login=False,
            status_label=None, email=None, plan="max_5x", usage=(),
            expires_at_ms=None, publishes_usage=False, renewed_by_use=False,
            sign_in_due=False):
    return Account(name=name, email=email or f"{name.lower()}@example.test",
                   plan=plan, active=active, state=state,
                   needs_login=needs_login, status_label=status_label,
                   usage=list(usage), expires_at_ms=expires_at_ms,
                   publishes_usage=publishes_usage,
                   renewed_by_use=renewed_by_use, sign_in_due=sign_in_due)


def group(*accounts, provider="claude", title="Claude Code", notices=(),
          can_sign_in=True, can_save=False, live_email=None,
          state="managed"):
    return Group(provider, title, [Surface("t", "Terminal"),
                                   Surface("v", "VS Code")],
                 list(accounts), state=state, live_email=live_email,
                 can_save=can_save, notices=list(notices),
                 can_sign_in=can_sign_in, cli=provider)


def view(*groups, **kw):
    return presenter.view(Snapshot(1, list(groups)), **kw)


def only(view_model):
    return view_model["groups"][0]


# -- which action an account gets ---------------------------------------------


def test_the_live_account_has_no_action_and_cannot_be_removed():
    """The login in use must not be one misclick from deletion."""
    live = only(view(group(account("Work", active=True))))["live"]

    assert live["action"] == ""
    assert live["canRemove"] is False


def test_a_healthy_parked_account_switches_and_can_be_removed():
    other = only(view(group(account("Work", active=True),
                            account("Personal"))))["others"][0]

    assert (other["action"], other["actionEnabled"]) == ("switch", True)
    assert other["canRemove"] is True


def test_a_lapsed_account_signs_in_and_never_switches():
    """Switching to it would install a dead token."""
    lapsed = account("Personal", state="closed", needs_login=True,
                     status_label="needs login")
    other = only(view(group(account("Work", active=True), lapsed)))["others"][0]

    assert (other["action"], other["actionLabel"]) == ("signin", "Sign in")
    assert (other["chip"], other["chipTone"]) == ("Needs sign-in", "bad")


def test_a_lapsed_live_account_still_offers_sign_in():
    lapsed = account("Work", active=True, state="closed", needs_login=True,
                     status_label="needs login")

    live = only(view(group(lapsed)))["live"]

    assert live["action"] == "signin" and live["chip"] == "Needs sign-in"


def test_sign_in_without_the_vendor_cli_is_disabled_with_the_reason():
    """Disabled and explained, not swapped for a Switch that would break."""
    lapsed = account("Personal", state="closed", needs_login=True,
                     status_label="needs login")
    other = only(view(group(account("Work", active=True), lapsed,
                            can_sign_in=False)))["others"][0]

    assert (other["action"], other["actionEnabled"]) == ("signin", False)
    assert "claude is not installed" in other["actionReason"]


def test_an_unreadable_store_blocks_switching_and_says_why():
    notice = Notice("store_unreadable", "Can't read the Claude Code login.",
                    "Unlock it, then refresh.")
    shown = only(view(group(account("Work", active=True), account("Personal"),
                            notices=[notice])))

    assert shown["others"][0]["actionEnabled"] is False
    assert "cannot be read" in shown["others"][0]["actionReason"]
    assert shown["notices"][0]["tone"] == "bad"


def test_nothing_moves_while_an_unsaved_login_is_live():
    """Any switch would replace that login with no copy kept."""
    notice = Notice("unsaved_login", "Signed in as x@example.test, which is "
                    "not saved yet.", "Save it first.")
    lapsed = account("Old", state="closed", needs_login=True)
    shown = only(view(group(account("Work", active=True), account("Personal"),
                            lapsed, notices=[notice], can_save=True,
                            state="drifted", live_email="x@example.test")))

    assert shown["live"] is None, "badged the marked account Live"
    by_name = {a["name"]: a for a in shown["others"]}
    assert set(by_name) == {"Work", "Personal", "Old"}
    assert all(not a["actionEnabled"] for a in by_name.values())
    assert "Save the signed-in login" in by_name["Personal"]["actionReason"]
    assert by_name["Work"]["canRemove"] is False, \
        "the marked account became removable"


def test_an_account_closing_soon_is_nudged_but_still_switches():
    soon = account("Client", state="closing", status_label="soon")
    other = only(view(group(account("Work", active=True), soon)))["others"][0]

    assert (other["chip"], other["chipTone"]) == ("Expires soon", "warn")
    assert other["action"] == "switch"


# -- number keys and the filter -------------------------------------------------


def test_number_keys_go_to_switchable_accounts_in_order_across_providers():
    lapsed = account("Lapsed", state="closed", needs_login=True)
    model = view(group(account("Work", active=True), account("Alpha"), lapsed,
                       account("Beta")),
                 group(account("Home", active=True), account("Team"),
                       provider="codex", title="Codex"))

    keys = {k: v["name"] for k, v in model["keys"].items()}
    assert keys == {"1": "Alpha", "2": "Beta", "3": "Team"}
    by_name = {a["name"]: a["key"] for g in model["groups"]
               for a in g["others"]}
    assert by_name["Lapsed"] == ""


def test_the_filter_narrows_by_name_or_address_and_renumbers():
    model = view(group(account("Work", active=True),
                       account("Client Acme"),
                       account("Personal", email="me@example.test")),
                 filter_text="  ACME ")

    shown = only(model)
    assert [a["name"] for a in shown["others"]] == ["Client Acme"]
    assert shown["live"] is None
    assert model["keys"]["1"]["name"] == "Client Acme"
    assert model["filtering"] and model["matches"] == 1


def test_the_filter_box_only_appears_once_there_are_enough_accounts():
    few = view(group(*[account(f"A{i}") for i in range(6)]))
    many = view(group(*[account(f"A{i}") for i in range(7)]))

    assert (few["showFilter"], many["showFilter"]) == (False, True)


# -- headings, notices and empty states -----------------------------------------


def test_the_group_summary_counts_accounts_and_those_needing_sign_in():
    lapsed = account("B", state="closed", needs_login=True)

    assert only(view(group(account("A", active=True))))["summary"] == \
        "1 account"
    assert only(view(group(account("A", active=True), lapsed,
                           account("C"))))["summary"] == \
        "3 accounts · 1 needs sign-in"


def test_an_unsaved_login_becomes_a_save_card_with_a_name_suggested():
    notice = Notice("unsaved_login",
                    "Signed in as new.hire@example.test, which is not saved "
                    "yet.", "Save it as an account before switching.")
    shown = only(view(group(account("New Hire"), notices=[notice],
                            can_save=True,
                            live_email="new.hire@example.test")))

    assert shown["save"]["email"] == "new.hire@example.test"
    assert shown["save"]["suggested"] == "New Hire 2", \
        "suggested a name that is already taken"
    assert shown["notices"] == [], "the save card replaces the banner"


def test_a_missing_profile_notice_offers_to_forget_the_marker():
    notice = Notice("missing_profile", "'Gone' is marked active but is no "
                    "longer on disk.", "Save the current login.",
                    account="Gone")

    shown = only(view(group(account("Work"), notices=[notice])))["notices"][0]

    assert (shown["action"], shown["tone"]) == ("forget", "warn")


def test_a_config_override_starts_collapsed():
    notice = Notice("config_override", "CLAUDE_CONFIG_DIR is set to /x.",
                    "Unset it.")

    shown = only(view(group(account("Work", active=True),
                            notices=[notice])))["notices"][0]

    assert shown["collapsed"] is True and shown["tone"] == "info"


def test_a_missing_cli_is_said_beside_accounts_that_still_switch():
    shown = only(view(group(account("Work", active=True), account("Personal"),
                            can_sign_in=False)))

    assert [n["code"] for n in shown["notices"]] == ["cli_missing"]
    assert shown["others"][0]["actionEnabled"] is True


def test_an_empty_provider_invites_an_account_or_says_the_cli_is_missing():
    ready = only(view(group()))
    missing = only(view(group(can_sign_in=False)))

    assert ready["empty"]["kind"] == "add"
    assert ready["summary"] == "Not signed in"
    assert missing["empty"]["kind"] == "cli"
    assert missing["summary"] == "Not installed"


# -- usage and the saved-login line ---------------------------------------------


def test_stale_usage_is_dimmed_only_on_an_account_not_in_use():
    old = Window("session", 40, age_label="5h ago", stale=True, severity="ok")
    shown = only(view(group(account("Work", active=True, usage=[old]),
                            account("Personal", usage=[old]))))

    assert shown["live"]["usage"][0]["tone"] == "ok"
    assert shown["others"][0]["usage"][0]["tone"] == "dim"
    assert shown["others"][0]["usageNote"] == "as of 5h ago"


def test_missing_usage_is_explained_only_where_there_could_be_some():
    shown = only(view(group(
        account("Work", active=True, publishes_usage=True),
        account("Personal", publishes_usage=True),
        account("Silent"))))
    hints = {a["name"]: a["usageHint"]
             for a in [shown["live"], *shown["others"]]}

    assert hints == {"Work": "Usage appears once you run it",
                     "Personal": "No usage recorded yet", "Silent": ""}


def test_usage_carries_the_services_severity_and_reset_time():
    hot = Window("week", 85, resets_label="Tue 17 Nov, 15:10",
                 severity="gone")

    bar = only(view(group(account("Work", active=True,
                                  usage=[hot]))))["live"]["usage"][0]

    assert bar == {"label": "Week", "percent": 85, "fill": 0.85,
                   "tone": "gone", "resets": "Resets Tue 17 Nov, 15:10"}


def test_the_login_line_gives_the_date_and_what_to_do():
    when = 1_785_000_000_000
    date = presenter.local_time(when)

    assert presenter.login_line(account("A", state="closed",
                                        expires_at_ms=when)) == \
        f"Expired {date}. Sign in again to renew it."
    assert presenter.login_line(account("A", state="absent")) == \
        "No login saved yet. Sign in to fill it."


def test_only_an_account_renewed_by_use_is_told_that_using_it_keeps_it():
    """Claude's deadline is fixed at sign-in, about thirty days out, and no
    amount of use moves it. Codex replaces its token when used. Telling a
    Claude user otherwise is how a login lapses that they thought was safe."""
    when = 1_785_000_000_000
    date = presenter.local_time(when)
    claude_like = dict(expires_at_ms=when, renewed_by_use=False)
    codex_like = dict(expires_at_ms=when, renewed_by_use=True)

    assert presenter.login_line(account("A", **codex_like)) == \
        f"Healthy. Good until {date}. Using the account renews it."
    assert presenter.login_line(account("A", **claude_like)) == \
        (f"Healthy. Good until {date}. Using the account does not move this "
         "date. Sign in again before then to keep it.")
    assert presenter.login_line(account("A", state="closing",
                                        **codex_like)) == \
        f"Expires {date}. Switch to it before then to keep it."
    assert presenter.login_line(account("A", state="closing",
                                        **claude_like)) == \
        (f"Expires {date}. Using the account does not move this date. Sign "
         "in again before then to keep it.")
    for state in ("live", "closing"):
        line = presenter.login_line(account("A", state=state, **claude_like))
        assert "renews" not in line and "Switch to it" not in line


def test_a_date_out_of_range_does_not_stop_the_window():
    """A vendor emitting microseconds must not take the list down."""
    assert presenter.local_time(10 ** 20) == ""
    assert presenter.login_line(account("A", expires_at_ms=10 ** 20)) == \
        "Healthy."


def test_plans_read_as_words():
    assert presenter.plan_label("max_5x") == "Max 5x"
    assert presenter.plan_label("claude_pro") == "Pro"
    assert presenter.plan_label(None) == ""


# -- sheets -----------------------------------------------------------------------


def test_the_login_sheet_names_who_to_sign_in_as_and_where_cancel_goes():
    sheet = presenter.login_sheet(provider_title="Claude Code",
                                  name="Personal",
                                  email="personal@example.test",
                                  previous="Work", adding=False)

    assert sheet["title"] == "Sign in to Personal"
    assert "personal@example.test" in sheet["who"]
    assert sheet["steps"][0] == {"text": "Work is saved and set aside",
                                 "state": "done"}
    assert sheet["cancelNote"] == \
        "Cancel puts you back on Work. Nothing is lost."


def test_the_login_sheet_advances_once_the_vendor_speaks():
    sheet = presenter.login_sheet(provider_title="Codex", name="Team",
                                  email="", previous="", adding=True)

    moved = presenter.login_started(sheet)

    assert [s["state"] for s in sheet["steps"]] == ["active", "todo", "todo"]
    assert [s["state"] for s in moved["steps"]] == ["done", "active", "todo"]
    assert moved["steps"][0]["text"] == "Codex's sign-in is ready"


def test_a_wrong_account_result_is_a_warning_that_can_be_retried():
    result = ActionResult(False, "login", error=ActionError(
        "login_other_account",
        "Your browser signed in as work@example.test, but 'Personal' is "
        "personal@example.test. Nothing was saved over 'Personal'.",
        "Sign out in your browser, then sign in to 'Personal' again."))

    sheet = presenter.result_sheet(result, name="Personal")

    assert sheet["title"] == "That was a different account"
    assert sheet["tone"] == "warn" and sheet["retry"] is True
    assert "Nothing was saved over 'Personal'" in sheet["message"]


def test_removing_says_what_it_costs_and_names_the_address():
    model = view(group(account("Work", active=True), account("Personal")))
    target = presenter.find_account(model, "claude", "Personal")

    sheet = presenter.remove_sheet(target)

    assert "personal@example.test" in sheet["message"]
    assert "new verification email" in sheet["message"]


def test_the_add_form_shows_an_uninstalled_provider_disabled():
    model = view(group(account("Work", active=True)),
                 group(provider="codex", title="Codex", can_sign_in=False))

    sheet = presenter.add_sheet(model, provider="codex")

    assert [(o["id"], o["enabled"]) for o in sheet["options"]] == \
        [("claude", True), ("codex", False)]
    assert sheet["provider"] == "claude", \
        "opened on a provider that cannot be used"


def test_migration_notices_say_whether_they_worked():
    done = SimpleNamespace(ok=True, message="Your profiles moved.")
    failed = SimpleNamespace(ok=False, message="The old store is unreadable.")

    assert presenter.notice_sheet([done])["tone"] == "ok"
    assert presenter.notice_sheet([done, failed])["tone"] == "bad"


# -- the boundary -------------------------------------------------------------------


def test_the_window_reaches_credentials_only_through_the_service():
    """Nothing under ``shambles/app/qt`` may import a module that moves a
    credential, spawns the vendor, or reads the store directly.

    Every one of those has to go through ``ShamblesService``. The Tk window
    never did, which is why its safety rules had to be re-proved one dialog
    at a time; a single stray ``from ... import switcher`` here is how the
    new window would start down the same road.
    """
    import ast
    from pathlib import Path

    forbidden = {"switcher", "login", "state", "profiles", "eject", "migrate",
                 "usage", "configjson", "stores", "providers", "settings"}
    package = Path(presenter.__file__).resolve().parent
    offenders = []
    for path in sorted(package.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom):
                names = {alias.name for alias in node.names}
                module = (node.module or "").split(".")
                if node.level >= 2 or "shambles" in module:
                    hit = forbidden & (names | set(module))
                    if hit:
                        offenders.append(f"{path.name}: {sorted(hit)}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    parts = set(alias.name.split("."))
                    if "shambles" in parts and forbidden & parts:
                        offenders.append(f"{path.name}: {alias.name}")

    assert offenders == []


def test_eject_says_what_the_service_plan_says_and_only_once():
    """The service owns what eject does. The window adding its own lead in
    front of the plan's said "Nothing is deleted" twice."""
    plan = SimpleNamespace(warnings=(
        "Shambles will stop managing your accounts. Nothing is deleted.",
        "Afterwards:\nPersonal stays on disk."))

    sheet = presenter.eject_sheet(plan)

    assert sheet["message"].count("Nothing is deleted") == 1
    assert sheet["message"].startswith("Shambles will stop managing")
    assert "Personal stays on disk." in sheet["message"]
    assert presenter.eject_sheet(SimpleNamespace(warnings=()))["message"] == \
        presenter.EJECT_FALLBACK



# -- a saved account signed in under the wrong marker ------------------------------


def elsewhere(owner="Home"):
    return Notice("signed_in_elsewhere",
                  f"Signed in as h@example.test, which is saved as '{owner}', "
                  "but 'Work' is marked active.",
                  f"Switch to '{owner}' to settle it. Nothing is lost either "
                  "way.", account=owner)


def drifted(*accounts, owner="Home"):
    return only(view(group(*accounts, notices=[elsewhere(owner)],
                           state="drifted", live_email="h@example.test")))


def test_a_login_saved_elsewhere_is_settled_by_switching_not_by_saving():
    """The address names a saved account. Saving would make a second account
    for one login; switching to the one named is how the user confirms it."""
    shown = drifted(account("Work", active=True), account("Home"),
                    account("Third"))

    assert shown["save"] is None
    settle = shown["settle"]
    assert settle["account"] == "Home"
    assert settle["label"] == "Switch to Home"
    assert "saved as 'Home'" in settle["title"]
    assert "Nothing is lost" in settle["body"]
    assert shown["notices"] == [], "drawn as the settle card, not a banner"


def test_every_other_switch_waits_until_it_is_settled():
    """The core refuses to switch anywhere but the named account from here,
    because the live login would be filed under the wrong name. The window
    says so before the click instead of after it."""
    shown = drifted(account("Work", active=True), account("Home"),
                    account("Third"))
    others = {a["name"]: a for a in shown["others"]}

    assert shown["live"] is None
    assert others["Home"]["actionEnabled"] is True
    for name in ("Work", "Third"):
        assert others[name]["actionEnabled"] is False
        assert "Switch to Home" in others[name]["actionReason"]


def test_settling_works_even_when_the_named_accounts_own_login_has_lapsed():
    """Its saved login may be dead while the live one is fresh; switching to
    it files the fresh one there. The card's button does that, whatever the
    row's own button says."""
    lapsed_home = account("Home", state="closed", needs_login=True,
                          status_label="needs login")

    shown = drifted(account("Work", active=True), lapsed_home)

    assert shown["settle"]["account"] == "Home"



# -- R11: a sign-in that is due before the date ---------------------------------------


def due_account(name, **kw):
    return account(name, state="closing", status_label="soon",
                   sign_in_due=True, **kw)


def test_the_live_account_due_a_sign_in_offers_one():
    """It still works, and only a new sign-in keeps it past the date."""
    live = only(view(group(due_account("Work", active=True))))["live"]

    assert (live["action"], live["actionLabel"]) == ("signin", "Sign in")
    assert live["actionEnabled"] is True
    assert live["signIn"] is True


def test_a_parked_account_due_a_sign_in_offers_it_beside_switch():
    """As the Tk window does: it still works, so Switch stays, and Sign in
    is offered next to it before the date rather than after."""
    other = only(view(group(account("Work", active=True),
                            due_account("Spare"))))["others"][0]

    assert other["action"] == "switch" and other["actionEnabled"] is True
    assert other["signIn"] is True and other["signInExtra"] is True


def test_a_lapsed_account_still_signs_in_and_never_switches():
    lapsed = account("Old", state="closed", needs_login=True,
                     status_label="needs login")
    other = only(view(group(account("Work", active=True), lapsed)))["others"][0]

    assert other["action"] == "signin"
    assert other["signIn"] is True and other["signInExtra"] is False


def test_a_due_sign_in_without_the_cli_is_not_offered_as_working():
    other = only(view(group(account("Work", active=True), due_account("Spare"),
                            can_sign_in=False)))["others"][0]

    assert other["action"] == "switch" and other["actionEnabled"] is True
    assert other["signIn"] is False


def test_the_sign_in_soon_notice_has_a_sign_in_button():
    notice = Notice("sign_in_soon",
                    "'Work' stops working on Tue 17 Nov. Claude ends every "
                    "login a fixed time after it was signed in.",
                    "Sign in to 'Work' again before then.", account="Work")

    shown = only(view(group(due_account("Work", active=True),
                            notices=[notice])))["notices"][0]

    assert shown["action"] == "signin"
    assert shown["actionLabel"] == "Sign in to Work"
    assert shown["account"] == "Work"
    assert shown["tone"] == "warn"
