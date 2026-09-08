import inspect
import json
import pathlib
import subprocess
import sys

import pytest

from shambles import settings, update_check
from shambles.update_check import check_for_update

DAY = 86_400


def answering(tag, calls=None):
    """A stand-in fetch that records the URL it was asked for.

    Every test here passes its own fetch. The real one is never called: a
    suite that reached GitHub would be the very thing this feature is supposed
    to keep optional.
    """
    def fetch(url):
        if calls is not None:
            calls.append(url)
        return {"tag_name": tag}
    return fetch


def test_a_default_install_never_reaches_the_network(paths):
    """The whole privacy argument in one assertion: with the setting unset,
    ``fetch`` is not called at all -- not called and discarded, not called."""
    calls = []
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=answering("v9.0.0", calls))
    assert calls == []
    assert status.enabled is False
    assert status.newer is False
    assert status.latest is None
    assert status.message is None


def test_an_enabled_check_says_what_is_new_and_how_to_get_it(paths):
    settings.set_update_check(paths, True)
    calls = []
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=answering("v2.1.0", calls))
    assert calls == [
        "https://api.github.com/repos/ianchendev/Shambles/releases/latest"]
    assert status.enabled is True
    assert status.latest == "2.1.0"
    assert status.newer is True
    assert status.message == (
        "Shambles 2.1.0 is available (you have 2.0.0). Update with: "
        "npm i -g shambles@latest — or re-run the install script.")


def test_the_notice_never_offers_to_do_the_update_itself(paths):
    """Shambles tells; it does not fetch, unpack or replace anything. The copy
    is the whole of the feature, so it is pinned here too."""
    settings.set_update_check(paths, True)
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=answering("v2.1.0"))
    assert "npm i -g shambles@latest" in status.message
    assert "re-run the install script" in status.message


@pytest.mark.parametrize("tag", ["v2.0.0", "2.0.0", "v1.9.9", "v1.0"])
def test_the_current_version_or_older_is_not_an_update(paths, tag):
    settings.set_update_check(paths, True)
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=answering(tag))
    assert status.enabled is True
    assert status.newer is False
    assert status.message is None


@pytest.mark.parametrize("latest,current,newer", [
    ("v2.1", "2.1.0", False),      # 2.1 and 2.1.0 are the same release
    ("v2.1.0", "2.1", False),
    ("v2.2", "2.1.9", True),
    ("v2.10.0", "2.9.0", True),    # ten is not "less than" nine here
    ("v2.0.1", "2.0.0.1", True),
])
def test_release_numbers_compare_by_segment_not_by_text(
        paths, latest, current, newer):
    """Padded to a common length before comparing, so a shorter number is not
    automatically the smaller one, and ``10`` sorts above ``9``."""
    settings.set_update_check(paths, True)
    status = check_for_update(paths, current_version=current, now_s=1_000,
                              fetch=answering(latest))
    assert status.newer is newer


@pytest.mark.parametrize("tag", [
    "v2.1.0-rc1",   # a prerelease is not something to push a stable user at
    "nightly",
    "v",
    "",
    "2.1.0b",
    "release-2.1.0",
])
def test_a_tag_that_is_not_a_release_number_stays_quiet(paths, tag):
    """An unorderable tag is a "say nothing", never a crash and never a false
    "there is an update"."""
    settings.set_update_check(paths, True)
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=answering(tag))
    assert status.newer is False
    assert status.message is None


@pytest.mark.parametrize("payload", [
    {}, {"name": "2.1.0"}, {"tag_name": None}, {"tag_name": 21}, [], "v2.1.0",
    None,
])
def test_a_payload_that_is_not_a_release_is_silent(paths, payload):
    """GitHub answers rate limits and outages with JSON too."""
    settings.set_update_check(paths, True)
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=lambda _url: payload)
    assert status.newer is False
    assert status.message is None


def test_only_one_lookup_a_day(paths):
    settings.set_update_check(paths, True)
    check_for_update(paths, current_version="2.0.0", now_s=1_000,
                     fetch=answering("v2.1.0"))
    calls = []
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000 + 60,
                              fetch=answering("v9.0.0", calls))
    assert calls == []
    # Still reported, from the cache -- quiet does not mean forgotten.
    assert status.latest == "2.1.0"
    assert status.newer is True


