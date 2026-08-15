import time
import tkinter as tk
from tkinter import ttk

import pytest

from conftest import posix_only
from helpers import (DAY_MS, NOW, make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile, make_v1_profile)
from shambles import gui, motion, profiles, providers, state, widgets


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
    """The dashed empty slots.

    Profile cards are canvases too -- they have to be, since Tk will not round
    a frame -- so the filter names what a placeholder is rather than matching
    every canvas in the row list.
    """
    return [w for w in app.rows.winfo_children()
            if isinstance(w, tk.Canvas) and not isinstance(w, widgets.Card)]


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

    # The slot is rounded to match the cards, so its outline is a smoothed
    # polygon rather than a rectangle. What matters is that it is dashed --
    # that is what makes it read as a space to fill rather than as a card.
    outlines = [(box, item) for box in boxes for item in box.find_all()
                if box.type(item) in ("rectangle", "polygon")]
    assert outlines, "placeholder drew no box"
    for box, item in outlines:
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


def test_no_scrollbar_when_everything_fits(paths, make_app, monkeypatch):
    """Whether a given screen fits a given amount of content depends on the
    font and the DPI, so asserting "no scrollbar" against the real display
    tests the machine rather than the code -- it passed on a desktop and
    failed on CI purely on Segoe UI's metrics.

    Giving the cap enough headroom to swallow anything makes the room
    unquestionably sufficient, so what is left under test is the actual rule:
    content that fits does not raise a scrollbar.
    """
    from helpers import make_claude_json, make_live_claude_login, make_profile
    from shambles import gui

    monkeypatch.setattr(gui, "MAX_HEIGHT_FRACTION", 4.0)

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


def test_each_provider_group_names_its_own_active_account(paths, make_app):
    """One window-wide header cannot represent two providers, each with its
    own active account; the treatment repeats per group instead."""
    from helpers import (make_claude_json, make_live_claude_login,
                         make_live_codex_login, make_profile)

    make_profile(paths, "claude", "Work", email="work@example.com", active=True)
    make_profile(paths, "codex", "Personal", email="me@example.com", active=True)
    make_claude_json(paths, email="work@example.com")
    make_live_claude_login(paths)
    make_live_codex_login(paths)

    app = make_app(paths)
    app.update()

    text = _label_texts(app)
    assert "CLAUDE CODE" in text, "provider name missing from its group"
    assert "CODEX" in text
    assert "Work" in text and "Personal" in text


def test_a_provider_with_no_active_account_says_so(paths, make_app):
    app = make_app(paths)
    app.update()
    assert "Not signed in" in _label_texts(app)


