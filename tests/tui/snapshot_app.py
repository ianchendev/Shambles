"""Deterministic fixture apps for TUI visual regression snapshots.

``pytest-textual-snapshot``'s ``snap_compare`` fixture imports this file as a
plain script (``runpy.run_path``) and looks for a module-level ``App``
instance -- ``app`` by default, or a named one via ``"snapshot_app.py:name"``.
Every app below is built from literal :mod:`shambles.app.snapshot` data
rather than a real ``ShamblesService`` reading a real home directory, so what
gets rendered never depends on the machine, the clock, or account state on
disk -- only on the literal values in this file.
"""

import os

from shambles.app.snapshot import Account, Group, Snapshot, Surface, Window
from shambles.app.tui.application import ShamblesTUI


class FrozenService:
    """The one slice of ``ShamblesService`` a render-only screen needs.

    Snapshot tests never press a key that would drive a switch, refresh, or
    lifecycle mutation -- they only render a single screen -- so unlike
    ``tests/tui/test_application.py``'s fuller ``SnapshotService`` stand-in,
    ``snapshot()`` is the only method ``ShamblesTUI.__init__`` actually calls.
    """

    def __init__(self, snapshot: Snapshot):
        self._snapshot = snapshot

    def snapshot(self) -> Snapshot:
        return self._snapshot


def _populated_snapshot() -> Snapshot:
    """One active/healthy account, one needing login, and a second provider.

    The same shape ``tests/tui/test_dashboard.py``'s ``snapshot`` fixture
    uses, reused here so what a reviewer sees in the SVG matches what the
    unit tests already assert about that exact data.
    """
    return Snapshot(1, groups=[
        Group(
            "claude", "Claude",
            surfaces=[Surface("terminal", "Terminal"), Surface("vscode", "VS Code")],
            accounts=[
                Account(
                    "Work", email="work@example.test", plan="Max 5x",
                    active=True, state="healthy",
                    usage=[Window("session", 22, resets_at_ms=1_788_000_000_000,
                                  resets_label="4:30 PM", age_label="just now")],
                ),
                Account(
                    "Personal", email="personal@example.test", state="unknown",
                    needs_login=True, login_hint="Run claude login",
                    usage=[Window("week", 33, resets_at_ms=None)],
                ),
            ],
        ),
        Group("codex", "Codex", surfaces=[Surface("terminal", "Terminal")],
              accounts=[Account("Personal", display_name="Taylor")]),
    ])


def _empty_snapshot() -> Snapshot:
    """No accounts anywhere -- the state that shows the onboarding screen."""
    return Snapshot(1, groups=[Group("claude", "Claude")])


#: The main dashboard, at whichever terminal size a test asks for.
app = ShamblesTUI(FrozenService(_populated_snapshot()), motion=False)

#: Onboarding with ``unicode=False`` -- the plain-ASCII fallback wordmark and
#: box-drawing a terminal without Unicode line-drawing glyphs gets instead.
ascii_app = ShamblesTUI(
    FrozenService(_empty_snapshot()), motion=False, unicode=False,
)

#: Onboarding as a real ``NO_COLOR`` terminal sees it. ``ShamblesTUI`` reads
#: ``NO_COLOR`` from the environment at construction time and turns its
#: onboarding box-draw animation off (see
#: ``shambles/app/tui/application.py``'s ``ShamblesTUI.__init__``), so the
#: frame renders fully drawn on its very first frame instead of animating in
#: over three ~150ms steps -- exactly what
#: ``tests/tui/test_application.py::test_motion_opt_out_starts_with_a_complete_frame``
#: asserts about the ``NO_COLOR`` mode. The environment is restored
#: immediately after construction so importing this module never leaves
#: ``NO_COLOR`` set for anything else in the process.
_environ_before = dict(os.environ)
os.environ["NO_COLOR"] = "1"
try:
    no_color_app = ShamblesTUI(FrozenService(_empty_snapshot()), motion=True)
finally:
    os.environ.clear()
    os.environ.update(_environ_before)
