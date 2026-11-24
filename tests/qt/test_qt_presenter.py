"""What the window says and offers, decided without a display.

The QML draws what :mod:`shambles.app.qt.presenter` hands it and decides
nothing, so these tests are the window's behaviour: which button a card
gets, when it is disabled and why, and what each sheet says.
"""

from types import SimpleNamespace

from shambles.app.qt import presenter
from shambles.app.service import ActionError, ActionResult
from shambles.app.snapshot import (Account, Group, Notice, Snapshot, Surface,
                                   Window, moment_label)

HOUR = 3_600_000
DAY = 24 * HOUR
#: A fixed "now" for anything about deadlines: 2026-11-18 12:00 UTC.
NOW = 1_795_521_600_000


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
    assert (other["badge"]["text"], other["badge"]["tone"]) == ("Signed out",
                                                                "bad")


def test_a_lapsed_live_account_still_offers_sign_in():
    lapsed = account("Work", active=True, state="closed", needs_login=True,
                     status_label="needs login")

    live = only(view(group(lapsed)))["live"]

    assert live["action"] == "signin"
    assert live["badge"]["text"] == "Signed out"


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

    assert other["badge"]["kind"] == "soon" and other["badge"]["tone"] == "warn"
    assert other["badge"]["action"] == ""
    assert other["action"] == "switch"


# -- number keys and the filter -------------------------------------------------


def test_number_keys_follow_each_accounts_place_and_never_renumber():
    """D8: Ctrl+N is the Nth account down the window, live or not, so the
    numbers do not shift when a switch changes who is live or a row
    lapses. Ctrl+N on the live account does nothing."""
    lapsed = account("Lapsed", state="closed", needs_login=True)
    model = view(group(account("Work", active=True), account("Alpha"), lapsed,
                       account("Beta")),
                 group(account("Home", active=True), account("Team"),
                       provider="codex", title="Codex"))

    numbers = {a["name"]: a["key"] for g in model["groups"]
               for a in [g["live"], *g["others"]]}
    assert numbers == {"Work": "1", "Alpha": "2", "Lapsed": "3", "Beta": "4",
                       "Home": "5", "Team": "6"}
    keys = {k: v["name"] for k, v in model["keys"].items()}
    assert keys == {"2": "Alpha", "3": "Lapsed", "4": "Beta", "6": "Team"}

    after = view(group(account("Work"), account("Alpha", active=True), lapsed,
                       account("Beta")))
    assert {a["name"]: a["key"] for a in [only(after)["live"],
                                          *only(after)["others"]]} == {
        "Work": "1", "Alpha": "2", "Lapsed": "3", "Beta": "4"}


def test_only_nine_accounts_get_a_number():
    model = view(group(*[account(f"A{i}", active=(i == 0))
                         for i in range(11)]))

    assert [a["key"] for a in only(model)["others"]][-2:] == ["", ""]
    assert sorted(model["keys"]) == list("23456789")


def test_the_filter_narrows_by_name_or_address_and_keeps_the_numbers():
    model = view(group(account("Work", active=True),
                       account("Client Acme"),
                       account("Personal", email="me@example.test")),
                 filter_text="  ACME ")

    shown = only(model)
    assert [a["name"] for a in shown["others"]] == ["Client Acme"]
    assert shown["live"] is None
    assert shown["others"][0]["key"] == "2"
    assert model["keys"]["2"]["name"] == "Client Acme"
    assert model["filtering"] and model["matches"] == 1


def test_a_switch_button_names_where_it_goes():
    other = only(view(group(account("Work", active=True),
                            account("Dev"))))["others"][0]

    assert other["actionTip"] == "Switch to Dev"


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
        "3 accounts · 1 signed out"


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


def test_the_save_card_says_who_in_its_title_and_why_on_hover():
    """Not "Signed in as x, which is not saved yet. 'work' is w@..." as a
    title: who, then that it is not saved, then why it matters behind an i.
    Which account is marked says nothing the save field does not."""
    notice = Notice("unsaved_login",
                    "Signed in as newhire@example.test, which is not saved "
                    "yet. 'work' is work@example.test.",
                    "Save it as an account before switching, or switching "
                    "away will replace it with no copy kept.")
    save = only(view(group(account("work", active=True), notices=[notice],
                           can_save=True, state="drifted",
                           live_email="newhire@example.test")))["save"]

    assert save["title"] == "Signed in as newhire@example.test"
    assert save["body"] == "Not saved yet"
    assert save["tip"] == notice.remedy
    assert "'" not in save["title"] + save["body"] + save["tip"]


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


