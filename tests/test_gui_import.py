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


def _all_widgets(widget, found=None):
    found = [] if found is None else found
    for child in widget.winfo_children():
        found.append(child)
        _all_widgets(child, found)
    return found


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


def test_tooltip_position_is_clamped_to_the_screen():
    """The ✕ sits at the right of a card, so its tooltip is the one that runs
    off the display — the screenshot showed it clipped mid-word."""
    from shambles.gui import tooltip_position

    # a button near the right edge, tooltip wider than the space left
    x, _y = tooltip_position(widget_x=1850, widget_y=100, widget_height=24,
                             tip_width=360, screen_width=1920, screen_height=1080)
    assert x + 360 <= 1920, f"tooltip runs to {x + 360} on a 1920 screen"
    assert x >= 0


def test_tooltip_position_is_unchanged_when_it_already_fits():
    from shambles.gui import tooltip_position

    x, y = tooltip_position(widget_x=100, widget_y=200, widget_height=24,
                            tip_width=360, screen_width=1920, screen_height=1080)
    assert (x, y) == (112, 230)


def test_tooltip_flips_above_when_it_would_fall_off_the_bottom():
    from shambles.gui import tooltip_position

    _x, y = tooltip_position(widget_x=100, widget_y=1050, widget_height=24,
                             tip_width=360, screen_width=1920, screen_height=1080,
                             tip_height=80)
    assert y + 80 <= 1080, "tooltip runs past the bottom of the screen"


def test_the_remove_button_is_not_styled_as_a_peer_of_switch(paths, make_app):
    """✕ and Switch shared a style, so a destructive control rendered in the
    same accent blue as the one you click constantly."""
    from helpers import make_claude_json, make_live_login, make_profile

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Personal", email="me@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)
    app = make_app(paths)
    app.update()

    styles = {}
    def walk(w):
        for c in w.winfo_children():
            try:
                styles[str(c.cget("text"))] = str(c.cget("style"))
            except tk.TclError:
                pass
            walk(c)
    walk(app)
    assert styles.get("✕") != styles.get("Switch"), \
        "the destructive control looks identical to the primary one"


def _usage_blob(session=None, week=None, fetched=None):
    limits = []
    if session is not None:
        limits.append({"kind": "session", "percent": session, "severity": "normal"})
    if week is not None:
        limits.append({"kind": "weekly_all", "percent": week, "severity": "warning"})
    return {"fetchedAtMs": fetched, "utilization": {"limits": limits}}


def test_the_active_card_shows_live_usage_chips(paths, make_app):
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import switcher

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com",
                     extra={"cachedUsageUtilization":
                            _usage_blob(22, 87, switcher.now_ms())})
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    # label, icon and value are separate widgets, so check the parts
    text = _buttons(app)
    assert "session" in text and "22%" in text
    assert "week" in text and "87%" in text


def test_a_stale_stashed_figure_is_labelled_with_its_age(paths, make_app):
    """The number is still worth showing — it says which account has headroom —
    but it must not pass for current."""
    from helpers import make_claude_json, make_live_login, make_profile, write_json
    from helpers import account as acct
    from shambles import switcher

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Other", email="other@example.com")
    write_json(paths.account("Other"), {
        "oauthAccount": acct("other@example.com"),
        "usage": _usage_blob(week=92,
                             fetched=switcher.now_ms() - 7 * 3_600_000)})
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    text = _buttons(app)
    assert "week" in text and "92%" in text
    assert any("7h ago" in t for t in text), \
        "a 7h-old figure rendered without its age"


def test_no_usage_row_when_there_is_nothing_to_show(paths, make_app):
    """Right after a switch the cache is cleared on purpose."""
    from helpers import make_claude_json, make_live_login, make_profile

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    cfg = paths.claude_json.read_text()
    import json as _json
    d = _json.loads(cfg); d.pop("cachedUsageUtilization", None)
    paths.claude_json.write_text(_json.dumps(d))
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    text = " ".join(_buttons(app))
    assert "session" not in text and "week" not in text



def _bar_fills(app):
    """Every rendered bar as (colour, fraction), in card order."""
    out = []
    for w in _all_widgets(app):
        if not isinstance(w, tk.Frame):
            continue
        try:
            info = w.place_info()
        except tk.TclError:
            continue
        if info and info.get("relwidth"):
            out.append((str(w.cget("bg")), float(info["relwidth"])))
    return out


def test_bars_go_red_at_eighty_percent(paths, make_app):
    """Matches the extension's own meter, so the two never disagree."""
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import switcher

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com",
                     extra={"cachedUsageUtilization":
                            _usage_blob(43, 89, switcher.now_ms())})
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    fills = _bar_fills(app)
    assert len(fills) == 2, f"expected two bars, got {len(fills)}"
    assert fills[0][0] == app.theme["accent"], "43% should not be red"
    assert fills[1][0] == app.theme["chip_gone_fg"], "89% should be red"


