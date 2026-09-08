"""Reading the usage figures Claude Code caches.

Shapes here are taken from a live ~/.claude.json on client 2.1.222.
"""

from helpers import NOW
from shambles import usage

LIVE = {
    "fetchedAtMs": NOW,
    "accountUuid": "uuid-a",
    "utilization": {
        "five_hour": {"utilization": 22,
                      "resets_at": "2026-08-07T04:00:00.355981+00:00"},
        "seven_day": {"utilization": 87,
                      "resets_at": "2026-08-10T14:00:00.356000+00:00"},
        "limits": [
            {"kind": "session", "group": "session", "percent": 22,
             "severity": "normal",
             "resets_at": "2026-08-07T04:00:00.355981+00:00"},
            {"kind": "weekly_all", "group": "weekly", "percent": 87,
             "severity": "warning",
             "resets_at": "2026-08-10T14:00:00.356000+00:00"},
        ],
    },
}


def test_reads_both_buckets_in_order():
    u = usage.parse(LIVE)
    assert [b.label for b in u.bars] == ["session", "week"]
    assert [b.percent for b in u.bars] == [22, 87]


def test_keeps_claude_codes_raw_severity_and_maps_it_for_display():
    u = usage.parse(LIVE)
    assert u.bars[0].severity == "normal"
    assert u.bars[0].display_severity == "ok"      # 22%, normal
    assert u.bars[1].severity == "warning"
    assert u.bars[1].display_severity == "gone"    # 87% -> past the 80% floor


def test_an_unknown_severity_renders_as_the_worst_case():
    blob = {"utilization": {"limits": [
        {"kind": "session", "percent": 5, "severity": "some_new_thing"}]}}
    assert usage.parse(blob).bars[0].display_severity == "gone"


def test_falls_back_to_the_utilization_buckets_without_limits():
    blob = {"fetchedAtMs": NOW, "utilization": {
        "five_hour": {"utilization": 40},
        "seven_day": {"utilization": 60},
    }}
    u = usage.parse(blob)
    assert [(b.label, b.percent) for b in u.bars] == [("session", 40), ("week", 60)]
    # no severity to trust, so the value alone decides
    assert [b.display_severity for b in u.bars] == ["ok", "ok"]


def test_per_model_buckets_are_ignored():
    """A card has room for two numbers, not six."""
    blob = {"utilization": {"limits": [
        {"kind": "session", "percent": 1, "severity": "normal"},
        {"kind": "weekly_all", "percent": 2, "severity": "normal"},
        {"kind": "weekly_opus", "percent": 99, "severity": "warning"},
        {"kind": "weekly_sonnet", "percent": 98, "severity": "warning"},
    ]}}
    assert [b.label for b in usage.parse(blob).bars] == ["session", "week"]


def test_missing_or_junk_input_is_empty_not_an_error():
    for blob in (None, {}, [], "nope", {"utilization": None},
                 {"utilization": {"limits": "not a list"}}):
        assert not usage.parse(blob), blob


def test_a_partial_bucket_is_skipped_rather_than_shown_as_zero():
    blob = {"utilization": {"limits": [
        {"kind": "session", "percent": None, "severity": "normal"},
        {"kind": "weekly_all", "percent": 87, "severity": "warning"}]}}
    bars = usage.parse(blob).bars
    assert [b.label for b in bars] == ["week"]


# ---- age, which is what makes a stashed figure safe to show --------------

def test_age_label_reads_naturally():
    HOUR = 3_600_000
    cases = [(0, "just now"), (10 * 60_000, "10m ago"),
             (3 * HOUR, "3h ago"), (50 * HOUR, "2d ago")]
    for age, expected in cases:
        u = usage.Usage(bars=(), fetched_at_ms=NOW - age)
        assert u.age_label(NOW) == expected, age


def test_freshly_fetched_is_not_stale():
    u = usage.parse({**LIVE, "fetchedAtMs": NOW - 60_000})
    assert not u.is_stale(NOW)


def test_an_hours_old_figure_is_stale():
    """The reported bug: a switch restored a 7h-old cache and it read as
    current. Anything shown from a stash has to say how old it is."""
    u = usage.parse({**LIVE, "fetchedAtMs": NOW - 7 * 3_600_000})
    assert u.is_stale(NOW)
    assert u.age_label(NOW) == "7h ago"


def test_no_timestamp_means_no_age_claim():
    u = usage.parse({"utilization": LIVE["utilization"]})
    assert u.age_ms(NOW) is None
    assert u.age_label(NOW) is None
    assert not u.is_stale(NOW)


def test_resets_label_is_human_readable():
    u = usage.parse(LIVE)
    assert "Aug" in u.bars[0].resets_label()


def test_a_broken_resets_timestamp_does_not_raise():
    blob = {"utilization": {"limits": [
        {"kind": "session", "percent": 1, "severity": "normal",
         "resets_at": "not a date"}]}}
    assert usage.parse(blob).bars[0].resets_label() is None


def test_a_resets_timestamp_of_the_wrong_type_does_not_raise():
    """The cache is Claude Code's file, so its shape is not ours to trust.

    An epoch number where a string belongs used to escape as a TypeError and
    take down every caller, `shambles list` included.
    """
    blob = {"utilization": {"limits": [
        {"kind": "session", "percent": 1, "severity": "normal",
         "resets_at": 1788000000000}]}}
    assert usage.parse(blob).bars[0].resets_label() is None