def test_a_missing_cli_is_one_line_in_the_header_beside_accounts_that_switch():
    """D6: no notice box; the header says it, with the rest behind an i."""
    shown = only(view(group(account("Work", active=True), account("Personal"),
                            can_sign_in=False)))

    assert shown["notices"] == []
    assert shown["missing"] is True
    assert "claude command" in shown["missingTip"]
    assert "still works" in shown["missingTip"]
    assert shown["others"][0]["actionEnabled"] is True


def test_an_empty_provider_invites_an_account_or_takes_one_line():
    ready = only(view(group()))
    missing = only(view(group(can_sign_in=False)))

    assert ready["empty"]["kind"] == "add" and ready["missing"] is False
    assert ready["summary"] == "Not signed in"
    assert missing["empty"] is None, "no card for a tool that is not there"
    assert missing["missing"] is True and missing["summary"] == "Not installed"
    assert "fills in by itself" in missing["missingTip"]


def test_where_switching_reaches_is_said_once_behind_the_heading():
    shown = only(view(group(account("Work", active=True))))

    assert shown["surfacesTip"] == ("Switching changes the Claude Code account "
                                    "in the terminal and in VS Code.")


# -- usage and the saved-login line ---------------------------------------------


def test_stale_usage_is_dimmed_only_on_an_account_not_in_use():
    old = Window("session", 40, age_label="5h ago", stale=True, severity="ok")
    shown = only(view(group(account("Work", active=True, usage=[old]),
                            account("Personal", usage=[old]))))

    assert shown["live"]["usage"][0]["tone"] == "ok"
    assert shown["others"][0]["usage"][0]["tone"] == "dim"


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

    assert bar["tone"] == "gone"
    assert (bar["label"], bar["percent"], bar["fill"]) == ("Week", 85, 0.85)
    assert bar["resets"] == "Resets Tue 17 Nov, 15:10"


# -- U1: a limit that has reset, and reset times you can choose by -------------

MINUTE = 60_000
NOW = 1_790_000_000_000


def bars(*windows, live=False, now_ms=NOW):
    shown = only(view(group(account("Work", active=True),
                            account("Dev", active=False, usage=windows))
                      if not live else
                      group(account("Dev", active=True, usage=windows)),
                      now_ms=now_ms))
    return shown["live"] if live else shown["others"][0]


def test_a_limit_past_its_reset_time_reads_reset_not_its_old_figure():
    """The mockup's Dev row: 100% when last read, but the 5-hour window has
    since rolled over, so 100% is no longer true."""
    full = Window("session", 100, resets_at_ms=NOW - 2 * HOUR,
                  fetched_at_ms=NOW - 7 * HOUR, severity="gone", stale=True)

    bar = bars(full)["usage"][0]

    assert bar["state"] == "reset"
    assert bar["text"] == "reset"
    assert bar["fill"] == 0.0
    assert bar["tone"] == "reset"
    assert bar["resets"] == ""
    assert bar["percent"] == 100
    assert bar["tip"] == (f"5-hour limit: 100% when last read at "
                          f"{moment_label(NOW - 7 * HOUR, NOW)}. It reset "
                          f"at {moment_label(NOW - 2 * HOUR, NOW)}.")


def test_a_limit_resets_on_screen_when_its_time_comes_without_a_re_read():
    """The snapshot's own verdict is from when it was built. The window
    redraws with the time it is drawn at."""
    running = Window("session", 60, resets_at_ms=NOW + MINUTE,
                     fetched_at_ms=NOW, reset=False, severity="ok")

    before = bars(running, live=True, now_ms=NOW)["usage"][0]
    after = bars(running, live=True, now_ms=NOW + 2 * MINUTE)["usage"][0]

    assert (before["state"], after["state"]) == ("current", "reset")


def test_a_reset_under_a_day_away_is_a_countdown_with_the_date_on_hover():
    soon = Window("session", 27, resets_at_ms=NOW + HOUR + 52 * MINUTE,
                  resets_label="Wed 18 Nov, 02:00", fetched_at_ms=NOW,
                  severity="ok")

    bar = bars(soon, live=True)["usage"][0]

    assert bar["state"] == "current"
    assert bar["text"] == "27%"
    assert bar["resetsIn"] == "in 1h 52m"
    assert bar["resets"] == "Resets in 1h 52m"
    assert bar["resetsExact"] == "Wed 18 Nov, 02:00"
    assert bar["tip"] == "5-hour limit: 27%. Resets Wed 18 Nov, 02:00."