def test_a_bar_never_overflows_its_track(paths, make_app):
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import switcher

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com",
                     extra={"cachedUsageUtilization":
                            _usage_blob(140, 100, switcher.now_ms())})
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    for _colour, fraction in _bar_fills(app):
        assert fraction <= 1.0, "over-quota bar drew past its track"


def test_bars_span_the_card_below_the_email(paths, make_app):
    """Full-width rows, so they line up across cards whatever the name length."""
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import switcher

    make_profile(paths, "A", email="a@example.com", active=True)
    make_claude_json(paths, email="a@example.com",
                     extra={"cachedUsageUtilization":
                            _usage_blob(10, 20, switcher.now_ms())})
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    email = [w for w in _all_widgets(app) if isinstance(w, tk.Label)
             and "a@example.com" in str(w.cget("text"))][-1]
    tracks = [w for w in _all_widgets(app) if isinstance(w, tk.Frame)
              and str(w.cget("bg")) == app.theme["border"]
              and w.winfo_width() > 100]
    assert tracks, "no full-width track found"
    assert tracks[0].winfo_rooty() > email.winfo_rooty(), "bars are not below the email"
    assert tracks[0].winfo_width() > email.winfo_width(), "track is not spanning the card"


def test_an_account_with_no_figures_says_why(paths, make_app):
    """Blank space reads as a broken widget; this is what the reporter saw."""
    from helpers import make_claude_json, make_live_login, make_profile
    import json as _json

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    d = _json.loads(paths.claude_json.read_text())
    d.pop("cachedUsageUtilization", None)
    paths.claude_json.write_text(_json.dumps(d))
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    text = " ".join(_buttons(app))
    assert "usage appears once you run Claude" in text


def test_switch_sits_left_of_the_remove_button(paths, make_app):
    from helpers import make_claude_json, make_live_login, make_profile

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Other", email="other@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    pos = {}
    for w in _all_widgets(app):
        try:
            label = str(w.cget("text"))
        except tk.TclError:
            continue
        if label in ("Switch", "✕"):
            pos[label] = w.winfo_rootx()
    assert pos["Switch"] < pos["✕"], "expected [Switch][✕]"


def test_refresh_button_only_reads(paths, make_app):
    """It must be safe to press at any time: no switch, no credential write,
    nothing a running Claude Code session would notice."""
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import state

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_profile(paths, "Other", email="other@example.com")
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    before_live = paths.live_credentials.read_bytes()
    before_cfg = paths.claude_json.read_bytes()
    before_marker = state.read_active(paths)

    app.refresh()
    app.update()

    assert paths.live_credentials.read_bytes() == before_live
    assert paths.claude_json.read_bytes() == before_cfg
    assert state.read_active(paths) == before_marker


def test_the_info_icon_raises_its_tooltip(paths, make_app):
    """The row no longer reacts, so the icon must."""
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import gui, switcher

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com",
                     extra={"cachedUsageUtilization":
                            _usage_blob(40, 90, switcher.now_ms())})
    make_live_login(paths)
    app = make_app(paths)
    app.update()

    icon = [w for w in _all_widgets(app)
            if isinstance(w, tk.Label) and str(w.cget("text")) == app.glyph["info"]][0]
    icon.event_generate("<Enter>")
    app.update_idletasks()
    assert gui.Tooltip._open, "hovering the info icon showed no tooltip"
    gui.Tooltip.hide_all()