def test_a_very_long_active_name_does_not_stretch_the_header(paths, make_app):
    from helpers import make_claude_json, make_live_claude_login, make_profile
    from shambles import theme

    make_profile(paths, "claude", "Q" * 70, email="q@example.com", active=True)
    make_claude_json(paths, email="q@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    assert app.winfo_reqwidth() <= theme.WINDOW_WIDTH


def test_the_height_cap_measures_chrome_rather_than_assuming_it(paths, make_app):
    """A hardcoded allowance is wrong by however much the header and footer
    differ from it, and they differ by font, platform and how many warnings
    are showing. Guessing 200px where the real figure was 78 cost the list
    122px and put a scrollbar on a single-profile window."""
    from helpers import make_claude_json, make_live_claude_login, make_profile
    from shambles import gui

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    chrome = sum(c.winfo_reqheight() for c in app.winfo_children()
                 if c is not app._body)
    cap = int(app.winfo_screenheight() * gui.MAX_HEIGHT_FRACTION)
    # the viewport is given whatever is left, never a fixed guess
    assert app._viewport.winfo_reqheight() <= cap - chrome


def test_the_footer_offers_a_refresh(paths, make_app):
    """The usage tooltip tells you to press it, so it has to exist."""
    app = make_app(paths)
    app.update()
    assert app.glyph["refresh"] in _label_texts(app), "no refresh control"


def test_refresh_only_reads(paths, make_app):
    """Safe to press at any time: no switch, no credential written, nothing a
    running session would notice."""
    from helpers import make_claude_json, make_live_claude_login, make_profile
    from shambles import state
    from shambles.providers import all_providers

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Other", email="o@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    claude = [p for p in all_providers() if p.id == "claude"][0]
    before = (paths.claude_json.read_bytes(),
              paths.credentials("claude", "Other").read_bytes(),
              state.read_active(paths, "claude"))

    app.refresh()
    app.update()

    assert paths.claude_json.read_bytes() == before[0]
    assert paths.credentials("claude", "Other").read_bytes() == before[1]
    assert state.read_active(paths, "claude") == before[2]


def test_a_healthy_account_still_reveals_its_expiry_on_hover(paths, make_app):
    """DD-1 keeps durations off the face but says the raw timestamps stay
    available in tooltips. With no chip rendered for a healthy account there
    was nothing to hover, so the number was unreachable."""
    from helpers import make_claude_json, make_live_claude_login, make_profile

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    # The group header shows the active account's name too, and that copy
    # carries no tooltip -- take the one on the card.
    names = [w for w in _every_widget(app)
             if isinstance(w, tk.Label) and str(w.cget("text")) == "Work"
             and w.bind("<Enter>")]
    assert names, "profile name on the card is not hoverable"
    names[0].event_generate("<Enter>")
    app.update_idletasks()
    assert gui.Tooltip._open, "the name raises no tooltip"
    text = list(gui.Tooltip._open)[0].text
    assert "expires" in text.lower(), f"no expiry in the hover: {text!r}"
    gui.Tooltip.hide_all()


# ======================================================================
# The drawn card, and the motion on it
# ======================================================================

def _cards(app):
    return [w for w in _every_widget(app) if isinstance(w, widgets.Card)]


def _named_card(app, name):
    """The card whose profile name label says ``name``."""
    for card in _cards(app):
        for label in _labels(card):
            if str(label.cget("text")) == name:
                return card
    raise AssertionError(f"no card for {name!r}")


def _two_claude_profiles(paths):
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Other", email="o@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)


def _pump(app, until, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.update()
        if until():
            return True
        time.sleep(0.01)
    return False


def test_a_profile_renders_as_a_rounded_card(paths, make_app):
    """Tk frames are square at every corner, so a card with a radius has to
    be a smoothed polygon on a canvas rather than a styled frame."""
    _two_claude_profiles(paths)

    app = make_app(paths)
    app.update()

    cards = _cards(app)
    assert len(cards) == 2, f"expected two cards, got {len(cards)}"
    for card in cards:
        face = list(zip(*[iter(card.coords(card.surface))] * 2))
        assert len(face) > 8, "the card face was never drawn at a real size"
        # A square corner sits exactly on the bounding box; a rounded one
        # cuts inside it.
        x1 = min(x for x, _y in face)
        y1 = min(y for _x, y in face)
        assert (x1, y1) not in face, "the card has square corners"


def test_the_card_keeps_its_name_and_address_readable(paths, make_app):
    """Moving the content onto a canvas must not lose it."""
    _two_claude_profiles(paths)

    app = make_app(paths)
    app.update()

    text = _all_text(app.rows)
    assert "Work" in text and "w@example.com" in text
    assert "Other" in text and "o@example.com" in text


def test_the_active_card_wears_the_accent_spine(paths, make_app):
    _two_claude_profiles(paths)

    app = make_app(paths)
    app.update()

    active = _named_card(app, "Work")
    idle = _named_card(app, "Other")
    assert active.itemcget(active.spine, "fill") == app.theme["border_active"]
    assert idle.itemcget(idle.spine, "fill") == app.theme["border"]


def test_a_card_grows_taller_when_it_draws_usage_bars(paths, make_app):
    """The scroll region is computed from the row heights, so a canvas that
    ignores its content puts a scrollbar on a window that does not need one."""
    from shambles import switcher

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com", extra={
        "cachedUsageUtilization": _usage_blob(43, 89, switcher.now_ms())})
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    card = _named_card(app, "Work")
    assert card.winfo_reqheight() >= card.body.winfo_reqheight()
    assert card.winfo_reqheight() > 60, "the card collapsed to a default height"