def test_a_reset_days_away_gives_the_date():
    later = Window("week", 41, resets_at_ms=NOW + 3 * 24 * HOUR,
                   resets_label="Sat 21 Nov, 02:00", fetched_at_ms=NOW,
                   severity="ok")

    bar = bars(later, live=True)["usage"][0]

    assert bar["resetsIn"] == "Sat 21 Nov, 02:00"
    assert bar["resets"] == "Resets Sat 21 Nov, 02:00"
    assert bar["tip"] == "Weekly limit: 41%. Resets Sat 21 Nov, 02:00."


def test_an_old_reading_is_marked_by_the_bar_not_by_a_sentence():
    """No "as of 7h ago" line. The bar's state says old; the age is on
    hover."""
    week = Window("week", 85, resets_at_ms=NOW + 3 * 24 * HOUR,
                  resets_label="Sat 21 Nov, 02:00",
                  fetched_at_ms=NOW - 7 * HOUR, age_label="7h ago",
                  stale=True, severity="gone")

    row = bars(week)
    bar = row["usage"][0]

    assert bar["state"] == "old"
    assert bar["tone"] == "dim"
    assert row["usageNote"] == ""
    assert bar["tip"] == ("Weekly limit: 85%. Resets Sat 21 Nov, 02:00. "
                          "Read 7h ago.")


def test_an_hour_old_reading_turns_old_while_the_window_stays_open():
    read = Window("week", 30, fetched_at_ms=NOW, stale=False, severity="ok")

    fresh = bars(read, now_ms=NOW + 59 * MINUTE)["usage"][0]
    aged = bars(read, now_ms=NOW + 61 * MINUTE)["usage"][0]

    assert (fresh["state"], aged["state"]) == ("current", "old")
    assert aged["tip"] == "Weekly limit: 30%. Read 1h ago."


def test_a_row_sums_its_bars_up_in_words_and_in_one_tooltip():
    full = Window("session", 100, resets_at_ms=NOW - HOUR,
                  fetched_at_ms=NOW - 2 * HOUR, severity="gone", stale=True)
    week = Window("week", 85, fetched_at_ms=NOW - 2 * HOUR, stale=True,
                  severity="gone")

    row = bars(full, week)

    assert row["usageSummary"] == "session reset · 85% week"
    assert row["usageTip"] == " ".join(b["tip"] for b in row["usage"])


def test_the_login_line_gives_the_date_and_what_to_do():
    when = 1_785_000_000_000
    date = presenter.local_time(when)

    assert presenter.login_line(account("A", state="closed",
                                        expires_at_ms=when)) == \
        f"Signed out since {date}. Sign in to use it again."
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
        f"Switch to it by {date} to keep it."
    assert presenter.login_line(account("A", state="closing",
                                        **claude_like)) == \
        (f"Sign in by {date} to keep it. Using the account does not move "
         "this date.")
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


def _claude_sheet(**kwargs):
    base = dict(provider_title="Claude Code", name="Personal",
                email="personal@example.test", previous="Work", adding=False)
    return presenter.login_sheet(**{**base, **kwargs})


def test_the_login_sheet_is_a_labelled_progress_line():
    """D7: four words in a line, the sentences behind them on hover."""
    sheet = _claude_sheet()

    assert sheet["title"] == "Sign in to Personal"
    assert sheet["subtitle"] == "Claude Code · personal@example.test"
    assert [(s["label"], s["state"]) for s in sheet["steps"]] == [
        ("Saved", "done"), ("Ready", "active"), ("Your browser", "todo"),
        ("Save", "todo")]
    assert sheet["steps"][0]["tip"] == "Work is saved and set aside."
    assert sheet["steps"][3]["tip"] == \
        "Then the new login is saved to Personal."
    assert sheet["cancelNote"] == "Cancel puts you back on Work."


def test_who_to_sign_in_as_moves_behind_the_link_s_i():
    sheet = _claude_sheet()
    assert "who" not in sheet
    assert sheet["linkTip"] == (
        "Open it in the browser profile that is signed in as "
        "personal@example.test, or in a private window.")

    added = _claude_sheet(name="Spare", email="", adding=True, previous="")
    assert "private window" in added["linkTip"]
    assert "the account you want to add" in added["linkTip"]


