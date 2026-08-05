import pytest

from shambles import retry
from shambles.errors import SwitchFailedError, SymlinkPermissionError


def test_returns_value_on_first_success():
    assert retry.with_retry(lambda: "ok", "do a thing", sleep=_no_sleep) == "ok"


def test_retries_then_succeeds():
    calls = []
    naps = []

    def flaky():
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("locked")
        return "ok"

    assert retry.with_retry(flaky, "do a thing", sleep=naps.append) == "ok"
    assert len(calls) == 3
    assert naps == [0.5, 0.5]


def test_gives_up_after_three_attempts():
    calls = []

    def always_locked():
        calls.append(1)
        raise PermissionError("locked")

    with pytest.raises(SwitchFailedError) as exc:
        retry.with_retry(always_locked, "update ~/.claude", sleep=_no_sleep)

    assert len(calls) == 3
    assert "update ~/.claude" in str(exc.value)
    assert "Close any running Claude Code sessions" in str(exc.value)


def test_windows_1314_raises_immediately_without_retrying():
    calls = []

    def blocked():
        calls.append(1)
        err = OSError("privilege not held")
        err.winerror = 1314
        raise err

    with pytest.raises(SymlinkPermissionError) as exc:
        retry.with_retry(blocked, "create a symlink", sleep=_no_sleep)

    assert len(calls) == 1  # a privilege error will never resolve by waiting
    assert "Developer Mode" in str(exc.value)


def _no_sleep(_seconds):
    pass