def test_hovering_a_card_washes_it(paths, make_app, monkeypatch):
    """Motion off so the end state lands at once; the tween itself is covered
    in test_motion."""
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    _two_claude_profiles(paths)

    app = make_app(paths)
    app.update()

    card = _named_card(app, "Other")

    # Drive it out of hover first. On a CI runner the pointer can already be
    # sitting over the window, in which case the card is legitimately washed
    # before the test touches it -- and then the assertion below is about
    # where the mouse happened to be rather than about the transition.
    card.event_generate("<Leave>", rootx=-200, rooty=-200)
    app.update()
    assert card.itemcget(card.surface, "fill") == app.theme["card"]

    card.event_generate("<Enter>")
    app.update()
    assert card.itemcget(card.surface, "fill") == app.theme["card_hover"]


def test_a_washed_card_repaints_the_text_on_it(paths, make_app, monkeypatch):
    """Tk has no colour inheritance -- every label sets its own background --
    so a surface that washes alone leaves white blocks behind the words."""
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    _two_claude_profiles(paths)

    app = make_app(paths)
    app.update()

    card = _named_card(app, "Other")
    card.event_generate("<Enter>")
    app.update()

    name = next(w for w in _labels(card) if str(w.cget("text")) == "Other")
    assert name.cget("bg") == app.theme["card_hover"]


def test_an_expiry_chip_keeps_its_own_colour_under_the_pointer(paths, make_app,
                                                               monkeypatch):
    """The chip background is the warning. Washing it with the card would
    erase the difference between 'closing soon' and 'fine'."""
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    from shambles import switcher

    # Against the real clock, not the suite's fixed NOW: the card computes
    # its severity from switcher.now_ms(), so a fixed reference would decide
    # which chip renders by how far the calendar had moved since it was set.
    #
    # Half a day, not a whole number of them. days_left is math.floor()ed
    # against a *second*, later reading of the clock, so `now + N * DAY_MS`
    # lands on N or N-1 depending on how many milliseconds the window took to
    # build -- and Claude's warn_days is 1, so N=2 is right on the boundary.
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Soon", email="s@example.com",
                 refresh_expires_ms=switcher.now_ms() + DAY_MS // 2)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    card = _named_card(app, "Soon")
    card.event_generate("<Enter>")
    app.update()

    chips = [w for w in _every_widget(card) if isinstance(w, widgets.Pill)]
    assert chips, "no expiry chip rendered"
    for chip in chips:
        drawn = {chip.itemcget(i, "fill") for i in chip.find_all()
                 if chip.type(i) == "polygon"}
        assert app.theme["chip_soon_bg"] in drawn, "the chip washed away"


def test_an_expiry_chip_is_a_rounded_pill(paths, make_app):
    from shambles import switcher

    # Half a day: see the note above on days_left being floored against a
    # second reading of the clock.
    make_profile(paths, "claude", "Soon", email="s@example.com", active=True,
                 refresh_expires_ms=switcher.now_ms() + DAY_MS // 2)
    make_claude_json(paths, email="s@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    chips = [w for w in _every_widget(app) if isinstance(w, widgets.Pill)]
    assert chips, "no expiry chip rendered"
    # DD-1 keeps the duration itself off the card face; the chip says only
    # that the window is closing, and the date lives in its tooltip.
    assert "soon" in _all_text(app.rows), "the chip text did not survive the pill"
    for chip in chips:
        assert chip.radius == pytest.approx(chip.winfo_reqheight() / 2, abs=1)


# ---- the usage bars now grow ---------------------------------------------

def test_usage_bars_reach_their_real_width(paths, make_app, monkeypatch):
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    from shambles import switcher

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com", extra={
        "cachedUsageUtilization": _usage_blob(43, 89, switcher.now_ms())})
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    widths = [round(w, 2) for _colour, w in _bar_fills(app)]
    assert widths == [0.43, 0.89]


