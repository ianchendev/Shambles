"""Visual regression snapshots for the terminal UI.

Each test renders one of ``tests/tui/snapshot_app.py``'s deterministic apps
to an SVG and compares it against the accepted fixture under
``tests/tui/__snapshots__/test_snapshots/`` (the default location
``pytest-textual-snapshot``/``syrupy`` write to -- there is no supported way
to rename it without reimplementing the plugin's file layout, so this suite
uses it as-is rather than fighting the tool).

Run just this file with::

    .venv/bin/python -m pytest tests/tui/test_snapshots.py -v

A first run, or any run after a deliberate rendering change, fails until the
new SVG is reviewed and accepted with ``--snapshot-update``.
"""

import pytest


@pytest.mark.parametrize("terminal_size", [
    (100, 32),
    (78, 28),
    (78, 16),  # wide-but-short: compact header, inline details
    (60, 28),
    (48, 24),
    (40, 24),
])
def test_dashboard_layouts(snap_compare, terminal_size):
    assert snap_compare("snapshot_app.py", terminal_size=terminal_size)


def test_empty_welcome_unicode_lockup(snap_compare):
    """Empty unicode welcome shows the lockup and add/eject footer."""
    assert snap_compare("snapshot_app.py:empty_app", terminal_size=(100, 32))


def test_onboarding_ascii_fallback_is_readable(snap_compare):
    """``unicode=False`` empty welcome uses the ASCII lockup."""
    assert snap_compare("snapshot_app.py:ascii_app", terminal_size=(100, 32))


def test_onboarding_under_no_color_settles_immediately(snap_compare):
    """``NO_COLOR`` empty welcome is monochrome with the same glyphs."""
    assert snap_compare("snapshot_app.py:no_color_app", terminal_size=(100, 32))