def test_nothing_is_set_aside_when_nobody_was_in_use():
    sheet = _claude_sheet(name="Team", email="", previous="", adding=True)
    assert [s["label"] for s in sheet["steps"]] == ["Ready", "Your browser",
                                                    "Save"]
    assert sheet["cancelNote"] == "Cancel keeps Team, signed out."


def test_the_login_sheet_advances_once_the_vendor_speaks():
    sheet = presenter.login_sheet(provider_title="Codex", name="Team",
                                  email="", previous="", adding=True)

    moved = presenter.login_started(sheet)

    assert [s["state"] for s in sheet["steps"]] == ["active", "todo", "todo"]
    assert [s["state"] for s in moved["steps"]] == ["done", "active", "todo"]
    assert moved["steps"][0]["tip"] == "Codex's sign-in is ready."
    # Once only: a second call changes nothing.
    assert presenter.login_started(moved) == moved


def test_the_link_line_says_what_to_do_in_a_few_words():
    sheet = _claude_sheet()
    assert sheet["url"] == ""
    assert sheet["linkHint"] == "Your browser should open by itself."

    with_link = presenter.login_link(sheet, "https://claude.com/cai/x")

    assert with_link["url"] == "https://claude.com/cai/x"
    assert with_link["linkHint"] == "Browser didn't open? Use this link."
    # The first link stays: a later line cannot swap what was offered.
    assert presenter.login_link(with_link, "https://claude.com/cai/y") \
        == with_link


# -- S1: the code from the browser page --------------------------------------------


def test_a_code_field_appears_only_where_the_sign_in_takes_one():
    sheet = _claude_sheet()
    assert sheet["acceptsCode"] is False

    taking = presenter.login_takes_code(sheet, True)

    assert taking["acceptsCode"] is True
    assert taking["codeTip"].startswith("Only needed when the page shows a code")
    assert taking["codeError"] == "" and taking["codeSent"] is False


def test_a_sent_code_is_marked_and_a_refused_one_says_why_without_it():
    sheet = presenter.login_takes_code(_claude_sheet(), True)
    code = "SECRETcode#STATEvalue"

    refused = presenter.login_code_result(sheet, ActionResult(
        False, "send_code", error=ActionError(
            "code_invalid", "That is only part of the code. Copy all of it "
                            "from the browser page.")))
    assert refused["codeError"].startswith("That is only part of the code")
    assert refused["codeSent"] is False

    sent = presenter.login_code_result(refused,
                                       ActionResult(True, "send_code"))
    assert sent["codeSent"] is True
    assert sent["codeError"] == ""
    for state in (refused, sent):
        assert "SECRET" not in repr(state)


# -- S2: a code for another device ---------------------------------------------------


def _codex_sheet(**kwargs):
    base = dict(provider_title="Codex", name="Spare",
                email="spare@example.test", previous="Main", adding=False,
                offers_device=True)
    return presenter.login_sheet(**{**base, **kwargs})


def test_codex_offers_this_browser_or_another_device():
    sheet = _codex_sheet()
    assert sheet["methods"] == [
        {"id": "browser", "label": "This browser"},
        {"id": "device", "label": "Another device"}]
    assert sheet["method"] == "browser"
    # Claude has one way in, so no choice is drawn.
    assert _claude_sheet()["methods"] == []


def test_the_device_sheet_waits_for_its_code_on_the_other_device():
    sheet = _codex_sheet(method="device")
    assert sheet["method"] == "device"
    assert [s["label"] for s in sheet["steps"]] == [
        "Saved", "Ready", "Other device", "Save"]
    assert sheet["device"] == {"code": "", "url": "", "expiresAtMs": 0}
    assert sheet["deviceHint"] == "Getting a code from Codex."
    # Codex's own warning, kept: a code from someone else is a trap.
    assert "never for a code someone else gave you" in sheet["deviceTip"]


def test_the_code_arrives_with_its_countdown():
    now = 1_800_000_000_000
    sheet = _codex_sheet(method="device")
    offer = SimpleNamespace(user_code="CODE-12345",
                            verification_url="https://auth.openai.com/codex/device",
                            expires_at_ms=now + 15 * 60_000)

    shown = presenter.login_device(sheet, offer, now_ms=now)

    assert shown["device"] == {"code": "CODE-12345",
                               "url": "https://auth.openai.com/codex/device",
                               "expiresAtMs": now + 15 * 60_000}
    assert shown["deviceHint"] == \
        "Open the link on any device and enter this code:"
    assert shown["expiresIn"] == "expires in 15:00"

    later = presenter.login_tick(shown, now_ms=now + 28_000)
    assert later["expiresIn"] == "expires in 14:32"


