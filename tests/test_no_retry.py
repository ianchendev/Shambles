"""A step that fails, fails the switch at once, and says so.

There used to be a retry wrapper here. Since 2.1.0 it retried nothing a
store did (stores raise StoreUnavailableError, the wrapper caught OSError),
and making it work showed why it should not exist: a retried write waits out
whatever held the file and then overwrites what that program wrote, from a
copy taken before the wait. If that program was the vendor rotating its
token, the rotated token is gone. Owner decision D5: delete it.

The one thing it still did was retry the backup of ~/.claude.json. That now
fails the switch on the first refusal, before anything has moved.
"""

import pytest

from helpers import make_claude_json, make_live_claude_login, make_profile
from shambles import configjson, providers, state, switcher
from shambles.errors import SwitchFailedError


def test_a_backup_that_fails_once_fails_the_switch_and_moves_nothing(
        paths, monkeypatch):
    claude = providers.load("claude", env={})
    make_profile(paths, "claude", "Work", email="w@example.test", active=True)
    make_profile(paths, "claude", "Other", email="o@example.test")
    make_claude_json(paths, email="w@example.test")
    live = make_live_claude_login(paths, access_token="tok-Work")
    before = live.read_bytes()
    real = configjson.backup
    calls = []

    def busy_once(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise PermissionError(13, "the file is in use")
        return real(*args, **kwargs)

    monkeypatch.setattr(configjson, "backup", busy_once)
    slept = []

    with pytest.raises(SwitchFailedError):
        switcher.switch(paths, claude, "Other", platform="linux",
                        sleep=slept.append)

    assert calls == [1], "the backup was tried again"
    assert slept == []
    assert live.read_bytes() == before
    assert state.read_active(paths, "claude") == "Work"


def test_there_is_no_retry_module():
    """Checked on disk, not with an import: the editable install's finder
    serves a module missing from a worktree out of the main checkout."""
    from pathlib import Path

    import shambles
    package = Path(shambles.__file__).parent
    assert not (package / "retry.py").exists()
    assert not any("retry" in line and "import" in line
                   for source in package.rglob("*.py")
                   for line in source.read_text(encoding="utf-8").splitlines()
                   if line.lstrip().startswith(("from", "import")))
