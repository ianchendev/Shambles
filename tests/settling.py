"""Waiting for a Textual screen to settle: on a condition, by the clock.

Every terminal-UI test that acts and then asserts goes through
:func:`settled`. ``pilot.pause()`` drains the message queue once and lets no
time pass, so an assertion made after a fixed number of pumps is a bet on
how many frames a platform takes: the Windows runners lost a different
handful of those bets on every run, and five retries per test were what
kept CI green. That is also how a real redraw bug -- a header that kept the
height of the text it had just replaced, and pushed the account list off
the screen for good -- passed as noise for weeks.

So the rule is: wait for the thing you are about to assert, up to a bound,
and if it never arrives fail with the whole screen and every widget's place
on it, because a condition that never holds is a bug to look at, not a
timeout to raise.
"""

import inspect
import time

#: Long enough for a slow CI runner to finish any layout Textual will ever
#: finish; the passing case returns as soon as the condition holds.
WITHIN = 5.0
POLL = 0.02


def screen_text(app) -> str:
    """What the active screen shows right now, as plain text lines."""
    return "\n".join(
        strip.text for strip in app.screen._compositor.render_strips()
    )


def layout_report(app, screen: str | None = None) -> str:
    """The whole screen and where each widget is, for a failed assertion.

    pytest shortens a long string to its first and last lines, which is all
    CI ever showed of the resize bug; this keeps the middle.
    """
    if screen is None:
        try:
            screen = screen_text(app)
        except Exception as exc:          # no screen to read is a finding too
            screen = f"<unreadable: {exc!r}>"
    try:
        regions = "\n".join(
            f"  #{w.id}: display={w.display} region={tuple(w.region)}"
            for w in app.screen.walk_children() if w.id)
        where = f"{type(app.screen).__name__}(id={app.screen.id!r})"
    except Exception as exc:
        regions, where = f"  <unreadable: {exc!r}>", "?"
    return (f"\n--- screen {where} ---\n{screen}"
            f"\n--- widgets ---\n{regions}")


def _describe(condition) -> str:
    try:
        return inspect.getsource(condition).strip()
    except (OSError, TypeError):
        return repr(condition)


async def settled(pilot, app, condition, *, within: float = WITHIN):
    """Pump once, then wait until ``condition()`` is true, by the clock.

    The first pump is what every test did before, so a check for something
    that must *not* happen is held to the same moment it always was. After
    that the screen gets real time, in small steps, until the condition
    holds or ``within`` seconds pass. A condition that raises -- a widget not
    mounted yet, say -- counts as not yet. Fails with the condition's source
    and :func:`layout_report` when it never holds.

    Returns the condition's last value, so a caller can keep what it found.
    """
    await pilot.pause()
    deadline = time.monotonic() + within
    last_error = None
    while True:
        try:
            value = condition()
        except Exception as exc:          # not there yet
            value, last_error = None, exc
        else:
            last_error = None
            if value:
                return value
        if time.monotonic() >= deadline:
            break
        await pilot.pause(POLL)
    detail = f" (last raised {last_error!r})" if last_error else ""
    raise AssertionError(
        f"never held within {within} s{detail}: {_describe(condition)}"
        + layout_report(app))
