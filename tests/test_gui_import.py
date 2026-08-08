import pytest

from helpers import (make_claude_json, make_live_claude_login,
                     make_live_codex_login, make_profile, make_v1_profile)
from shambles import gui, providers, state


@pytest.fixture
def claude():
    return providers.load("claude")


@pytest.fixture
def codex():
    return providers.load("codex")


def _all_text(widget):
    """Every string rendered anywhere under a widget."""
    found = []
    for child in widget.winfo_children():
        try:
            found.append(str(child.cget("text")))
        except Exception:
            pass
        # append, not extend: _all_text returns a string, and extending a list
        # with one splits it into individual characters.
        found.append(_all_text(child))
    return " ".join(found)


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


def test_saved_profiles_stay_visible_when_the_vendor_is_missing(paths, make_app):
    """Switching copies a file and runs nothing, so it still works without the
    vendor binary. Hiding the accounts would take away something usable."""
    make_profile(paths, "codex", "Side", email="c@example.com", active=True)
    make_live_codex_login(paths, email="c@example.com")

    app = make_app(paths)
    app.refresh()

    rendered = _all_text(app.rows)
    assert "Side" in rendered
    assert "not on your PATH" in rendered


def test_the_window_migrates_a_v1_store_on_open(paths, make_app):
    """The repair is automatic and unprompted, like the v1.0 history merge:
    there is no version of the old layout anyone wants."""
    make_v1_profile(paths, "Work", email="w@example.com", active=True)

    make_app(paths)

    assert paths.credentials("claude", "Work").is_file()
    assert state.read_active(paths, "claude") == "Work"


def test_an_empty_machine_renders_without_error(paths, make_app):
    app = make_app(paths)
    app.refresh()
    assert "No accounts yet." in _all_text(app.rows)


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
