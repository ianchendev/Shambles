"""U2 end to end: the real service on a synthetic home, driven through the
bridge the way the window's timers drive it."""

import os

import pytest

pytest.importorskip("PySide6.QtCore", exc_type=ImportError,
                    reason="PySide6 is not installed or cannot load")

from helpers import (NOW, make_claude_json, make_live_claude_login,  # noqa: E402
                     make_profile)
from qt_support import qt_app  # noqa: E402,F401
from shambles import providers  # noqa: E402
from shambles.app.qt import bridge as bridge_mod  # noqa: E402
from shambles.app.service import ShamblesService  # noqa: E402


def usage(percent):
    return {"cachedUsageUtilization": {
        "fetchedAtMs": NOW, "accountUuid": "uuid-a",
        "utilization": {"limits": [
            {"kind": "session", "percent": percent, "severity": "normal"}]}}}


def test_usage_claude_code_writes_shows_up_on_the_next_poll(paths, qt_app):
    make_profile(paths, "claude", "Work", email="work@example.test",
                 active=True)
    make_live_claude_login(paths, access_token="tok-Work")
    make_claude_json(paths, email="work@example.test", extra=usage(12))
    service = ShamblesService(paths=paths,
                              providers=providers.all_providers(env={}),
                              platform="linux", clock_ms=lambda: NOW)
    ui = bridge_mod.Bridge(service, runner=lambda work: work(),
                           clock_ms=lambda: NOW)
    ui.start()
    try:
        live = ui.view["groups"][0]["live"]
        assert [b["percent"] for b in live["usage"]] == [12]

        make_claude_json(paths, email="work@example.test", extra=usage(64))
        later = paths.claude_json.stat().st_mtime_ns + 5_000_000_000
        os.utime(paths.claude_json, ns=(later, later))
        ui.poll()

        live = ui.view["groups"][0]["live"]
        assert [b["percent"] for b in live["usage"]] == [64]
    finally:
        ui.shutdown()