def test_the_countdown_reads_minutes_and_seconds_then_expired():
    now = 1_000_000
    assert presenter.expiry_label(now + 61_000, now) == "expires in 1:01"
    assert presenter.expiry_label(now + 999, now) == "expires in 0:01"
    assert presenter.expiry_label(now, now) == "expired"
    assert presenter.expiry_label(now - 5_000, now) == "expired"
    assert presenter.expiry_label(0, now) == ""


def test_a_wrong_account_result_is_a_warning_that_can_be_retried():
    result = ActionResult(False, "login", error=ActionError(
        "login_other_account",
        "Your browser signed in as work@example.test, but 'Personal' is "
        "personal@example.test. Nothing was saved over 'Personal'.",
        "Sign out in your browser, then sign in to 'Personal' again."))

    sheet = presenter.result_sheet(result, name="Personal")

    assert sheet["title"] == "That was a different account"
    assert sheet["tone"] == "warn" and sheet["retry"] is True
    assert "Nothing was saved over Personal." in sheet["message"]


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



# -- D7: shorter sheets ---------------------------------------------------------------


def eject_plan(parked=("Admin", "client")):
    return SimpleNamespace(
        warnings=("Shambles will stop managing your accounts. Nothing is "
                  "deleted.", "Afterwards:\nPersonal stays on disk."),
        details={"keeps": [{"provider": "Claude Code", "account": "work",
                            "signedIn": True},
                           {"provider": "Codex", "account": "",
                            "signedIn": False}],
                 "parked": list(parked),
                 "store": "/home/example/.shambles"})


def test_eject_says_who_each_tool_stays_on_and_puts_the_path_on_its_own():
    """D7: 90 words with a path split over three lines, before."""
    sheet = presenter.eject_sheet(eject_plan())

    assert sheet["lines"] == ["Claude Code stays signed in as work.",
                              "Codex will ask you to sign in."]
    assert sheet["path"] == "/home/example/.shambles"
    assert sheet["pathLabel"] == "Saved logins for Admin and client stay in"
    assert "verification email" in sheet["pathTip"]
    said = " ".join([sheet["message"], *sheet["lines"], sheet["pathLabel"]])
    assert len(said.split()) <= 40
    assert "Nothing is deleted" in sheet["message"]


def test_eject_with_nothing_parked_says_the_folder_can_go():
    sheet = presenter.eject_sheet(eject_plan(parked=()))

    assert sheet["pathLabel"] == "You can delete this folder afterwards"
    assert sheet["pathTip"] == ""


def test_the_store_move_notice_is_short_with_its_paths_on_their_own():
    moved = SimpleNamespace(
        ok=True, code="store_moved", message="Your profiles moved...",
        details={"count": 2, "dest": "/home/example/.shambles/claude",
                 "source": "/home/example/.shambles-v1"})

    items = presenter.notice_sheet([moved])["messages"]

    assert [i["path"] for i in items] == ["/home/example/.shambles/claude",
                                          "/home/example/.shambles-v1"]
    assert items[0]["text"] == "2 accounts are now kept by provider, in"
    assert "Codex accounts alongside Claude" in items[0]["tip"]
    assert sum(len(i["text"].split()) for i in items) <= 25


def test_a_notice_without_details_is_said_as_the_service_wrote_it():
    plain = SimpleNamespace(ok=True, code="history_merged",
                            message="Your history was merged.")

    assert presenter.notice_sheet([plain])["messages"] == [
        {"text": "Your history was merged.", "path": "", "tip": ""}]


def test_a_failed_sign_in_does_not_repeat_its_title_or_its_button():
    """D7: "Sign-in did not finish" over "The vendor's sign-in did not
    finish.", and "Sign in to try again" right above Try again."""
    result = ActionResult(False, "login", error=ActionError(
        "login_failed", "The vendor's sign-in did not finish.",
        "You are back on 'work'. Nothing was lost. Sign in to 'client' to "
        "try again."))

    sheet = presenter.result_sheet(result, name="client",
                                   provider_title="Claude Code",
                                   names=["work", "client"])

    assert sheet["title"] == "Sign-in did not finish"
    assert sheet["message"] == ""
    assert sheet["remedy"] == "You are back on work. Nothing was lost."
    assert sheet["retry"] is True


