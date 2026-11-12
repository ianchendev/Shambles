"""Pulling the sign-in URL out of what the vendor prints."""

from shambles import login


def test_finds_a_url_in_a_noisy_line():
    line = ("Open this URL in your browser: "
            "https://claude.ai/oauth/authorize?code_challenge=abc&state=xyz")
    assert login.find_url(line) == (
        "https://claude.ai/oauth/authorize?code_challenge=abc&state=xyz")


def test_finds_a_url_on_its_own_line():
    url = "https://auth.openai.com/authorize?x=1"
    assert login.find_url(f"  {url}  ") == url


def test_ignores_a_line_with_no_url():
    assert login.find_url("Waiting for the browser...") is None
    assert login.find_url("") is None


def test_takes_the_first_url_when_a_line_has_two():
    first = "https://a.example/one"
    assert login.find_url(f"{first} or https://b.example/two") == first


def test_strips_trailing_punctuation_that_is_not_part_of_the_url():
    assert login.find_url("Visit https://claude.ai/oauth?a=1.") == \
        "https://claude.ai/oauth?a=1"
    assert login.find_url("(https://claude.ai/oauth)") == \
        "https://claude.ai/oauth"


def test_only_http_schemes():
    assert login.find_url("file:///etc/passwd") is None
    assert login.find_url("ftp://example.com/x") is None


# ---- the dialog surfaces the URL rather than printing it and hoping -----

def test_the_dialog_offers_the_link_once_the_vendor_prints_one(make_app, paths):
    """Under WSL the vendor cannot open a browser and prints an address
    instead. It was reaching the user as unselectable text."""
    import tkinter as tk
    from shambles import gui, providers

    app = make_app(paths)
    dialog = gui.LoginDialog.__new__(gui.LoginDialog)
    tk.Toplevel.__init__(dialog, app)
    dialog.theme = app.theme
    dialog._url = None
    dialog.status = tk.Label(dialog, text="")
    dialog.output = tk.Text(dialog)
    dialog.open_button = tk.Button(dialog, state="disabled")
    dialog.copy_button = tk.Button(dialog, state="disabled")

    gui.LoginDialog._append(dialog, "Open https://claude.ai/oauth?x=1 to sign in")

    assert dialog._url == "https://claude.ai/oauth?x=1"
    assert str(dialog.open_button.cget("state")) == "normal"
    assert str(dialog.copy_button.cget("state")) == "normal"
    dialog.destroy()


def test_a_line_without_a_url_leaves_the_controls_alone(make_app, paths):
    import tkinter as tk
    from shambles import gui

    app = make_app(paths)
    dialog = gui.LoginDialog.__new__(gui.LoginDialog)
    tk.Toplevel.__init__(dialog, app)
    dialog.theme = app.theme
    dialog._url = None
    dialog.status = tk.Label(dialog, text="")
    dialog.output = tk.Text(dialog)
    dialog.open_button = tk.Button(dialog, state="disabled")
    dialog.copy_button = tk.Button(dialog, state="disabled")

    gui.LoginDialog._append(dialog, "Waiting for authentication...")

    assert dialog._url is None
    assert str(dialog.open_button.cget("state")) == "disabled"
    dialog.destroy()


def test_the_dialog_prefills_the_address_and_passes_the_environment(monkeypatch):
    """Re-login knows whose account this is, so the vendor page should too."""
    from shambles import gui, providers

    seen = {}

    class FakeProcess:
        def __init__(self, argv, *, env=None):
            seen.update(argv=argv, env=env)

        def start(self, *, on_line, on_exit):
            pass

    monkeypatch.setattr(gui.login, "LoginProcess", FakeProcess)
    dialog = gui.LoginDialog.__new__(gui.LoginDialog)
    dialog._email = "o@example.com"
    dialog._env = {"HOME": "/home/test"}

    gui.LoginDialog._start(dialog, providers.load("claude"))

    assert seen["argv"] == ["claude", "auth", "login", "--email", "o@example.com"]
    assert seen["env"] == {"HOME": "/home/test"}


def test_the_address_survives_the_browser_fallback(make_app, paths):
    """Under WSL the URL arrives at once and replaces the waiting line. On a
    re-login that line named the account to use, which is the one thing that
    stops a browser signed in as somebody else from being reused."""
    import tkinter as tk
    from shambles import gui

    app = make_app(paths)
    dialog = gui.LoginDialog.__new__(gui.LoginDialog)
    tk.Toplevel.__init__(dialog, app)
    dialog.theme = app.theme
    dialog._url = None
    dialog._email = "o@example.com"
    dialog.status = tk.Label(dialog, text="")
    dialog.output = tk.Text(dialog)
    dialog.open_button = tk.Button(dialog, state="disabled")
    dialog.copy_button = tk.Button(dialog, state="disabled")

    gui.LoginDialog._append(dialog, "Open https://claude.ai/oauth?x=1 to sign in")

    assert "o@example.com" in dialog.status.cget("text")
    dialog.destroy()
