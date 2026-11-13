"""A stand-in ShamblesService that records what the window asked of it."""

from shambles.app.service import ActionError, ActionPlan, ActionResult
from shambles.app.snapshot import Account, Group, Notice, Snapshot, Surface


def account(name, *, active=False, state="live", needs_login=False,
            status_label=None, email=None):
    return Account(name=name, email=email or f"{name.lower()}@example.test",
                   plan="max_5x", active=active, state=state,
                   needs_login=needs_login, status_label=status_label)


def group(*accounts, provider="claude", title="Claude Code", notices=(),
          can_sign_in=True, can_save=False, live_email=None,
          state="managed"):
    return Group(provider, title, [Surface("t", "Terminal")], list(accounts),
                 state=state, live_email=live_email, can_save=can_save,
                 notices=list(notices), can_sign_in=can_sign_in, cli=provider)


def lapsed(name):
    return account(name, state="closed", needs_login=True,
                   status_label="needs login")


def standard():
    """Work live, Personal healthy, Old lapsed; Codex installed and empty."""
    return Snapshot(1, [
        group(account("Work", active=True), account("Personal"),
              lapsed("Old")),
        group(provider="codex", title="Codex"),
    ])


def saved_elsewhere():
    """Signed in as Home, which is saved, while Work is still marked."""
    notice = Notice("signed_in_elsewhere",
                    "Signed in as home@example.test, which is saved as "
                    "'Home', but 'Work' is marked active.",
                    "Switch to 'Home' to settle it. Nothing is lost either "
                    "way.", account="Home")
    return Snapshot(1, [group(account("Work", active=True), account("Home"),
                              account("Third"), notices=[notice],
                              state="drifted", live_email="home@example.test")])


def unsaved():
    notice = Notice("unsaved_login",
                    "Signed in as new@example.test, which is not saved yet.",
                    "Save it as an account before switching.")
    return Snapshot(1, [group(account("Work", active=True),
                              account("Personal"), notices=[notice],
                              can_save=True, state="drifted",
                              live_email="new@example.test")])


def failure(action, code, message, recovery=""):
    return ActionResult(False, action,
                        error=ActionError(code, message, recovery))


class Handle:
    def __init__(self):
        self.cancelled = False
        self.waited = None

    def cancel(self):
        self.cancelled = True

    def wait(self, timeout=None):
        self.waited = timeout
        return True


class Clipboard:
    def __init__(self):
        self.text = None

    def setText(self, text):
        self.text = text


class FakeService:
    def __init__(self, snapshot=None):
        self.snap = snapshot or standard()
        self.calls = []
        self.theme = "system"
        self.migrations = ()
        self.opens = True
        #: action name -> ActionResult to return instead of success.
        self.fail = {}
        #: (on_line, on_done) of the sign-in in flight.
        self.login = None
        self.handles = []

    # -- reads ---------------------------------------------------------

    def snapshot(self):
        return self.snap

    def window_theme(self):
        return self.theme

    def run_migrations(self):
        return self.migrations

    def sign_in_url(self, line):
        return line if line.startswith("https://") else None

    # -- writes --------------------------------------------------------

    def _done(self, action, *args, summary=""):
        self.calls.append((action, *args))
        if action in self.fail:
            return self.fail[action]
        return ActionResult(True, action, summary, snapshot=self.snap)

    def refresh(self):
        return self._done("refresh")

    def set_window_theme(self, theme):
        self.calls.append(("set_window_theme", theme))
        self.theme = theme
        return ActionResult(True, "set_window_theme")

    def switch(self, provider, name):
        return self._done("switch", provider, name)

    def save_current(self, provider, name):
        return self._done("save_current", provider, name)

    def rename(self, provider, old, new):
        return self._done("rename", provider, old, new)

    def forget_marker(self, provider):
        return self._done("forget_marker", provider)

    def plan_remove(self, provider, name):
        return ActionPlan("remove", provider, name, True, f"Remove {name}?")

    def remove(self, plan):
        return self._done("remove", plan.provider, plan.account)

    def plan_eject(self):
        # Shaped like the service's own plan: what eject does, then after.
        return ActionPlan("eject", None, None, True, "Eject Shambles?",
                          ("Shambles will stop managing your accounts. "
                           "Nothing is deleted.",
                           "Afterwards:\nLogins for Personal stay on disk."))

    def eject(self, plan):
        return self._done("eject", summary="Shambles has handed back 2 "
                                           "accounts.")

    def open_sign_in_url(self, url):
        self.calls.append(("open", url))
        return self.opens

    def _start(self, action, provider, name, on_line, on_done):
        self.calls.append((action, provider, name))
        if action in self.fail:
            on_done(self.fail[action])
            return Handle()
        self.login = (on_line, on_done)
        self.handles.append(Handle())
        return self.handles[-1]

    def start_login(self, provider, name, on_line, on_done):
        return self._start("start_login", provider, name, on_line, on_done)

    def start_add(self, provider, name, on_line, on_done):
        return self._start("start_add", provider, name, on_line, on_done)

    # -- test helpers --------------------------------------------------

    def named(self, action):
        return [call for call in self.calls if call[0] == action]

    def settle(self, result):
        _on_line, on_done = self.login
        self.login = None
        on_done(result)