def test_a_message_that_adds_to_the_title_is_kept():
    result = ActionResult(False, "login", error=ActionError(
        "login_not_written", "The vendor did not write a usable login.",
        "'client' still needs a sign-in. Sign in to 'client' to try again."))

    sheet = presenter.result_sheet(result, name="client",
                                   provider_title="Codex",
                                   names=["work", "client"])

    # The tool by name, not "the vendor"; names as the rest of the window
    # writes them, without quotes (D9).
    assert sheet["message"] == "Codex did not save a usable login."
    assert sheet["remedy"] == "client still needs a sign-in."


def test_only_account_names_lose_their_quotes():
    result = ActionResult(False, "login", error=ActionError(
        "login_other_account",
        "Your browser signed in as dev@example.test, but 'O'Brien' is "
        "obrien@example.test. Nothing was saved over 'O'Brien'.",
        "The vendor's page can sign you out first. Then sign in to "
        "'O'Brien' again."))

    sheet = presenter.result_sheet(result, name="O'Brien",
                                   provider_title="Claude Code",
                                   names=["O'Brien", "work"])

    assert sheet["message"] == (
        "Your browser signed in as dev@example.test, but O'Brien is "
        "obrien@example.test. Nothing was saved over O'Brien.")
    assert sheet["remedy"] == ("Claude Code's page can sign you out first. "
                               "Then sign in to O'Brien again.")


def test_a_deadline_tooltip_writes_names_without_quotes():
    shown = only(view(group(due_account("Work", active=True,
                                        expires_at_ms=NOW + DAY),
                            notices=[SOON]), now_ms=NOW))

    assert "'Work'" not in shown["deadline"]["tip"]
    assert shown["deadline"]["tip"].startswith("Work stops working")


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
    assert "saved as Home," in settle["title"], "names without quotes (D9)"
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


def test_the_live_account_due_a_sign_in_offers_one_on_its_badge():
    """It still works, and only a new sign-in keeps it past the date. The
    live card has no button of its own for it; the badge is the button."""
    live = only(view(group(due_account("Work", active=True,
                                       expires_at_ms=NOW + 2 * DAY + HOUR)),
                     now_ms=NOW))["live"]

    assert live["action"] == ""
    assert live["badge"]["action"] == "signin"
    assert live["signIn"] is True


def test_a_parked_account_due_a_sign_in_keeps_one_button_and_a_badge():
    """D2, fixing F3: Switch stays the row's one button, and the sign-in
    moves onto the badge, so nothing pushes the row's menu off the card."""
    other = only(view(group(account("Work", active=True),
                            due_account("Spare",
                                        expires_at_ms=NOW + 2 * DAY + HOUR)),
                      now_ms=NOW))["others"][0]

    assert other["action"] == "switch" and other["actionEnabled"] is True
    assert other["badge"]["kind"] == "due"
    assert (other["badge"]["icon"], other["badge"]["text"]) == ("clock", "2d")
    assert other["badge"]["action"] == "signin"
    assert other["badge"]["tip"].startswith("Sign in by ")
    assert other["signIn"] is True and "signInExtra" not in other


def test_a_due_badge_under_a_day_counts_hours():
    other = only(view(group(account("Work", active=True),
                            due_account("Spare",
                                        expires_at_ms=NOW + 5 * HOUR + 1)),
                      now_ms=NOW))["others"][0]

    assert other["badge"]["text"] == "5h"


def test_a_lapsed_account_still_signs_in_and_never_switches():
    lapsed = account("Old", state="closed", needs_login=True,
                     status_label="needs login")
    other = only(view(group(account("Work", active=True), lapsed)))["others"][0]

    assert other["action"] == "signin"
    assert other["badge"]["kind"] == "signedout"
    assert other["badge"]["action"] == ""
    assert other["signIn"] is True


def test_a_due_sign_in_without_the_cli_is_not_offered_as_working():
    other = only(view(group(account("Work", active=True), due_account("Spare"),
                            can_sign_in=False)))["others"][0]

    assert other["action"] == "switch" and other["actionEnabled"] is True
    assert other["signIn"] is False
    assert other["badge"]["action"] == ""