def test_the_lookup_happens_again_once_the_day_is_up(paths):
    settings.set_update_check(paths, True)
    check_for_update(paths, current_version="2.0.0", now_s=1_000,
                     fetch=answering("v2.1.0"))
    calls = []
    status = check_for_update(paths, current_version="2.0.0",
                              now_s=1_000 + DAY + 1,
                              fetch=answering("v2.2.0", calls))
    assert len(calls) == 1
    assert status.latest == "2.2.0"


def test_a_clock_that_went_backwards_does_not_wedge_the_check(paths):
    """A cache stamped in the future would otherwise stay fresh forever."""
    settings.set_update_check(paths, True)
    check_for_update(paths, current_version="2.0.0", now_s=10 * DAY,
                     fetch=answering("v2.1.0"))
    calls = []
    check_for_update(paths, current_version="2.0.0", now_s=1_000,
                     fetch=answering("v2.2.0", calls))
    assert len(calls) == 1


def test_a_failed_lookup_is_silent(paths):
    settings.set_update_check(paths, True)

    def boom(_url):
        raise OSError("offline")

    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=boom)
    assert status.enabled is True
    assert status.newer is False
    assert status.latest is None
    assert status.message is None


def test_a_failed_lookup_still_spends_the_day_s_attempt(paths):
    """Otherwise every invocation on an offline machine sits waiting on a
    connection that is not coming."""
    settings.set_update_check(paths, True)

    def boom(_url):
        raise OSError("offline")

    check_for_update(paths, current_version="2.0.0", now_s=1_000, fetch=boom)
    calls = []
    check_for_update(paths, current_version="2.0.0", now_s=1_000 + 60,
                     fetch=answering("v2.1.0", calls))
    assert calls == []


def test_a_tag_already_seen_survives_a_failed_lookup(paths):
    """The notice does not blink out because the network went away."""
    settings.set_update_check(paths, True)
    check_for_update(paths, current_version="2.0.0", now_s=1_000,
                     fetch=answering("v2.1.0"))

    def boom(_url):
        raise OSError("offline")

    status = check_for_update(paths, current_version="2.0.0",
                              now_s=1_000 + DAY + 1, fetch=boom)
    assert status.latest == "2.1.0"
    assert status.newer is True


def test_an_unreadable_cache_is_looked_up_again_not_fatal(paths):
    settings.set_update_check(paths, True)
    paths.ensure_store()
    (paths.library_dir / "update-cache.json").write_text(
        "{{{", encoding="utf-8")
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=answering("v2.1.0"))
    assert status.newer is True


def test_the_cache_holds_a_tag_and_a_timestamp_and_nothing_else(paths):
    """It lives among the credentials, so it is worth asserting that it never
    grows an email, a profile name or a token."""
    settings.set_update_check(paths, True)
    check_for_update(paths, current_version="2.0.0", now_s=1_000,
                     fetch=answering("v2.1.0"))
    cached = json.loads(
        (paths.library_dir / "update-cache.json").read_text(encoding="utf-8"))
    assert cached == {"checked_at": 1_000, "latest": "2.1.0"}


def test_turning_the_check_back_off_silences_it_again(paths):
    """A cached tag is not a licence to keep talking."""
    settings.set_update_check(paths, True)
    check_for_update(paths, current_version="2.0.0", now_s=1_000,
                     fetch=answering("v2.1.0"))
    settings.set_update_check(paths, False)
    status = check_for_update(paths, current_version="2.0.0", now_s=1_000,
                              fetch=answering("v2.1.0"))
    assert status.enabled is False
    assert status.newer is False
    assert status.message is None


def test_callers_get_the_real_lookup_without_having_to_wire_it_up():
    """The CLI and the TUI call this with a version and a clock and nothing
    else, so the default has to be the real GitHub lookup -- asserted by
    identity rather than by calling it."""
    default = inspect.signature(check_for_update).parameters["fetch"].default
    assert default is update_check.fetch_latest_tag


def test_importing_the_module_does_not_import_urllib():
    """``urllib.request`` is imported inside the fetch function's body, not at
    module scope, so ``import shambles`` -- which the GUI, the TUI and every
    test do -- never pulls a networking stack into the process. Asserted in a
    fresh interpreter because pytest's own dependencies import plenty.
    """
    repo_root = pathlib.Path(update_check.__file__).resolve().parent.parent
    probe = ("import sys, shambles.update_check as u;"
             "print(sorted(m for m in sys.modules"
             " if m in ('socket', 'urllib.request', 'ssl', 'http.client')))")
    finished = subprocess.run([sys.executable, "-c", probe], cwd=repo_root,
                              capture_output=True, text=True, check=True)
    assert finished.stdout.strip() == "[]"