def test_usage_bars_grow_rather_than_appearing_full(paths, make_app):
    """The number you opened the window to check is the thing that moves."""
    from shambles import switcher

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com", extra={
        "cachedUsageUtilization": _usage_blob(43, 89, switcher.now_ms())})
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()
    early = [w for _colour, w in _bar_fills(app)]

    assert _pump(app, lambda: round(_bar_fills(app)[0][1], 2) == 0.43), (
        "the bar never reached its target width")
    late = [w for _colour, w in _bar_fills(app)]

    assert early[0] < late[0], "the bar was already full; nothing animated"


def test_the_bar_colours_are_left_exactly_as_they_were(paths, make_app,
                                                       monkeypatch):
    """Animating the width must not touch the palette: blue below the line,
    red above it, which is what the vendor's own meter does."""
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    from shambles import switcher

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com", extra={
        "cachedUsageUtilization": _usage_blob(43, 89, switcher.now_ms())})
    make_live_claude_login(paths)

    app = make_app(paths)
    app.update()

    colours = [c for c, _w in _bar_fills(app)]
    assert colours == [app.theme["accent"], app.theme["chip_gone_fg"]]


# ---- confirming a switch --------------------------------------------------

def test_switching_pulses_the_card_it_switched_to(paths, make_app, monkeypatch):
    """Today the one action this window exists for reports success by
    silently redrawing the list."""
    pulsed = []
    monkeypatch.setattr(widgets.Card, "pulse",
                        lambda self, flash: pulsed.append(self))
    _two_claude_profiles(paths)

    app = make_app(paths)
    app.update()
    claude = providers.load("claude")

    app.on_switch(claude, "Other")
    app.update()

    assert len(pulsed) == 1, f"expected one confirmation, got {len(pulsed)}"
    assert any(str(w.cget("text")) == "Other" for w in _labels(pulsed[0]))


def test_an_ordinary_refresh_pulses_nothing(paths, make_app, monkeypatch):
    """Motion confirms a change. Pressing refresh changes nothing."""
    pulsed = []
    monkeypatch.setattr(widgets.Card, "pulse",
                        lambda self, flash: pulsed.append(self))
    _two_claude_profiles(paths)

    app = make_app(paths)
    app.update()
    app.refresh()
    app.update()

    assert not pulsed


def test_a_failed_switch_does_not_leave_a_pulse_armed(paths, make_app,
                                                      monkeypatch):
    """The flag is set before the switch runs, so a switch that raises must
    not confirm itself on the next unrelated redraw."""
    pulsed = []
    monkeypatch.setattr(widgets.Card, "pulse",
                        lambda self, flash: pulsed.append(self))
    monkeypatch.setattr(gui.messagebox, "showerror", lambda *a, **k: None)
    _two_claude_profiles(paths)

    app = make_app(paths)
    app.update()
    claude = providers.load("claude")

    app.on_switch(claude, "NoSuchProfile")
    app.update()
    pulsed.clear()

    app.refresh()
    app.update()
    assert not pulsed, "a failed switch armed a confirmation for later"


# ---- the window itself ----------------------------------------------------

def test_the_window_never_stays_transparent(paths, make_app):
    """A fade that stalls leaves an invisible window and no way to guess why."""
    app = make_app(paths)

    assert _pump(app, lambda: float(app.attributes("-alpha")) == 1.0), (
        f"stuck at alpha {app.attributes('-alpha')}")


def test_with_motion_off_the_window_is_opaque_immediately(paths, make_app,
                                                          monkeypatch):
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    app = make_app(paths)
    app.update()
    assert float(app.attributes("-alpha")) == 1.0


# ---- an old figure on the account you are signed in as -------------------

def _stale_usage(paths, *, active_name, session, week, age_ms):
    """Give the live account a usage blob of a chosen age."""
    from shambles import switcher
    now = switcher.now_ms()
    make_claude_json(paths, email="w@example.com", extra={
        "cachedUsageUtilization": {
            "fetchedAtMs": now - age_ms,
            "accountUuid": "uuid-a",
            "utilization": {"limits": [
                {"kind": "session", "percent": session, "severity": "normal"},
                {"kind": "weekly_all", "percent": week, "severity": "normal"},
            ]},
        }})
    make_live_claude_login(paths)


