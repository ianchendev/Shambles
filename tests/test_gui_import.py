import tkinter as tk
from tkinter import ttk

import pytest

from conftest import posix_only
from helpers import (DAY_MS, NOW, make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile, make_v1_profile)
from shambles import gui, profiles, providers, state


@pytest.fixture
def claude():
    return providers.load("claude")


@pytest.fixture
def codex():
    return providers.load("codex")


def _all_text(widget):
    """Every string rendered anywhere under a widget.

    Canvas items are included: the empty-slot placeholder draws its label as a
    canvas item rather than as a Label, so a walk that only read ``-text``
    options would report an empty group as blank.
    """
    found = []
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except Exception:
            pass
        if isinstance(child, tk.Canvas):
            for item in child.find_all():
                try:
                    found.append(str(child.itemcget(item, "text")))
                except tk.TclError:
                    pass  # a rectangle has no text
        # append, not extend: _all_text returns a string, and extending a list
        # with one splits it into individual characters.
        found.append(_all_text(child))
    return " ".join(found)


def _labels(widget):
    """Every ``tk.Label`` under ``widget``, depth-first."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            found.append(child)
        found.extend(_labels(child))
    return found


def _buttons(widget):
    """Every ``ttk.Button`` under ``widget``, depth-first."""
    found = []
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            found.append(child)
        found.extend(_buttons(child))
    return found


# -- the heading, without a display ------------------------------------

def test_the_heading_names_the_active_account(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    text = gui.group_heading(claude, state.inspect(paths, claude, platform="linux"))

    assert "Claude Code" in text and "Work" in text and "w@example.com" in text


def test_the_heading_surfaces_drift(paths, claude):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="other@example.com")

    text = gui.group_heading(claude, state.inspect(paths, claude, platform="linux"))

    assert "⚠" in text and "other@example.com" in text


def test_the_heading_of_an_empty_provider_says_so(paths, codex):
    text = gui.group_heading(codex, state.inspect(paths, codex, platform="linux"))
    assert "Codex" in text
    assert "No accounts saved" in text


# -- the window --------------------------------------------------------

def test_the_window_renders_both_providers(paths, make_app):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)
    make_live_codex_login(paths, email="c@example.com")

    app = make_app(paths)
    app.refresh()

    rendered = _all_text(app.rows)
    assert "Work" in rendered and "Side" in rendered


def test_a_healthy_active_card_has_no_active_label_or_countdown(paths, make_app):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True,
                 refresh_expires_ms=NOW + 30 * DAY_MS)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.refresh()
    text = _all_text(app.rows)

    assert "Work" in text and "w@example.com" in text
    assert "ACTIVE" not in text
    assert "30d" not in text
    assert "soon" not in text
    assert "needs login" not in text


def test_a_closed_card_shows_needs_login_without_a_warning_glyph(paths, make_app):
    make_profile(paths, "claude", "Old", email="o@example.com",
                 refresh_expires_ms=NOW - 3 * DAY_MS)

    app = make_app(paths)
    app.refresh()
    text = _all_text(app.rows)

    assert "needs login" in text
    # Group headers may still contain ⚠ for drift/unknown; the card badge was
    # a Label whose entire text was the glyph.
    assert not any(str(c.cget("text")).strip() == "⚠" for c in _labels(app.rows))


def test_chip_tooltip_uses_warning_prose_when_there_is_no_expiry(paths, claude):
    make_profile(paths, "claude", "Empty", token=False)
    found = profiles.discover(paths, claude, None, NOW, platform="linux")[0]
    tip = gui.chip_tooltip(found)
    assert "No token here yet" in tip


def test_saved_profiles_stay_visible_when_the_vendor_is_missing(paths, make_app):
    """Switching copies a file and runs nothing, so it still works without the
    vendor binary. Hiding the accounts would take away something usable."""
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_live_codex_login(paths, email="c@example.com")

    app = make_app(paths)
    app.refresh()

    rendered = _all_text(app.rows)
    assert "Side" in rendered
    assert "can't add accounts" in rendered


def test_missing_vendor_banner_starts_collapsed(paths, make_app):
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_live_codex_login(paths, email="c@example.com")

    app = make_app(paths)
    app.refresh()
    text = _all_text(app.rows)

    assert "not on PATH — can't add accounts" in text
    assert "Details" in text
    # Detail copy exists on an unpacked Label; it must not be mapped yet.
    assert not any(
        "Switching between accounts you already saved still works" in str(lab.cget("text"))
        and lab.winfo_ismapped()
        for lab in _labels(app.rows)
    )


def test_missing_vendor_banner_expands_on_details(paths, make_app):
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_live_codex_login(paths, email="c@example.com")

    app = make_app(paths)
    app.refresh()

    details = next(b for b in _buttons(app.rows) if b.cget("text") == "Details")
    details.invoke()
    app.update()

    text = _all_text(app.rows)
    assert "Switching between accounts you already saved still works" in text
    assert "Hide" in text


def test_add_account_dialog_omits_shared_history_paragraph(paths, make_app, monkeypatch):
    # Patch only this dialog class — a blanket Toplevel.wait_window stub
    # would also silence messagebox and hang later tests waiting on it.
    monkeypatch.setattr(gui.AddAccountDialog, "wait_window",
                        lambda self, *_a, **_k: None)
    monkeypatch.setattr(gui.AddAccountDialog, "grab_set", lambda self: None)

    app = make_app(paths)
    dlg = gui.AddAccountDialog(app, app.add_account_options(), app.theme)
    try:
        text = _all_text(dlg)
        assert "Browser will open to sign in" in text
        assert "session history" not in text
        assert "plugins" not in text
    finally:
        dlg.destroy()


def test_the_window_migrates_a_v1_store_on_open(paths, make_app, monkeypatch):
    """The repair is automatic and unprompted, like the v1.0 history merge:
    there is no version of the old layout anyone wants."""
    monkeypatch.setattr(gui.messagebox, "showinfo", lambda *a, **k: None)
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    make_v1_profile(paths, "Work", email="w@example.com", active=True)

    make_app(paths)

    assert paths.credentials("claude", "Work").is_file()
    assert state.read_active(paths, "claude") == "Work"


def test_an_empty_machine_renders_without_error(paths, make_app):
    app = make_app(paths)
    app.refresh()
    assert _all_text(app.rows).strip()


# -- the empty-slot placeholder ----------------------------------------

def _placeholders(app):
    return [w for w in app.rows.winfo_children() if isinstance(w, tk.Canvas)]


def test_a_provider_with_no_accounts_gets_a_dotted_placeholder(paths, make_app,
                                                              fake_vendor):
    """An empty group should read as a space something goes in, not as a
    section that failed to load.

    ``fake_vendor`` is taken without creating anything: it pins PATH to an
    empty directory, so what the developer happens to have installed cannot
    change the result.
    """
    app = make_app(paths)
    app.refresh()
    app.update()

    boxes = _placeholders(app)
    assert len(boxes) == 2, "one placeholder per provider, both empty here"

    outlines = [item for box in boxes for item in box.find_all()
                if box.type(item) == "rectangle"]
    assert outlines, "placeholder drew no box"
    for box in boxes:
        for item in box.find_all():
            if box.type(item) == "rectangle":
                assert box.itemcget(item, "dash"), "the box must be dashed"


def test_the_placeholder_disappears_once_an_account_exists(paths, make_app,
                                                          fake_vendor):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.refresh()
    app.update()

    rendered = _all_text(app.rows)
    assert "Add a Claude Code account" not in rendered, "the filled group kept its slot"
    assert len(_placeholders(app)) == 1, "only the empty Codex group keeps one"


@posix_only
def test_an_installed_provider_invites_adding_an_account(paths, make_app,
                                                         fake_vendor):
    fake_vendor("claude")
    fake_vendor("codex")
    app = make_app(paths)
    app.refresh()
    app.update()

    rendered = _all_text(app.rows)
    assert "Add a Claude Code account" in rendered
    assert "Add a Codex account" in rendered
    for box in _placeholders(app):
        assert box.cget("cursor") == "hand2", "an addable slot should look clickable"


def test_a_missing_vendor_placeholder_says_so_and_is_not_clickable(paths, make_app,
                                                                  fake_vendor):
    """Add Account disables a provider whose CLI is absent, so an inviting box
    would lead somewhere that refuses."""
    app = make_app(paths)
    app.refresh()
    app.update()

    rendered = _all_text(app.rows)
    assert "not on your PATH" in rendered
    for box in _placeholders(app):
        assert box.cget("cursor") != "hand2"


def test_clicking_the_placeholder_preselects_that_provider(paths, make_app,
                                                           monkeypatch):
    """The only thing anyone wants from an empty slot."""
    seen = {}

    class FakeDialog:
        def __init__(self, parent, options, theme, preselect=None):
            seen["preselect"] = preselect
            self.result = None

    monkeypatch.setattr(gui, "AddAccountDialog", FakeDialog)
    app = make_app(paths)
    app.on_add(providers.load("codex"))

    assert seen["preselect"] == "codex"


def test_the_footer_button_preselects_nothing(paths, make_app, monkeypatch):
    seen = {}

    class FakeDialog:
        def __init__(self, parent, options, theme, preselect=None):
            seen["preselect"] = preselect
            self.result = None

    monkeypatch.setattr(gui, "AddAccountDialog", FakeDialog)
    app = make_app(paths)
    app.on_add()

    assert seen["preselect"] is None


# -- add account -------------------------------------------------------

def test_add_offers_every_provider_with_its_availability(paths, make_app):
    app = make_app(paths)
    options = app.add_account_options()
    assert {p.id for p, _ok in options} == {"claude", "codex"}
    assert all(isinstance(ok, bool) for _p, ok in options)


def test_stash_after_login_files_what_the_vendor_wrote(paths, make_app):
    """The step that turns a vendor login into a Shambles profile."""
    codex = providers.load("codex")
    app = make_app(paths)
    paths.ensure_profile("codex", "Fresh")
    make_live_codex_login(paths, email="new@example.com")

    assert app.stash_after_login(codex, "Fresh") is True
    assert paths.credentials("codex", "Fresh").is_file()


def test_stash_after_login_reports_false_when_nothing_was_written(paths, make_app):
    """A cancelled or failed login leaves the profile empty, and the caller
    must be able to tell."""
    codex = providers.load("codex")
    app = make_app(paths)
    paths.ensure_profile("codex", "Fresh")

    assert app.stash_after_login(codex, "Fresh") is False
    assert not paths.credentials("codex", "Fresh").exists()


def test_save_is_not_offered_when_there_is_nothing_to_save(paths, make_app):
    """A control whose only outcome is a refusal is worse than no control."""
    app = make_app(paths)
    app.refresh()
    assert "Save current login" not in _all_text(app.rows)


def test_save_is_offered_when_a_login_exists_outside_any_profile(paths, make_app):
    """The state this button is for: signed in, but Shambles does not know it."""
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.refresh()

    assert "Save current login" in _all_text(app.rows)


def test_save_is_offered_for_a_credential_with_no_readable_identity(paths, make_app):
    """~/.claude.json may not exist yet. The token is still worth saving, so
    this must not key off the displayed email."""
    make_live_claude_login(paths)

    app = make_app(paths)
    app.refresh()

    assert "Save current login" in _all_text(app.rows)


# ---- restored after the multi-provider merge disconnected them ----------

def _every_widget(widget, found=None):
    found = [] if found is None else found
    for child in widget.winfo_children():
        found.append(child)
        _every_widget(child, found)
    return found


def _label_texts(app):
    out = []
    for w in _every_widget(app):
        try:
            out.append(str(w.cget("text")))
        except tk.TclError:
            pass
    return out


def test_no_control_renders_as_a_missing_glyph(paths, make_app):
    """Ubuntu has no U+FF0B, so a hardcoded ＋ draws a box. Every decorative
    glyph must be one the font can actually draw."""
    from shambles import theme

    app = make_app(paths)
    app.update()

    tofu = app.theme.chip.measure(theme.MISSING_PROBE)
    for text in _label_texts(app):
        for ch in text:
            if ch.isascii() or ch.isspace():
                continue
            assert app.theme.chip.measure(ch) != tofu, (
                f"{ch!r} (U+{ord(ch):04X}) in {text!r} renders as a box")


def test_a_long_profile_name_does_not_stretch_the_window(paths, make_app):
    from helpers import make_claude_json, make_live_claude_login, make_profile
    from shambles import theme

    make_profile(paths, "claude", "A" * 60, email="long@example.com",
                 active=True)
    make_claude_json(paths, email="long@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    assert app.winfo_reqwidth() <= theme.WINDOW_WIDTH, (
        f"a 60-character name took the window to {app.winfo_reqwidth()}px")


def _usage_blob(session=None, week=None, fetched=None, uuid="uuid-a"):
    limits = []
    if session is not None:
        limits.append({"kind": "session", "percent": session,
                       "severity": "normal"})
    if week is not None:
        limits.append({"kind": "weekly_all", "percent": week,
                       "severity": "warning"})
    return {"fetchedAtMs": fetched, "accountUuid": uuid,
            "utilization": {"limits": limits}}


def _bar_fills(app):
    out = []
    for w in _every_widget(app):
        if not isinstance(w, tk.Frame):
            continue
        try:
            info = w.place_info()
        except tk.TclError:
            continue
        if info and info.get("relwidth"):
            out.append((str(w.cget("bg")), float(info["relwidth"])))
    return out


def test_the_active_claude_card_draws_usage_bars(paths, make_app):
    from helpers import (make_claude_json, make_live_claude_login, make_profile)
    from shambles import switcher

    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": _usage_blob(43, 89, switcher.now_ms())})
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    text = _label_texts(app)
    assert "session" in text and "43%" in text
    assert "week" in text and "89%" in text


def test_a_bar_goes_red_at_eighty_percent(paths, make_app):
    from helpers import (make_claude_json, make_live_claude_login, make_profile)
    from shambles import switcher

    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": _usage_blob(43, 89, switcher.now_ms())})
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    fills = _bar_fills(app)
    assert len(fills) == 2, f"expected two bars, got {len(fills)}"
    assert fills[0][0] == app.theme["accent"], "43% should not be red"
    assert fills[1][0] == app.theme["chip_gone_fg"], "89% should be red"


def test_a_provider_publishing_no_usage_shows_no_bars(paths, make_app):
    """Codex exposes nothing readable; that is a supported state, not a gap."""
    from helpers import make_profile

    make_profile(paths, "codex", "Personal", email="me@example.com", active=True)

    app = make_app(paths)
    app.update()

    assert not _bar_fills(app)


def test_the_active_account_records_its_own_figures(paths, make_app):
    """Without this a profile only learns its usage when switched away from,
    so the account in use is the one guaranteed to render blank."""
    from helpers import (make_claude_json, make_live_claude_login, make_profile,
                         write_json, account as acct)
    from shambles import configjson, switcher

    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    write_json(paths.account("claude", "Work"),
               {"oauthAccount": acct("work@example.com", uuid="uuid-a")})
    make_claude_json(paths, email="work@example.com", extra={
        "cachedUsageUtilization": _usage_blob(30, 40, switcher.now_ms())})
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    stashed = configjson.load(paths.account("claude", "Work")).get("usage")
    assert stashed, "the active account's figures were not recorded"


def test_switch_sits_left_of_the_remove_control(paths, make_app):
    from helpers import make_claude_json, make_live_claude_login, make_profile

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Other", email="o@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    pos = {}
    for w in _every_widget(app):
        try:
            label = str(w.cget("text"))
        except tk.TclError:
            continue
        if label in ("Switch", app.glyph["remove"]):
            pos[label] = w.winfo_rootx()
    assert pos["Switch"] < pos[app.glyph["remove"]], "expected [Switch][remove]"


def test_the_window_never_grows_past_the_screen(paths, make_app, monkeypatch):
    """Two provider groups make this far easier to hit than one, and there is
    no resize handle to recover a footer pushed off the bottom."""
    from helpers import make_claude_json, make_live_claude_login, make_profile
    from shambles import gui

    monkeypatch.setattr(gui, "MAX_HEIGHT_FRACTION", 0.12)
    for i in range(10):
        make_profile(paths, "claude", f"Account{i}", email=f"a{i}@example.com",
                     active=(i == 0))
    make_claude_json(paths, email="a0@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    assert app._scrollbar.winfo_ismapped(), "no scrollbar despite overflowing"
    assert app.winfo_reqheight() < 10 * 150, "window grew with every profile"


def test_no_scrollbar_when_everything_fits(paths, make_app):
    from helpers import make_claude_json, make_live_claude_login, make_profile

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    assert not app._scrollbar.winfo_ismapped(), "scrollbar shown unnecessarily"


def test_nothing_is_stranded_beside_the_card_list(paths, make_app):
    from helpers import make_claude_json, make_live_claude_login, make_profile

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    width = app.winfo_width()
    for child in app.winfo_children():
        try:
            child.pack_info()
        except tk.TclError:
            continue
        assert child.winfo_width() == width, (
            f"{type(child).__name__} is {child.winfo_width()}px in a "
            f"{width}px window")
