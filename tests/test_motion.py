"""The tween kit.

Tk has no animation API and no per-widget opacity, so every effect in the
window is the same shape: tick a frame on ``after``, ease a number, set a
property. The easing and colour maths are pure functions and are tested
without a display; only the driver needs a real widget.
"""

import time

import pytest

from shambles import motion


# ---- easing --------------------------------------------------------------

def test_easing_starts_at_zero_and_ends_at_one():
    assert motion.ease_out_cubic(0.0) == 0.0
    assert motion.ease_out_cubic(1.0) == 1.0


def test_easing_is_monotonic():
    seen = [motion.ease_out_cubic(i / 20) for i in range(21)]
    assert seen == sorted(seen)


def test_easing_is_front_loaded():
    """Ease-out means most of the distance is covered early, which is what
    makes a 120ms hover read as responsive rather than as a delay."""
    assert motion.ease_out_cubic(0.5) > 0.5


# ---- colour blending -----------------------------------------------------

def test_blending_a_colour_with_itself_changes_nothing():
    for t in (0.0, 0.37, 1.0):
        assert motion.lerp_hex("#2563eb", "#2563eb", t) == "#2563eb"


def test_the_ends_of_a_blend_are_the_colours_themselves():
    assert motion.lerp_hex("#ffffff", "#2563eb", 0.0) == "#ffffff"
    assert motion.lerp_hex("#ffffff", "#2563eb", 1.0) == "#2563eb"


def test_the_midpoint_is_halfway():
    assert motion.lerp_hex("#000000", "#ffffff", 0.5) == "#808080"


def test_a_blend_is_always_a_drawable_six_digit_hex():
    for i in range(21):
        got = motion.lerp_hex("#f4f5f7", "#17181c", i / 20)
        assert len(got) == 7 and got[0] == "#"
        int(got[1:], 16)  # raises if it is not hex


def test_uppercase_and_shorthand_input_is_accepted():
    """Tk hands back whatever was set, and cget can return any of these."""
    assert motion.lerp_hex("#FFFFFF", "#000000", 0.0) == "#ffffff"
    assert motion.lerp_hex("#fff", "#000", 1.0) == "#000000"


# ---- honouring a reduced-motion preference -------------------------------

def test_motion_is_on_by_default():
    assert motion.wants_motion(None) is True


def test_motion_can_be_turned_off():
    for off in ("0", "off", "no", "none", "false", "OFF", " off "):
        assert motion.wants_motion(off) is False, off


def test_an_unrecognised_value_leaves_motion_on():
    assert motion.wants_motion("yes") is True
    assert motion.wants_motion("") is True


# ---- the driver ----------------------------------------------------------

@pytest.fixture
def root():
    tk = pytest.importorskip("tkinter")
    try:
        made = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    made.withdraw()
    yield made
    made.destroy()


def _pump(root, until, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        root.update()
        if until():
            return True
        time.sleep(0.005)
    return False


def test_a_tween_finishes_exactly_on_one(root):
    """A tween that stops at 0.98 leaves the card a shade off its resting
    colour, and the drift accumulates over a session."""
    seen = []
    motion.animate(root, 60, seen.append)

    assert _pump(root, lambda: seen and seen[-1] == 1.0), f"never finished: {seen}"
    assert seen[-1] == 1.0


def test_a_tween_reports_progress_more_than_once(root):
    seen = []
    motion.animate(root, 120, seen.append)

    assert _pump(root, lambda: seen and seen[-1] == 1.0)
    assert len(seen) > 1, "that was a jump, not an animation"


def test_the_done_callback_fires_after_the_last_frame(root):
    order = []
    motion.animate(root, 50, lambda p: order.append(("step", p)),
                   done=lambda: order.append(("done", None)))

    assert _pump(root, lambda: order and order[-1][0] == "done")
    assert order[-1] == ("done", None)
    assert order[-2] == ("step", 1.0)


def test_cancelling_stops_the_frames(root):
    seen = []
    running = motion.animate(root, 400, seen.append)
    _pump(root, lambda: len(seen) >= 2)
    running.cancel()
    frozen = len(seen)

    _pump(root, lambda: False, timeout=0.2)
    assert len(seen) == frozen, "a cancelled tween kept painting"
    assert seen[-1] < 1.0, "cancelled too late to prove anything"


def test_a_cancelled_tween_never_fires_done(root):
    fired = []
    running = motion.animate(root, 400, lambda _p: None,
                             done=lambda: fired.append(True))
    _pump(root, lambda: False, timeout=0.1)
    running.cancel()

    _pump(root, lambda: False, timeout=0.3)
    assert not fired, "a cancelled tween still reported completion"


def test_a_widget_destroyed_mid_tween_does_not_raise(root):
    """refresh() destroys the whole row tree, and it does it constantly --
    on every switch, rename and remove. A tween in flight must simply stop."""
    tk = pytest.importorskip("tkinter")
    doomed = tk.Frame(root)
    doomed.pack()

    def step(p):
        doomed.configure(width=int(40 + 40 * p))

    motion.animate(doomed, 400, step)
    _pump(root, lambda: False, timeout=0.05)
    doomed.destroy()

    # No exception may escape into the Tk callback handler.
    assert _pump(root, lambda: False, timeout=0.3) is False


def test_destroying_a_widget_cancels_its_tween(root):
    """Deterministically, rather than by letting the timer fire into a dead
    widget -- Tk reports that as `invalid command name "...tick"` on stderr,
    from inside its own error handler where nothing can catch it."""
    tk = pytest.importorskip("tkinter")
    doomed = tk.Frame(root)
    doomed.pack()

    running = motion.animate(doomed, 400, lambda _p: None)
    _pump(root, lambda: False, timeout=0.05)
    doomed.destroy()
    root.update()

    assert not running.running, "the tween outlived the widget it was painting"


def test_a_child_dying_does_not_cancel_its_parents_tween(root):
    """The window fade is a tween on the toplevel, and refresh() destroys
    widgets underneath it constantly. Cancelling on any descendant's
    <Destroy> would strand the window part-way through fading in.
    """
    tk = pytest.importorskip("tkinter")
    holder = tk.Frame(root)
    holder.pack()
    child = tk.Frame(holder)
    child.pack()

    running = motion.animate(holder, 400, lambda _p: None)
    _pump(root, lambda: False, timeout=0.05)
    child.destroy()
    root.update()

    assert running.running, "a child's destruction cancelled the parent's tween"


def test_with_motion_off_the_step_lands_on_its_final_value_at_once(root, monkeypatch):
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    seen = []
    running = motion.animate(root, 400, seen.append)

    assert seen == [1.0], "reduced motion must still reach the end state"
    assert running.finished


def test_with_motion_off_done_still_fires(root, monkeypatch):
    monkeypatch.setenv(motion.MOTION_ENV, "0")
    fired = []
    motion.animate(root, 400, lambda _p: None, done=lambda: fired.append(True))

    assert fired == [True]


def test_cancelling_a_finished_tween_is_harmless(root):
    running = motion.animate(root, 30, lambda _p: None)
    _pump(root, lambda: running.finished)
    running.cancel()
    running.cancel()
