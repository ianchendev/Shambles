"""The GUI is smoke-tested only -- no display is assumed in CI."""

import pytest

tk = pytest.importorskip("tkinter")


def test_module_imports_and_exposes_run():
    from shambles import gui
    assert callable(gui.run)
    assert issubclass(gui.ShamblesApp, tk.Tk)


def test_header_text_for_each_link_state(paths):
    import os

    from helpers import make_claude_json, make_profile
    from shambles import gui, links

    make_profile(paths, "Work", email="work@example.com")
    make_claude_json(paths, email="work@example.com")

    assert "not set up" in gui.header_text(paths, links.inspect(paths)).lower()

    os.symlink(str(paths.profile_dir("Work")), str(paths.claude_dir),
               target_is_directory=True)
    text = gui.header_text(paths, links.inspect(paths))
    assert "Work" in text
    assert "work@example.com" in text


def test_header_reports_a_broken_link(paths):
    import os

    from helpers import make_profile
    from shambles import gui, links

    make_profile(paths, "Gone")
    os.symlink(str(paths.profile_dir("Gone")), str(paths.claude_dir),
               target_is_directory=True)
    for child in paths.profile_dir("Gone").iterdir():
        child.unlink()
    paths.profile_dir("Gone").rmdir()

    text = gui.header_text(paths, links.inspect(paths))
    assert "Broken" in text


def _display_or_skip():
    """A real Tk window needs a display; skip rather than fail without one."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display: {exc}")
    root.destroy()


def test_window_renders_every_profile_state(paths):
    """Builds the real widget tree and forces a render pass, so a broken
    card layout fails here instead of only when the user launches it."""
    import json
    import os

    from helpers import DAY_MS, make_claude_json, make_profile
    from shambles import gui, switcher

    _display_or_skip()

    # The window reads the real clock, so anchor the fixtures to it. The extra
    # hour keeps each value off a day boundary, where flooring would flip it.
    now = switcher.now_ms()
    hour = 3_600_000
    make_profile(paths, "Healthy", email="ok@example.com",
                 refresh_expires_ms=now + 29 * DAY_MS + hour)
    make_profile(paths, "Soon", email="soon@example.com",
                 refresh_expires_ms=now + 4 * DAY_MS + hour)
    make_profile(paths, "Lapsed", email="old@example.com",
                 refresh_expires_ms=now - 3 * DAY_MS + hour)
    make_profile(paths, "Fresh", token=False)
    make_claude_json(paths, email="ok@example.com")
    os.symlink(str(paths.profile_dir("Healthy")), str(paths.claude_dir),
               target_is_directory=True)

    app = gui.ShamblesApp(paths)
    app.update()

    assert app.winfo_width() >= 400
    assert "Healthy" in app.title_label.cget("text")
    assert "ok@example.com" in app.subtitle.cget("text")
    assert str(app.save_button.cget("state")) == "disabled"

    texts = _all_text(app.rows)
    for expected in ("Healthy", "Soon", "Lapsed", "Fresh", "ACTIVE",
                     "29d", "4d", "expired 3d ago", "⚠"):
        assert any(expected in t for t in texts), f"missing from UI: {expected}"
    # the active card offers no Switch of its own
    assert sum(t == "Switch" for t in texts) == 3

    app.destroy()


def test_window_renders_with_no_profiles(paths):
    from shambles import gui

    _display_or_skip()
    app = gui.ShamblesApp(paths)
    app.update()
    assert any("No profiles yet" in t for t in _all_text(app.rows))
    app.destroy()


def _all_text(widget):
    found = []
    for child in widget.winfo_children():
        try:
            text = child.cget("text")
        except Exception:
            text = ""
        if text:
            found.append(str(text))
        found.extend(_all_text(child))
    return found