def test_the_active_accounts_bars_keep_their_colour_when_the_figure_is_old(
        paths, make_app, monkeypatch):
    """An old figure on the account you are signed in as is still yours --
    nothing has refreshed it because you have not run a session for an hour.

    Greying it says 'do not trust this number', which is what the *inactive*
    case means, and the copy already draws that distinction: an idle active
    account gets IDLE_NOTE ("it refreshes as you work"), an inactive one gets
    STALE_NOTE ("the real figure may have moved on"). The colour has to make
    the same distinction.
    """
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    _stale_usage(paths, active_name="Work", session=56, week=18,
                 age_ms=2 * 60 * 60 * 1000)

    app = make_app(paths)
    app.update()

    colours = [c for c, _w in _bar_fills(app)]
    assert colours, "no bars rendered"
    assert app.theme["faint"] not in colours, "the active account was greyed out"
    assert colours == [app.theme["accent"], app.theme["accent"]]


def test_an_inactive_accounts_stale_bars_are_still_greyed(paths, make_app,
                                                          monkeypatch):
    """The other half of the rule. That account has not been signed in since
    the figure was taken, so it really may have moved on."""
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    from shambles import configjson, switcher

    now = switcher.now_ms()
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_profile(paths, "claude", "Other", email="o@example.com")
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    sidecar_path = paths.account("claude", "Other")
    sidecar = configjson.load(sidecar_path)
    sidecar["usage"] = {
        "fetchedAtMs": now - 6 * DAY_MS,
        "accountUuid": "uuid-a",
        "utilization": {"limits": [
            {"kind": "session", "percent": 56, "severity": "normal"}]},
    }
    configjson.write_atomic(sidecar_path, sidecar)

    app = make_app(paths)
    app.update()

    # Scoped to that card: the live account renders bars of its own from the
    # fixture's ~/.claude.json, and those are correctly *not* grey.
    idle = [c for c, _w in _bar_fills(_named_card(app, "Other"))]
    assert idle == [app.theme["faint"]], f"expected one grey bar, got {idle}"

    live = [c for c, _w in _bar_fills(_named_card(app, "Work"))]
    assert app.theme["faint"] not in live, "the live account was greyed too"


def test_a_fresh_bar_over_the_red_line_is_still_red(paths, make_app, monkeypatch):
    """The 80% rule has to survive the staleness change."""
    monkeypatch.setenv(motion.MOTION_ENV, "off")
    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    _stale_usage(paths, active_name="Work", session=43, week=89,
                 age_ms=3 * 60 * 60 * 1000)

    app = make_app(paths)
    app.update()

    colours = [c for c, _w in _bar_fills(app)]
    assert colours == [app.theme["accent"], app.theme["chip_gone_fg"]]


def test_a_screen_too_small_for_the_window_scrolls_it(paths, make_app,
                                                     monkeypatch):
    """The safety rule the cap exists for.

    The window cannot be resized, so on a display too short to hold it the
    viewport has to be capped and the overflow handed to a scrollbar. Without
    that the footer runs off the bottom and Eject and Add Account become
    unclickable with no way to reach them.

    Driven by squeezing the cap rather than by naming a screen height: the
    height a real display needs varies with the font, which is exactly the
    dependency that made the previous version of this pass locally and fail
    on CI.
    """
    from shambles import gui

    make_profile(paths, "claude", "Work", email="w@example.com", active=True)
    make_claude_json(paths, email="w@example.com")
    make_live_claude_login(paths)

    app = make_app(paths)
    monkeypatch.setattr(gui, "MAX_HEIGHT_FRACTION", 0.01)
    app.refresh()
    app.update()

    assert app._scrollbar.winfo_ismapped(), "no scrollbar on an overflowing window"
    assert app._viewport.winfo_reqheight() < app.rows.winfo_reqheight(), (
        "the viewport was not capped, so the footer is off the screen")