def test_the_window_never_grows_past_the_screen(paths, make_app, monkeypatch):
    """No resize handle, so a footer pushed off the bottom takes Eject and
    Add Account with it and cannot be recovered.

    The cap is a fraction of screen height, so it is forced small here rather
    than depending on whatever display the suite happens to run on.
    """
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import gui

    monkeypatch.setattr(gui, "MAX_HEIGHT_FRACTION", 0.12)

    for i in range(12):
        make_profile(paths, f"Account{i}", email=f"a{i}@example.com",
                     active=(i == 0))
    make_claude_json(paths, email="a0@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    assert app._scrollbar.winfo_ismapped(), "no scrollbar despite overflowing"
    assert app.winfo_reqheight() < 12 * 140, \
        "window grew with every profile instead of capping"


def test_no_scrollbar_when_everything_fits(paths, make_app):
    from helpers import make_claude_json, make_live_login, make_profile

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    assert not app._scrollbar.winfo_ismapped(), "scrollbar shown unnecessarily"


def test_the_footer_stays_reachable_with_many_profiles(paths, make_app,
                                                       monkeypatch):
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import gui

    monkeypatch.setattr(gui, "MAX_HEIGHT_FRACTION", 0.12)

    for i in range(12):
        make_profile(paths, f"Account{i}", email=f"a{i}@example.com",
                     active=(i == 0))
    make_claude_json(paths, email="a0@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    def label_of(w):
        try:
            return str(w.cget("text"))
        except tk.TclError:
            return ""

    eject = [w for w in _all_widgets(app) if label_of(w) == "Eject"]
    assert eject, "Eject button missing"
    assert eject[0].winfo_rooty() < app.winfo_rooty() + app.winfo_height(), \
        "footer is off the bottom of the window"


def test_nothing_is_stranded_in_a_column(paths, make_app):
    """The card list was packed side='left' and the footer side='bottom',
    so the footer claimed a right-hand slab and the cards were squeezed into
    a narrow column with 677px of dead space beside them."""
    from helpers import make_claude_json, make_live_login, make_profile

    for i in range(3):
        make_profile(paths, f"Account{i}", email=f"a{i}@example.com",
                     active=(i == 0))
    make_claude_json(paths, email="a0@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    width = app.winfo_width()
    for child in app.winfo_children():
        try:
            child.pack_info()
        except tk.TclError:
            continue          # the scrollbar, hidden until needed
        assert child.winfo_width() == width, (
            f"{type(child).__name__} is {child.winfo_width()}px in a "
            f"{width}px window — something is stranded beside it")


def test_cards_span_the_window(paths, make_app):
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import theme

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    cards = [w for w in app.rows.winfo_children() if isinstance(w, tk.Frame)]
    assert cards, "no card rendered"
    # full width less the list's own horizontal padding
    assert cards[0].winfo_width() >= app.winfo_width() - 3 * theme.GAP_L


def test_the_window_is_not_squat_with_one_profile(paths, make_app):
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import theme

    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_login(paths)

    app = make_app(paths)
    app.update()

    assert app.winfo_height() >= theme.MIN_HEIGHT


def _usage_app(paths, make_app, session=60, week=8, fetched_ago_ms=0):
    from helpers import make_claude_json, make_live_login, make_profile
    from shambles import switcher
    make_profile(paths, "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": _usage_blob(
            session, week, switcher.now_ms() - fetched_ago_ms)})
    make_live_login(paths)
    app = make_app(paths)
    app.update()
    return app


def test_each_usage_row_ends_in_an_info_icon(paths, make_app):
    from shambles import gui
    app = _usage_app(paths, make_app)
    icons = [w for w in _all_widgets(app)
             if isinstance(w, tk.Label) and str(w.cget("text")) == app.glyph["info"]]
    assert len(icons) == 2, f"expected one icon per bar, got {len(icons)}"


def test_only_the_icon_carries_the_tooltip(paths, make_app):
    """Hovering the label, the bar or the percentage should do nothing — the
    whole row reacting was too eager."""
    from shambles import gui
    app = _usage_app(paths, make_app)

    icon = [w for w in _all_widgets(app)
            if isinstance(w, tk.Label) and str(w.cget("text")) == app.glyph["info"]][0]
    row = icon.master
    assert icon.bind("<Enter>"), "the icon has no tooltip"
    for sibling in row.winfo_children():
        if sibling is icon:
            continue
        assert not sibling.bind("<Enter>"), \
            f"{sibling.cget('text') if isinstance(sibling, tk.Label) else sibling} still reacts"
    assert not row.bind("<Enter>"), "the row itself still reacts"


def test_only_one_tooltip_is_ever_open(paths, make_app):
    """The screenshot showed the expiry chip's tooltip and a usage tooltip
    overlapping each other."""
    from shambles import gui
    app = _usage_app(paths, make_app)

    hoverable = [w for w in _all_widgets(app) if w.bind("<Enter>")]
    assert len(hoverable) >= 2
    for widget in hoverable[:4]:
        widget.event_generate("<Enter>")
        app.update_idletasks()
        assert len(gui.Tooltip._open) <= 1, "more than one tooltip on screen"
    gui.Tooltip.hide_all()


def test_the_active_account_is_not_told_it_is_signed_out(paths, make_app):
    """An hour-old figure on the account you are signed in as is just an
    unrefreshed number, not evidence you left."""
    from shambles import gui
    app = _usage_app(paths, make_app, fetched_ago_ms=4 * 3_600_000)

    icon = [w for w in _all_widgets(app)
            if isinstance(w, tk.Label) and str(w.cget("text")) == app.glyph["info"]][0]
    icon.event_generate("<Enter>")
    app.update_idletasks()
    tip = list(gui.Tooltip._open)[0]
    text = tip.text
    assert "not been signed in since" not in text, text
    gui.Tooltip.hide_all()