SOON = Notice("sign_in_soon",
              "'Work' stops working on Tue 17 Nov. Claude ends every "
              "login a fixed time after it was signed in.",
              "Sign in to 'Work' again before then.", account="Work")


def test_a_deadline_in_the_last_three_days_is_one_line_with_sign_in():
    """D4: who and when, a Sign in button, the explanation behind an i."""
    shown = only(view(group(due_account("Work", active=True,
                                        expires_at_ms=NOW + 2 * DAY),
                            notices=[SOON]), now_ms=NOW))

    strip = shown["deadline"]
    assert shown["notices"] == []
    assert strip["account"] == "Work"
    assert strip["text"].startswith("Work stops working ")
    assert len(strip["text"].split()) <= 8
    assert strip["tip"] == (SOON.message + " " + SOON.remedy).replace(
        "'Work'", "Work")
    assert strip["canSignIn"] is True


def test_a_deadline_line_keeps_its_date_apart_from_the_name():
    """At narrow widths the name gives way, never the date."""
    strip = only(view(group(due_account("Work", active=True,
                                        expires_at_ms=NOW + 2 * DAY),
                            notices=[SOON]), now_ms=NOW))["deadline"]
    day = presenter.local_time(NOW + 2 * DAY, presenter.DAY_FORMAT)

    assert strip["when"] == f"stops working {day}"
    assert strip["whenShort"] == f"stops {day}"
    assert strip["text"] == f"Work stops working {day}"


def test_a_deadline_further_off_is_left_to_the_rows_badge():
    shown = only(view(group(due_account("Work", active=True,
                                        expires_at_ms=NOW + 4 * DAY),
                            notices=[SOON]), now_ms=NOW))

    assert shown["deadline"] is None and shown["notices"] == []


def test_a_deadline_hidden_today_stays_hidden():
    shown = only(view(group(due_account("Work", active=True,
                                        expires_at_ms=NOW + DAY),
                            notices=[SOON]),
                      now_ms=NOW, hidden_deadlines={"claude/Work"}))

    assert shown["deadline"] is None


# -- D1: one line of identity, and reasons said once --------------------------------


def test_an_account_named_after_its_address_does_not_say_it_twice():
    model = view(group(account("Me@Example.test", email="me@example.test",
                               active=True),
                       account("Work", email="work@example.test")))

    assert only(model)["live"]["showAddress"] is False
    assert only(model)["others"][0]["showAddress"] is True


def test_a_reason_every_row_shares_is_said_once_for_the_group():
    shown = only(view(group(account("Work", active=True), account("Personal"),
                            account("Spare"), can_save=True,
                            live_email="new@example.test",
                            notices=[Notice("unsaved_login", "Not saved.",
                                            "Save it.")])))

    assert shown["hold"].startswith("Save the signed-in login")
    assert all(not a["actionEnabled"] for a in shown["others"])


# -- D3: the account with the most room -----------------------------------------------


def limits(session, week):
    return [Window("session", session, severity="ok"),
            Window("week", week, severity="ok")]


def test_most_room_is_offered_once_the_live_account_passes_80_percent():
    model = view(group(account("Work", active=True, usage=limits(85, 40)),
                       account("Dev", usage=limits(10, 70)),
                       account("Spare", usage=limits(20, 30)),
                       account("Bare")))

    badges = {a["name"]: a["badge"]["kind"] for a in only(model)["others"]}
    assert badges == {"Dev": "", "Spare": "room", "Bare": ""}


def test_most_room_is_not_offered_while_the_live_account_has_room():
    model = view(group(account("Work", active=True, usage=limits(79, 60)),
                       account("Spare", usage=limits(0, 0))))

    assert only(model)["others"][0]["badge"]["kind"] == ""


def test_most_room_never_goes_to_an_account_that_cannot_be_switched_to():
    lapsed = account("Old", state="closed", needs_login=True,
                     usage=limits(0, 0))
    model = view(group(account("Work", active=True, usage=limits(95, 95)),
                       lapsed, account("Dev", usage=limits(50, 50))))

    badges = {a["name"]: a["badge"]["kind"] for a in only(model)["others"]}
    assert badges == {"Old": "signedout", "Dev": "room"}


def test_most_room_needs_more_room_than_the_live_account_has():
    model = view(group(account("Work", active=True, usage=limits(85, 10)),
                       account("Dev", usage=limits(90, 90))))

    assert only(model)["others"][0]["badge"]["kind"] == ""
