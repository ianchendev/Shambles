"""Opening the sign-in URL, including where Python's own opener cannot.

`webbrowser` picks `gio` under WSL, which has no handler and fails with
"Operation not supported" -- while reporting success, so a caller that trusts
its return value never falls back.
"""

import pytest

from shambles import login


def test_wsl_prefers_the_windows_openers():
    order = login.browser_commands(wsl=True, which=lambda c: f"/usr/bin/{c}")
    assert order, "no opener offered under WSL"
    assert order[0][0][0] == "wslview"
    assert any(argv[0] == "explorer.exe" for argv, _codes in order)


def test_wsl_skips_openers_that_are_not_installed():
    """wslview ships in wslu, which is not installed by default."""
    present = {"explorer.exe", "cmd.exe"}
    order = login.browser_commands(
        wsl=True, which=lambda c: f"/x/{c}" if c in present else None)
    names = [argv[0] for argv, _codes in order]
    assert "wslview" not in names
    assert names[0] == "explorer.exe"


def test_a_plain_linux_desktop_uses_the_usual_openers():
    order = login.browser_commands(wsl=False, which=lambda c: f"/usr/bin/{c}")
    names = [argv[0] for argv, _codes in order]
    assert "explorer.exe" not in names
    assert "xdg-open" in names


def test_nothing_installed_means_no_commands():
    assert login.browser_commands(wsl=True, which=lambda c: None) == []


def test_the_url_is_never_passed_through_a_shell():
    """It comes from a subprocess's stdout; it must stay one argv element."""
    hostile = "https://x.example/?a=1;rm -rf ~"
    seen = []

    def runner(argv, **kw):
        seen.append(argv)
        class R:
            returncode = 0
        return R()

    login.open_url(hostile, wsl=True, which=lambda c: f"/x/{c}", runner=runner)
    assert seen, "nothing was run"
    assert hostile in seen[0], "the URL was mangled or interpolated"
    assert not any(isinstance(a, str) and " " in a and "http" not in a
                   for a in seen[0][:-1]), "an argv element looks shell-joined"


def test_open_url_reports_failure_when_every_opener_fails():
    def runner(argv, **kw):
        class R:
            returncode = 127          # no opener treats this as success
        return R()

    assert login.open_url("https://x.example", wsl=True,
                          which=lambda c: f"/x/{c}", runner=runner) is False


def test_open_url_stops_at_the_first_success():
    calls = []

    def runner(argv, **kw):
        calls.append(argv[0])
        class R:
            returncode = 0
        return R()

    assert login.open_url("https://x.example", wsl=True,
                          which=lambda c: f"/x/{c}", runner=runner) is True
    assert len(calls) == 1, f"kept going after success: {calls}"


def test_a_runner_that_raises_falls_through_rather_than_crashing():
    def runner(argv, **kw):
        raise OSError("no such binary")

    assert login.open_url("https://x.example", wsl=True,
                          which=lambda c: f"/x/{c}", runner=runner) is False


def test_only_http_urls_are_ever_opened():
    """open_url feeds whatever it is given to a process."""
    for bad in ("file:///etc/passwd", "", None, "javascript:alert(1)"):
        assert login.open_url(bad, wsl=True, which=lambda c: f"/x/{c}",
                              runner=lambda *a, **k: None) is False


def test_explorer_returning_one_counts_as_success():
    """explorer.exe returns 1 on success. Treating non-zero as failure
    rejected the one opener that works under WSL."""
    def runner(argv, **kw):
        class R:
            returncode = 1
        return R()

    assert login.open_url("https://x.example", wsl=True,
                          which=lambda c: f"/x/{c}" if c == "explorer.exe"
                          else None, runner=runner) is True


def test_cmd_exe_is_not_offered():
    """cmd splits its argument at & whatever the quoting, and every OAuth URL
    is full of them."""
    order = login.browser_commands(wsl=True, which=lambda c: f"/x/{c}")
    assert not any(argv[0] == "cmd.exe" for argv, _codes in order)


def test_a_desktop_opener_returning_one_is_still_a_failure():
    """Only explorer.exe gets that latitude."""
    def runner(argv, **kw):
        class R:
            returncode = 1
        return R()

    assert login.open_url("https://x.example", wsl=False,
                          which=lambda c: f"/x/{c}", runner=runner) is False
