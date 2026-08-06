"""The GUI is smoke-tested only -- no display is assumed in CI."""

import pytest

tk = pytest.importorskip("tkinter")


def test_module_imports_and_exposes_run():
    from shambles import gui
    assert callable(gui.run)
    assert issubclass(gui.ShamblesApp, tk.Tk)


def test_header_text_for_each_state(paths):
    from helpers import make_claude_json, make_profile
    from shambles import gui, state

    make_claude_json(paths, email="work@example.com")
    assert "no accounts saved" in gui.header_text(
        paths, state.inspect(paths)).lower()

    make_profile(paths, "Work", email="work@example.com", active=True)
    text = gui.header_text(paths, state.inspect(paths))
    assert "Work" in text
    assert "work@example.com" in text


def test_header_reports_a_missing_profile(paths):
    from helpers import make_claude_json, make_profile
    from shambles import gui, state

    make_profile(paths, "Gone", email="gone@example.com", active=True)
    make_claude_json(paths, email="gone@example.com")
    for child in paths.profile_dir("Gone").iterdir():
        child.unlink()
    paths.profile_dir("Gone").rmdir()

    text = gui.header_text(paths, state.inspect(paths))
    assert "Gone" in text and "missing" in text.lower()


def test_header_reports_drift_after_a_manual_login(paths):
    from helpers import make_claude_json, make_profile
    from shambles import gui, state

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="someone-else@example.com")
    text = gui.header_text(paths, state.inspect(paths))
    assert "someone-else@example.com" in text


def test_header_reports_a_failed_merge(paths):
    """Startup repairs the old layout automatically, so seeing this state at
    all means the merge failed."""
    import os

    from helpers import make_claude_json, make_profile
    from shambles import gui, state

    make_profile(paths, "Work", email="work@example.com")
    make_claude_json(paths, email="work@example.com")
    os.symlink(str(paths.profile_dir("Work")), str(paths.claude_dir),
               target_is_directory=True)
    text = gui.header_text(paths, state.inspect(paths)).lower()
    assert "could not merge" in text


def test_window_renders_every_profile_state(paths, make_app):
    """Builds the real widget tree and forces a render pass, so a broken
    card layout fails here instead of only when the user launches it."""
    import json
    import os

    from helpers import DAY_MS, make_claude_json, make_profile
    from shambles import gui, switcher

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
    paths.active_marker.write_text("Healthy\n", encoding="utf-8")

    app = make_app(paths)
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



def test_window_renders_with_no_profiles(paths, make_app):
    from shambles import gui

    app = make_app(paths)
    app.update()
    assert any("No profiles yet" in t for t in _all_text(app.rows))


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


def test_window_warns_when_config_dir_is_overridden(paths, make_app, monkeypatch):
    """A globally-set CLAUDE_CONFIG_DIR makes the CLI ignore every swap."""
    from helpers import make_claude_json, make_live_login, make_profile

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)
    elsewhere = paths.home / "elsewhere-config"
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere))

    app = make_app(paths)
    app.update()

    texts = []
    def walk(w):
        for child in w.winfo_children():
            try:
                texts.append(str(child.cget("text")))
            except tk.TclError:
                pass
            walk(child)
    walk(app)
    joined = " ".join(texts)
    assert "CLAUDE_CONFIG_DIR" in joined
    assert "elsewhere-config" in joined


def test_window_is_quiet_when_config_dir_is_unset(paths, make_app, monkeypatch):
    from helpers import make_claude_json, make_live_login, make_profile

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)

    app = make_app(paths)
    app.update()

    texts = []
    def walk(w):
        for child in w.winfo_children():
            try:
                texts.append(str(child.cget("text")))
            except tk.TclError:
                pass
            walk(child)
    walk(app)
    assert "CLAUDE_CONFIG_DIR" not in " ".join(texts)


def test_the_expiry_tooltip_does_not_name_a_fixed_window():
    """Measured windows differ by an order of magnitude between platform/plan
    samples (docs/token-storage.md). The tooltip sits next to a chip showing
    the real number, so naming a different one contradicts what is on screen."""
    from shambles import gui
    assert "30-day" not in gui.EXPIRY_TOOLTIP
    assert "30 day" not in gui.EXPIRY_TOOLTIP


def _buttons(widget, found=None):
    found = [] if found is None else found
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except tk.TclError:
            pass
        _buttons(child, found)
    return found


def test_only_inactive_profiles_offer_removal(paths, make_app):
    """The active profile must have no ✕ — the login in use cannot be deleted
    by a misclick."""
    from helpers import make_claude_json, make_live_login, make_profile

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_profile(paths, "Third", email="third@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    labels = _buttons(app)
    # two inactive profiles -> two ✕ and two Switch, never three
    assert labels.count("✕") == 2
    assert labels.count("Switch") == 2


def test_a_lone_active_profile_offers_no_removal(paths, make_app):
    from helpers import make_claude_json, make_live_login, make_profile

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    assert "✕" not in _buttons(app)


def test_declining_the_confirmation_removes_nothing(paths, make_app, monkeypatch):
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import gui, state

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: False)
    app = make_app(paths)
    app.on_remove("Personal")

    assert paths.credentials("Personal").exists()
    assert sorted(state.profile_names(paths)) == ["Personal", "Work"]


def test_confirming_removes_the_profile_and_refreshes(paths, make_app, monkeypatch):
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import gui, state

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    monkeypatch.setattr(gui.messagebox, "askyesno", lambda *a, **k: True)
    app = make_app(paths)
    app.on_remove("Personal")
    app.update()

    assert state.profile_names(paths) == ["Work"]
    assert "Personal" not in " ".join(_buttons(app)), "still listed after removal"


def test_the_confirmation_names_the_profile_and_the_cost(paths, make_app,
                                                         monkeypatch):
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import gui

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    seen = {}
    def capture(title, message, **k):
        seen["title"], seen["message"] = title, message
        return False
    monkeypatch.setattr(gui.messagebox, "askyesno", capture)

    app = make_app(paths)
    app.on_remove("Personal")

    assert seen["title"] == "Remove Profile"
    assert "'Personal'" in seen["message"]
    assert "permanently destroy its stored login token" in seen["message"]