# ---- bar colour: an explicit threshold, matching the extension ----------

def test_eighty_percent_and_above_is_red():
    for pct in (80, 87, 99, 100):
        assert usage.bar_severity(pct, "normal") == "gone", pct


def test_below_eighty_is_not_red():
    for pct in (0, 43, 79):
        assert usage.bar_severity(pct, "normal") != "gone", pct


def test_claude_codes_warning_still_shows_below_the_threshold():
    """Our 80% rule is a floor, not a replacement. If Claude Code flags
    something at 60% we surface it rather than painting it normal."""
    assert usage.bar_severity(60, "warning") == "soon"
    assert usage.bar_severity(60, "normal") == "ok"


def test_an_unknown_severity_below_the_threshold_still_escalates():
    assert usage.bar_severity(10, "some_new_thing") == "gone"


def test_the_threshold_is_inclusive_at_exactly_eighty():
    assert usage.bar_severity(79, "normal") == "ok"
    assert usage.bar_severity(80, "normal") == "gone"


def test_fill_fraction_is_clamped():
    assert usage.fill_fraction(0) == 0.0
    assert usage.fill_fraction(50) == 0.5
    assert usage.fill_fraction(100) == 1.0
    assert usage.fill_fraction(140) == 1.0, "over-quota must not overflow the bar"
    assert usage.fill_fraction(-5) == 0.0


# ---- keeping a profile's figures current while it is active -------------

def test_capture_records_the_live_figures_for_the_active_profile(paths):
    """Without this a profile only ever learns its usage at the moment you
    switch away, so the account you are actually using shows nothing."""
    from helpers import account, make_claude_json, make_profile, write_json
    from shambles import configjson

    make_profile(paths, "claude", "Work")
    write_json(paths.account("claude", "Work"),
               {"oauthAccount": account("work@example.com", uuid="uuid-a")})
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": {"fetchedAtMs": NOW, "accountUuid": "uuid-a",
                                   "utilization": {"limits": [
                                       {"kind": "session", "percent": 30,
                                        "severity": "normal"}]}}})

    assert usage.capture_live(paths, "claude", "Work", now_ms=NOW) is True

    stashed = configjson.load(paths.account("claude", "Work"))["usage"]
    assert stashed["utilization"]["limits"][0]["percent"] == 30


def test_capture_refuses_a_blob_belonging_to_another_account(paths):
    """~/.claude.json can still hold the previous account's cache. Stashing it
    against this profile would attribute someone else's usage to it."""
    from helpers import account, make_claude_json, make_profile, write_json
    from shambles import configjson

    make_profile(paths, "claude", "Work")
    write_json(paths.account("claude", "Work"),
               {"oauthAccount": account("work@example.com", uuid="uuid-a")})
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": {"fetchedAtMs": NOW, "accountUuid": "SOMEONE-ELSE",
                                   "utilization": {"limits": []}}})

    assert usage.capture_live(paths, "claude", "Work", now_ms=NOW) is False
    assert "usage" not in configjson.load(paths.account("claude", "Work"))


def test_capture_does_nothing_without_a_live_blob(paths):
    from helpers import account, make_claude_json, make_profile, write_json
    make_profile(paths, "claude", "Work")
    write_json(paths.account("claude", "Work"), {"oauthAccount": account("w@example.com")})
    make_claude_json(paths, email="w@example.com")
    cfg = paths.claude_json.read_text().replace('"cachedUsageUtilization"', '"gone"')
    paths.claude_json.write_text(cfg)
    assert usage.capture_live(paths, "claude", "Work", now_ms=NOW) is False


def test_capture_does_not_rewrite_an_identical_figure(paths):
    """Called on every window refresh, so it must not churn the file."""
    from helpers import account, make_claude_json, make_profile, write_json
    make_profile(paths, "claude", "Work")
    write_json(paths.account("claude", "Work"),
               {"oauthAccount": account("work@example.com", uuid="uuid-a")})
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": {"fetchedAtMs": NOW, "accountUuid": "uuid-a",
                                   "utilization": {"limits": []}}})

    assert usage.capture_live(paths, "claude", "Work", now_ms=NOW) is True
    assert usage.capture_live(paths, "claude", "Work", now_ms=NOW) is False, "rewrote it"


def test_capture_preserves_the_rest_of_the_sidecar(paths):
    from helpers import account, make_claude_json, make_profile, write_json
    from shambles import configjson
    make_profile(paths, "claude", "Work")
    write_json(paths.account("claude", "Work"),
               {"oauthAccount": account("work@example.com", uuid="uuid-a"),
                "stashed_at": 123})
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": {"fetchedAtMs": NOW, "accountUuid": "uuid-a",
                                   "utilization": {"limits": []}}})

    usage.capture_live(paths, "claude", "Work", now_ms=NOW)

    d = configjson.load(paths.account("claude", "Work"))
    assert d["oauthAccount"]["emailAddress"] == "work@example.com"
    assert d["stashed_at"] == 123
