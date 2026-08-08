import pytest

from helpers import DAY_MS, NOW, make_claude_json, make_profile
from shambles import profiles, providers
from shambles.errors import ProfileNameError
from shambles.providers import ABSENT, CLOSED, CLOSING, LIVE


@pytest.fixture
def claude():
    return providers.load("claude")


@pytest.fixture
def codex():
    return providers.load("codex")


def test_discovery_is_case_insensitively_sorted(paths, claude):
    for name in ("zeta", "Alpha", "beta"):
        make_profile(paths, "claude", name, email=f"{name}@example.com")
    found = profiles.discover(paths, claude, None, NOW, platform="linux")
    assert [p.name for p in found] == ["Alpha", "beta", "zeta"]


def test_a_profile_carries_its_provider(paths, codex):
    make_profile(paths, "codex", "Work", email="c@example.com")
    found = profiles.discover(paths, codex, None, NOW, platform="linux")
    assert found[0].provider == "codex"


def test_the_active_profile_is_flagged(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_claude_json(paths, email="w@example.com")

    found = profiles.discover(paths, claude, "Work", NOW, platform="linux")

    assert [(p.name, p.active) for p in found] == [("Personal", False), ("Work", True)]


def test_a_parked_claude_profile_shows_its_own_email_not_the_live_one(paths, claude):
    """~/.claude.json describes only the account signed in right now. Reading
    it for a parked profile would label every row with the active email."""
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Personal", email="p@example.com")
    make_claude_json(paths, email="w@example.com")

    found = {p.name: p.email for p in
             profiles.discover(paths, claude, "Work", NOW, platform="linux")}

    assert found == {"Work": "w@example.com", "Personal": "p@example.com"}


def test_codex_email_comes_out_of_the_jwt(paths, codex):
    make_profile(paths, "codex", "Work", email="c@example.com")
    found = profiles.discover(paths, codex, None, NOW, platform="linux")
    assert found[0].email == "c@example.com"
    assert found[0].plan == "plus"


HOUR_MS = 3_600_000

#: Offsets from the reference clock rather than whole days, because the two
#: interesting cases are not expressible in days. Claude's warn window is one
#: day (DD-1), so "closing" lives between 0 and 1 days out, and "today" means
#: some hours from now -- an expiry of *exactly* now is closed, not closing.
#: Face labels are state words (DD-1 / quieter UI), not countdown numbers.
@pytest.mark.parametrize("offset_ms, state, label", [
    (30 * DAY_MS, LIVE, None),
    (DAY_MS + HOUR_MS, CLOSING, "soon"),
    (6 * HOUR_MS, CLOSING, "soon"),
    (-3 * DAY_MS, CLOSED, "needs login"),
])
def test_the_face_label_follows_liveness_state(paths, claude, offset_ms, state, label):
    make_profile(paths, "claude", "Work", email="w@example.com",
                 refresh_expires_ms=NOW + offset_ms)
    found = profiles.discover(paths, claude, None, NOW, platform="linux")[0]
    assert found.liveness.state == state
    assert profiles.expiry_label(found) == label


def test_an_expiry_of_exactly_now_is_closed_not_closing(paths, claude):
    """The boundary the parametrized cases step around. A window that closes
    at this instant has closed -- reporting it as 'closing' would tell someone
    they still have time they do not have."""
    make_profile(paths, "claude", "Work", email="w@example.com",
                 refresh_expires_ms=NOW)
    found = profiles.discover(paths, claude, None, NOW, platform="linux")[0]
    assert found.liveness.state == CLOSED


def test_the_same_token_reads_differently_under_each_provider_threshold(paths):
    """DD-1's actual requirement: one shared constant cannot serve both.

    A token 2 days out is comfortable for Claude (1-day window) but already
    closing for Codex (2-day window).
    """
    claude_p, codex_p = providers.load("claude"), providers.load("codex")
    make_profile(paths, "claude", "Work", email="w@example.com",
                 refresh_expires_ms=NOW + 2 * DAY_MS)
    make_profile(paths, "codex", "Work", email="c@example.com",
                 refresh_expires_ms=NOW + 2 * DAY_MS)

    claude_state = profiles.discover(
        paths, claude_p, None, NOW, platform="linux")[0].liveness.state
    codex_state = profiles.discover(
        paths, codex_p, None, NOW, platform="linux")[0].liveness.state

    assert (claude_state, codex_state) == (LIVE, CLOSING)


def test_a_profile_with_no_token_is_absent_not_expired(paths, claude):
    """Added but never logged into. Distinct from a lapsed window, and the
    difference is the whole reason an expired token is never deleted."""
    make_profile(paths, "claude", "Work", token=False)
    found = profiles.discover(paths, claude, None, NOW, platform="linux")[0]
    assert found.liveness.state == ABSENT
    assert profiles.expiry_label(found) == "needs login"
    assert profiles.expiry_severity(found) == profiles.EXPIRY_GONE
    assert profiles.warning(found) is not None


def test_expiry_severity_covers_absent_without_days(paths, claude):
    """The chip still needs a colour when there is no countdown to draw from."""
    make_profile(paths, "claude", "Work", token=False)
    found = profiles.discover(paths, claude, None, NOW, platform="linux")[0]
    assert found.liveness.days_left is None
    assert profiles.expiry_severity(found) == profiles.EXPIRY_GONE


def test_the_warn_threshold_is_per_provider(claude, codex):
    """DD-1: Claude's window is ~4 days against Codex's ~10, so one shared
    constant cannot serve both."""
    assert claude.warn_days != codex.warn_days


def test_a_name_colliding_case_insensitively_is_refused():
    with pytest.raises(ProfileNameError):
        profiles.validate_profile_name("work", ["Work"])


@pytest.mark.parametrize("bad", ["", "  ", ".", "..", ".hidden", "a/b", "a:b"])
def test_unusable_names_are_refused(bad):
    with pytest.raises(ProfileNameError):
        profiles.validate_profile_name(bad, [])
