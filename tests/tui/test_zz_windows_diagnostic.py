"""Throwaway: dump what Windows actually renders. Delete before merging."""

import sys
from dataclasses import replace

import pytest
from rich.cells import cell_len

from shambles.app.tui.dashboard import Dashboard
from test_dashboard import DashboardHarness, screen_text
from test_dashboard import snapshot as _snapshot_fixture


@pytest.mark.parametrize("width", [60, 40])
async def test_diagnostic_dump(width):
    snap = _snapshot_fixture.__wrapped__()
    group = snap.groups[0]
    account = group.accounts[0]
    window = replace(account.usage[0], stale=True)
    snap = replace(snap, groups=[
        replace(group, accounts=[replace(account, usage=[window])])])

    app = DashboardHarness(snap)
    async with app.run_test(size=(width, 32)) as pilot:
        await pilot.pause()
        screen = screen_text(app)
        dash = app.query_one(Dashboard)
        classes = sorted(dash.classes)
        size = app.size

    print(f"\n@@@ WIDTH={width} platform={sys.platform} "
          f"encoding={sys.stdout.encoding} @@@")
    print(f"@@@ app.size={size} classes={classes} @@@")
    print(f"@@@ cell_len('5h  22%')={cell_len('5h  22%')} "
          f"cell_len('▊')={cell_len(chr(0x258a))} "
          f"cell_len('·')={cell_len(chr(0xb7))} @@@")
    print(f"@@@ lines={len(screen.splitlines())} has22={'22%' in screen} "
          f"hasStale={'stale' in screen} @@@")
    for i, line in enumerate(screen.splitlines()):
        print(f"@@@{i:02d}|{line.rstrip()!r}")
    assert False, "diagnostic dump"
