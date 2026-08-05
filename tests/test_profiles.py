import pytest

from helpers import (NOW, DAY_MS, account, make_claude_json, make_profile,
                     write_json)
from shambles import profiles
from shambles.errors import ProfileNameError


# ---- discovery ----------------------------------------------------------

def test_no_profiles_dir_lists_nothing(paths):
    assert profiles.list_profile_names(paths) == []


def test_lists_directories_case_insensitively_sorted(paths):
    for name in ("zeta", "Alpha", "beta"):
        make_profile(paths, name)
    assert profiles.list_profile_names(paths) == ["Alpha", "beta", "zeta"]


def test_skips_dotted_entries_and_files(paths):
    make_profile(paths, "Work")
    paths.backup_dir.mkdir(parents=True)
    (paths.profiles_dir / "stray.txt").write_text("x", encoding="utf-8")
    assert profiles.list_profile_names(paths) == ["Work"]


# ---- email chain --------------------------------------------------------

def test_active_profile_reads_live_claude_json(paths):
    make_profile(paths, "Work", email="stale@example.com")
    make_claude_json(paths, email="live@example.com")
    got = profiles.resolve_account(paths, "Work", active_name="Work")
    assert got["emailAddress"] == "live@example.com"


def test_inactive_profile_reads_its_sidecar(paths):
    make_profile(paths, "Personal", email="personal@example.com")
    make_claude_json(paths, email="live@example.com")
    got = profiles.resolve_account(paths, "Personal", active_name="Work")
    assert got["emailAddress"] == "personal@example.com"




def test_unknown_email_when_nothing_on_disk(paths):
    make_profile(paths, "Bare")
    assert profiles.resolve_account(paths, "Bare", active_name="Work") == {}




# ---- token state --------------------------------------------------------

def test_token_ok(paths):
    d = make_profile(paths, "Work")
    assert profiles.token_state(d, NOW) == profiles.TOKEN_OK


def test_token_missing_when_no_credentials_file(paths):
    d = make_profile(paths, "Fresh", token=False)
    assert profiles.token_state(d, NOW) == profiles.TOKEN_MISSING


def test_token_missing_when_credentials_malformed(paths):
    d = make_profile(paths, "Broken")
    paths.credentials("Broken").write_text("{ not json", encoding="utf-8")
    assert profiles.token_state(d, NOW) == profiles.TOKEN_MISSING


def test_token_expired_when_refresh_window_passed(paths):
    d = make_profile(paths, "Stale", refresh_expires_ms=NOW - DAY_MS)
    assert profiles.token_state(d, NOW) == profiles.TOKEN_EXPIRED


def test_warning_text_matches_spec(paths):
    d = make_profile(paths, "Fresh", token=False)
    p = profiles.discover(paths, active_name=None, now_ms=NOW)[0]
    assert p.path == d
    assert p.warning == (
        "No token found. Switch to this profile and run 'claude' in terminal to login."
    )


def test_healthy_profile_has_no_warning(paths):
    make_profile(paths, "Work", email="w@example.com")
    p = profiles.discover(paths, active_name="Work", now_ms=NOW)[0]
    assert p.warning is None


# ---- refresh-window countdown -------------------------------------------

def test_discover_reports_days_left(paths):
    make_profile(paths, "Work", email="w@example.com",
                 refresh_expires_ms=NOW + 29 * DAY_MS + 3_600_000)
    p = profiles.discover(paths, "Work", NOW)[0]
    assert p.refresh_expires_ms == NOW + 29 * DAY_MS + 3_600_000
    assert p.days_left == 29          # floored, not rounded up


def test_days_left_is_negative_once_lapsed(paths):
    make_profile(paths, "Stale", refresh_expires_ms=NOW - 3 * DAY_MS)
    p = profiles.discover(paths, None, NOW)[0]
    assert p.days_left == -3
    assert p.token_state == profiles.TOKEN_EXPIRED


def test_days_left_is_none_without_credentials(paths):
    make_profile(paths, "Fresh", token=False)
    p = profiles.discover(paths, None, NOW)[0]
    assert p.refresh_expires_ms is None
    assert p.days_left is None


@pytest.mark.parametrize("days,expected", [
    (29, "29d"),
    (8, "8d"),
    (7, "7d"),
    (1, "1d"),
    (0, "today"),
    (-1, "expired 1d ago"),
    (-12, "expired 12d ago"),
])
def test_expiry_label(paths, days, expected):
    make_profile(paths, "P", refresh_expires_ms=NOW + days * DAY_MS)
    p = profiles.discover(paths, None, NOW)[0]
    assert profiles.expiry_label(p) == expected


def test_expiry_label_is_none_without_a_token(paths):
    make_profile(paths, "Fresh", token=False)
    p = profiles.discover(paths, None, NOW)[0]
    assert profiles.expiry_label(p) is None


@pytest.mark.parametrize("days,severity", [
    (29, profiles.EXPIRY_OK),
    (8, profiles.EXPIRY_OK),
    (7, profiles.EXPIRY_SOON),
    (1, profiles.EXPIRY_SOON),
    (0, profiles.EXPIRY_SOON),
    (-1, profiles.EXPIRY_GONE),
])
def test_expiry_severity(paths, days, severity):
    make_profile(paths, "P", refresh_expires_ms=NOW + days * DAY_MS)
    p = profiles.discover(paths, None, NOW)[0]
    assert profiles.expiry_severity(p) == severity


def test_expiry_severity_is_none_without_a_token(paths):
    make_profile(paths, "Fresh", token=False)
    p = profiles.discover(paths, None, NOW)[0]
    assert profiles.expiry_severity(p) is None


# ---- discover -----------------------------------------------------------

def test_discover_marks_the_active_profile(paths):
    make_profile(paths, "Work", email="w@example.com")
    make_profile(paths, "Personal", email="p@example.com")
    make_claude_json(paths, email="w@example.com")

    found = {p.name: p for p in profiles.discover(paths, "Work", NOW)}
    assert found["Work"].active is True
    assert found["Personal"].active is False
    assert found["Personal"].email == "p@example.com"
    assert found["Work"].org == "Acme"


# ---- name validation ----------------------------------------------------

def test_validate_trims_and_returns_clean_name():
    assert profiles.validate_profile_name("  Work  ", []) == "Work"


@pytest.mark.parametrize("bad", ["", "   ", ".", "..", ".hidden",
                                 "a/b", "a\\b", "a:b", "a*b", "a?b",
                                 'a"b', "a<b", "a>b", "a|b"])
def test_validate_rejects(bad):
    with pytest.raises(ProfileNameError):
        profiles.validate_profile_name(bad, [])


def test_validate_rejects_duplicates_case_insensitively():
    with pytest.raises(ProfileNameError):
        profiles.validate_profile_name("work", ["Work"])


def test_validate_rejects_none():
    with pytest.raises(ProfileNameError):
        profiles.validate_profile_name(None, [])
