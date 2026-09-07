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
    (100, 32),  # wide: list and detail panes side by side
    (78, 28),   # the wide/medium breakpoint (see brand.variant_for)
    (60, 28),   # medium: the selected row expands its own inline detail
    (48, 24),   # the medium/compact breakpoint
    (40, 24),   # compact: decoration hidden, list stacked above detail
])
def test_dashboard_layouts(snap_compare, terminal_size):
    """The dashboard's five documented breakpoints all render real content."""
    assert snap_compare("snapshot_app.py", terminal_size=terminal_size)


def test_onboarding_ascii_fallback_is_readable(snap_compare):
    """``unicode=False`` swaps the box-drawing frame and wordmark for ASCII."""
    assert snap_compare("snapshot_app.py:ascii_app", terminal_size=(100, 32))


def test_onboarding_under_no_color_settles_immediately(snap_compare):
    """``NO_COLOR`` disables the onboarding draw-in animation outright, so
    the frame is complete on its very first rendered frame rather than
    showing a partially-drawn corner-only box."""
    assert snap_compare("snapshot_app.py:no_color_app", terminal_size=(100, 32))
