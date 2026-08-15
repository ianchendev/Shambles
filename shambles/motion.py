"""Tweening, for a toolkit that has no animation and no alpha.

Tk gives you one primitive: ``after``. Every effect in the window is built
from the same loop -- tick a frame, ease a number, set a property -- so it is
written once here rather than five times in the widget tree.

Two consequences of Tk's model shape this module:

* **There is no per-widget opacity.** A "fade" is a colour blend against
  whatever is actually behind the widget, which is why :func:`lerp_hex` takes
  two solid colours rather than a colour and an alpha.
* **Widgets die mid-flight.** ``refresh()`` destroys and rebuilds the whole
  row tree on every switch, rename and remove, so a tween must treat a
  vanished widget as an ordinary stopping condition rather than an error.
"""

import os
import tkinter as tk

#: Frame interval. ``after`` is not vsynced and Tk makes no timing promise, so
#: this is a target rather than a guarantee -- fine for the 120-420ms range
#: everything here runs in, and honest about not being a render loop.
FRAME_MS = 16

#: Opt out of motion entirely, e.g. SHAMBLES_MOTION=off. Mirrors the
#: SHAMBLES_SCALE escape hatch in :mod:`shambles.theme`. Tk cannot see the
#: desktop's own reduced-motion setting, so an explicit variable is the only
#: way to honour the preference at all.
MOTION_ENV = "SHAMBLES_MOTION"

OFF_VALUES = frozenset({"0", "off", "no", "none", "false"})

_UNSET = object()


def wants_motion(override=_UNSET) -> bool:
    """Whether to animate. Anything unrecognised leaves motion on."""
    if override is _UNSET:
        override = os.environ.get(MOTION_ENV)
    if override is None:
        return True
    return override.strip().lower() not in OFF_VALUES


def ease_out_cubic(t: float) -> float:
    """Most of the distance early, settling at the end.

    Ease-out rather than linear because these tweens confirm something that
    has already happened; the eye should arrive with the change, not travel
    alongside it.
    """
    return 1 - (1 - t) ** 3


def _channels(colour: str):
    """``#rgb`` or ``#rrggbb`` -> three ints. Case-insensitive."""
    raw = colour.lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))


def lerp_hex(start: str, end: str, t: float) -> str:
    """Blend two ``#rrggbb`` colours, ``t`` from 0 to 1.

    Hex only, deliberately: resolving a named colour needs a live widget, and
    a caller reading a half-blended value back out of ``cget`` is exactly the
    bug this signature prevents. Callers track their own start colour.
    """
    sr, sg, sb = _channels(start)
    er, eg, eb = _channels(end)
    return "#%02x%02x%02x" % (
        round(sr + (er - sr) * t),
        round(sg + (eg - sg) * t),
        round(sb + (eb - sb) * t),
    )


class Animation:
    """A tween in flight. Hold it to cancel.

    Cancelling leaves the property wherever it had reached rather than
    snapping to either end -- a pointer crossing two cards in quick
    succession should hand over mid-blend, not flash.
    """

    __slots__ = ("_widget", "_job", "_cancelled", "_death", "finished")

    def __init__(self, widget):
        self._widget = widget
        self._job = None
        self._cancelled = False
        self._death = None
        self.finished = False

    @property
    def running(self) -> bool:
        return not (self.finished or self._cancelled)

    def watch_widget(self) -> None:
        """Stop if the widget is destroyed.

        Without this the timer still fires after Tk has deleted the widget's
        command, and Tk reports ``invalid command name "...tick"`` from
        inside its own background error handler, where no ``except`` in this
        module can reach it. ``refresh()`` destroys every row on every
        action, so that is the common case rather than the rare one.
        """
        try:
            self._death = self._widget.bind("<Destroy>", self._died, add="+")
        except tk.TclError:
            pass  # already gone; the first tick will stop on its own

    def _died(self, event=None) -> None:
        # <Destroy> reaches this binding for descendants too. Cancelling on
        # those would be wrong: the window fade is a tween on the toplevel,
        # and a card being rebuilt underneath it must not strand the window
        # part-way through fading in.
        if event is not None and str(getattr(event, "widget", "")) != str(self._widget):
            return
        self.cancel()

    def release(self) -> None:
        """Drop the ``<Destroy>`` watch, leaving the tween's state alone.

        A long-lived widget -- the toplevel, which the window fade animates --
        would otherwise collect one dead binding per tween for the life of
        the session.
        """
        death, self._death = self._death, None
        if death is not None:
            try:
                self._widget.unbind("<Destroy>", death)
            except tk.TclError:
                pass

    def cancel(self) -> None:
        """Stop the tween. Safe to call twice, and after it has finished."""
        self._cancelled = True
        job, self._job = self._job, None
        if job is not None:
            try:
                self._widget.after_cancel(job)
            except tk.TclError:
                pass  # the widget, or the interpreter, is already gone
        self.release()


def animate(widget, duration_ms: int, step, *, ease=ease_out_cubic, done=None):
    """Drive ``step(progress)`` from 0 to 1 over ``duration_ms``.

    ``step`` always receives exactly ``1.0`` on its final call: a tween that
    stops at 0.98 leaves a card a shade off its resting colour, and the drift
    accumulates across a session. ``done`` fires after that last frame, and
    never for a cancelled tween.

    With motion turned off the end state is applied immediately -- the window
    must still be correct, just not animated.
    """
    running = Animation(widget)

    def land():
        """Apply the finished state without animating to it."""
        try:
            step(1.0)
        except tk.TclError:
            running.finished = True
            return
        running.finished = True
        if done:
            done()

    if duration_ms <= 0 or not wants_motion():
        land()
        return running

    frames = max(1, int(duration_ms // FRAME_MS))
    counter = {"n": 0}

    def tick():
        running._job = None
        if running._cancelled:
            return
        counter["n"] += 1
        progress = min(1.0, counter["n"] / frames)
        try:
            step(ease(progress))
        except tk.TclError:
            running.finished = True
            return  # the widget went away; that is a stop, not a failure
        if progress >= 1.0:
            running.finished = True
            running.release()
            if done:
                done()
            return
        running._job = _schedule(widget, tick, running)

    running._job = _schedule(widget, tick, running)
    running.watch_widget()
    return running


def _schedule(widget, callback, running):
    """``after``, treating a dead widget as the end of the tween."""
    try:
        return widget.after(FRAME_MS, callback)
    except tk.TclError:
        running.finished = True
        return None
