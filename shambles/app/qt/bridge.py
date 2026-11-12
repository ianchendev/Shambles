"""The one object the QML talks to.

Holds the window's state -- the view model, the open sheet, the toast -- and
turns clicks into :class:`~shambles.app.service.ShamblesService` calls. Every
operation that moves a credential goes through the service; nothing here
imports ``switcher``, ``login`` or ``state``.

The state is plain data built by :mod:`shambles.app.qt.presenter`, so a flow
can be driven and asserted on from a test with no QML loaded at all: call a
slot, read ``bridge.sheet``.

Threading: the service runs the vendor's login on its own thread and calls
back from it. Those callbacks only ever emit a signal, which Qt queues onto
the GUI thread; no state is touched off that thread.
"""

from PySide6.QtCore import Property, QObject, Signal, Slot

from ... import __version__
from . import presenter, theme

SWITCHED = "Switched to {name}. Start a new session to pick it up."
SIGNED_IN = "{name} is signed in and live. Start a new session to pick it up."
NO_BROWSER = ("No browser could be launched from here, which is usual under "
              "WSL and over SSH. The link is on your clipboard.")
UNREADABLE = "Could not read your accounts. Press Refresh to try again."


class Bridge(QObject):
    viewChanged = Signal()
    sheetChanged = Signal()
    toastChanged = Signal()
    themeChanged = Signal()
    filterChanged = Signal()
    #: An account just became live: ``provider/name``. The card pulses.
    confirmed = Signal(str)

    _lineArrived = Signal(str)
    _loginSettled = Signal(object)

    def __init__(self, service, *, clipboard=None, system_dark=None,
                 motion=True, parent=None):
        super().__init__(parent)
        self._service = service
        self._clipboard = clipboard
        #: Callable returning True/False/None for the OS colour scheme.
        self._system_dark = system_dark or (lambda: None)
        self._motion = motion
        self._snapshot = None
        self._filter = ""
        self._view = {"groups": [], "count": 0, "showFilter": False,
                      "filtering": False, "matches": 0, "keys": {}}
        self._sheet = {}
        self._toast = {"text": "", "tone": "ok", "serial": 0}
        self._save_errors = {}
        #: The running vendor login, and what it is for.
        self._handle = None
        self._login = None
        self._eject_plan = None
        self._lineArrived.connect(self._on_line)
        self._loginSettled.connect(self._on_settled)

    # -- what the QML reads -----------------------------------------------

    @Property("QVariantMap", notify=viewChanged)
    def view(self):
        return self._view

    @Property("QVariantMap", notify=sheetChanged)
    def sheet(self):
        return self._sheet

    @Property(bool, notify=sheetChanged)
    def sheetOpen(self):
        return bool(self._sheet)

    @Property("QVariantMap", notify=toastChanged)
    def toast(self):
        return self._toast

    @Property("QVariantMap", notify=themeChanged)
    def theme(self):
        return theme.tokens(self.dark)

    @Property(bool, notify=themeChanged)
    def dark(self):
        return theme.is_dark(self.themeChoice, self._system_dark())

    @Property(str, notify=themeChanged)
    def themeChoice(self):
        return self._service.window_theme()

    @Property(bool, constant=True)
    def motion(self):
        return self._motion

    @Property(str, constant=True)
    def version(self):
        return __version__

    @Property(str, notify=filterChanged)
    def filter(self):
        return self._filter

    # -- state changes ----------------------------------------------------

    def _set_sheet(self, sheet):
        self._sheet = sheet or {}
        self.sheetChanged.emit()

    def _say(self, text, tone="ok"):
        if not text:
            return
        self._toast = {"text": text, "tone": tone,
                       "serial": self._toast["serial"] + 1}
        self.toastChanged.emit()

    def _rebuild(self):
        if self._snapshot is None:
            return
        model = presenter.view(self._snapshot, filter_text=self._filter)
        for group in model["groups"]:
            if group["save"] is not None:
                group["save"]["error"] = self._save_errors.get(
                    group["provider"], "")
        self._view = model
        self.viewChanged.emit()

    def _take(self, result):
        """Adopt whatever state a result carries, or read it fresh."""
        fresh = getattr(result, "snapshot", None)
        if fresh is None:
            try:
                fresh = self._service.snapshot()
            except Exception:
                fresh = None
        if fresh is not None:
            self._snapshot = fresh
        self._rebuild()

    def _report(self, result, success=""):
        """Adopt a result and say how it went. Returns whether it worked."""
        self._take(result)
        if result.ok:
            text = " ".join(part for part in
                            (success or result.summary, *result.warnings)
                            if part)
            self._say(text)
        else:
            self._say(_error_text(result), "bad")
        return result.ok

    def _account(self, provider, name):
        return presenter.find_account(self._view, provider, name)

    def _live_name(self, provider):
        group = presenter.find_group(self._view, provider)
        return group["live"]["name"] if group and group["live"] else ""

    # -- startup, refresh, theme, filter ------------------------------------

    def start(self):
        """Run startup migrations, then read the accounts."""
        try:
            notices = self._service.run_migrations()
        except Exception:
            notices = ()
        self.refresh()
        if notices:
            self._set_sheet(presenter.notice_sheet(notices))

    @Slot()
    def refresh(self):
        try:
            result = self._service.refresh()
        except Exception:
            self._say(UNREADABLE, "bad")
            return
        self._take(result)
        if not result.ok:
            self._say(_error_text(result), "bad")
        elif result.warnings:
            self._say(" ".join(result.warnings), "bad")

    @Slot(str)
    def setTheme(self, choice):
        result = self._service.set_window_theme(choice)
        if not result.ok:
            self._say(_error_text(result), "bad")
        self.themeChanged.emit()

    def system_theme_changed(self):
        self.themeChanged.emit()

    @Slot(str)
    def setFilter(self, text):
        if text == self._filter:
            return
        self._filter = text
        self.filterChanged.emit()
        self._rebuild()

    # -- switching ----------------------------------------------------------

    @Slot(str, str)
    def switchTo(self, provider, name):
        account = self._account(provider, name)
        if (not account or account["action"] != "switch"
                or not account["actionEnabled"] or self._handle):
            return
        result = self._service.switch(provider, name)
        if self._report(result, SWITCHED.format(name=name)):
            self.confirmed.emit(f"{provider}/{name}")

    @Slot(str)
    def pressKey(self, key):
        target = self._view["keys"].get(key)
        if target and not self._sheet:
            self.switchTo(target["provider"], target["name"])

    # -- signing in and adding ------------------------------------------------

    @Slot(str, str)
    def signIn(self, provider, name):
        account = self._account(provider, name)
        if (not account or account["action"] != "signin"
                or not account["actionEnabled"] or self._handle):
            return
        self._begin(provider, name, adding=False, email=account["email"],
                    title=account["providerTitle"])

    @Slot(str)
    def openAdd(self, provider):
        if self._handle:
            return
        self._set_sheet(presenter.add_sheet(self._view, provider=provider))

    @Slot(str, str)
    def submitAdd(self, provider, name):
        group = presenter.find_group(self._view, provider)
        if not group or not group["canSignIn"] or self._handle:
            return
        if not name.strip():
            self._set_sheet(presenter.add_sheet(
                self._view, provider=provider,
                error="Give the account a name, such as Work."))
            return
        self._begin(provider, name.strip(), adding=True, email="",
                    title=group["title"])

    def _begin(self, provider, name, *, adding, email, title):
        self._login = {"provider": provider, "name": name, "adding": adding,
                       "started": False}
        self._set_sheet(presenter.login_sheet(
            provider_title=title, name=name, email=email,
            previous=self._live_name(provider), adding=adding))
        start = (self._service.start_add if adding
                 else self._service.start_login)
        # The callbacks arrive on the vendor's thread; emitting is all they do.
        handle = start(provider, name, self._lineArrived.emit,
                       self._loginSettled.emit)
        if self._login is not None:
            self._handle = handle

    @Slot(str)
    def _on_line(self, line):
        if self._sheet.get("kind") != "login" or self._login is None:
            return
        sheet = self._sheet
        if not self._login["started"]:
            self._login["started"] = True
            sheet = presenter.login_started(sheet)
        url = self._service.sign_in_url(line)
        if url and not sheet["url"]:
            sheet = {**sheet, "url": url}
        if sheet is not self._sheet:
            self._set_sheet(sheet)

    @Slot(object)
    def _on_settled(self, result):
        login, self._login, self._handle = self._login, None, None
        self._take(result)
        if login is None:
            return
        name, provider = login["name"], login["provider"]
        if result.ok:
            self._set_sheet({})
            self._say(" ".join((SIGNED_IN.format(name=name),)))
            self.confirmed.emit(f"{provider}/{name}")
            return
        code = result.error.code if result.error else ""
        if code == "login_cancelled":
            self._set_sheet({})
            self._say(_error_text(result))
        elif login["adding"] and code not in presenter.LOGIN_CODES:
            # Refused before any sign-in ran: a name problem, say. That
            # belongs on the form, with what was typed still in it.
            self._set_sheet(presenter.add_sheet(
                self._view, provider=provider, name=name,
                error=result.error.message if result.error else ""))
        else:
            sheet = presenter.result_sheet(result, name=name)
            sheet["provider"] = provider
            self._set_sheet(sheet)

    @Slot()
    def cancelLogin(self):
        if self._handle is not None:
            self._set_sheet({**self._sheet, "cancelling": True})
            self._handle.cancel()

    @Slot()
    def retry(self):
        """Run the sign-in a result sheet is about once more."""
        sheet = self._sheet
        if sheet.get("kind") != "result" or not sheet.get("retry"):
            return
        self._set_sheet({})
        # An add that got as far as the vendor left its profile in place, so
        # a retry is a sign-in to it either way.
        account = self._account(sheet["provider"], sheet["name"])
        if account and account["action"] == "signin":
            self.signIn(sheet["provider"], sheet["name"])

    @Slot()
    def openUrl(self):
        """Hand the link to a browser, and leave it on the clipboard too.

        Copying unconditionally is the point: the WSL openers report success
        while doing nothing, so "did it open?" is never trusted.
        """
        url = self._sheet.get("url")
        if not url:
            return
        self._copy(url)
        if not self._service.open_sign_in_url(url):
            self._say(NO_BROWSER)

    @Slot()
    def copyUrl(self):
        url = self._sheet.get("url")
        if url:
            self._copy(url)

    def _copy(self, url):
        if self._clipboard is not None:
            self._clipboard.setText(url)
        self._set_sheet({**self._sheet, "copied": True})

    # -- saving, renaming, removing, forgetting, ejecting ---------------------

    @Slot(str, str)
    def saveCurrent(self, provider, name):
        result = self._service.save_current(provider, name.strip())
        self._save_errors.pop(provider, None)
        if not result.ok and result.error:
            # Beside the field it is about, not in a toast that fades.
            self._save_errors[provider] = result.error.message
            self._take(result)
            return
        self._report(result, f"Saved {name.strip()}. You can switch away "
                             "and come back to it.")

    @Slot(str, str)
    def askRename(self, provider, name):
        account = self._account(provider, name)
        if account:
            self._set_sheet(presenter.rename_sheet(account))

    @Slot(str)
    def submitRename(self, new_name):
        sheet = self._sheet
        if sheet.get("kind") != "rename":
            return
        new_name = new_name.strip()
        if not new_name or new_name == sheet["name"]:
            self._set_sheet({})
            return
        result = self._service.rename(sheet["provider"], sheet["name"],
                                      new_name)
        if result.ok:
            self._set_sheet({})
            self._report(result, f"Renamed to {new_name}.")
        else:
            self._take(result)
            self._set_sheet({**sheet, "error": result.error.message
                             if result.error else "Could not rename."})

    @Slot(str, str)
    def askRemove(self, provider, name):
        account = self._account(provider, name)
        # The live account is never removable: not offered, and not honoured
        # if something asks anyway.
        if account and account["canRemove"]:
            self._set_sheet(presenter.remove_sheet(account))

    @Slot()
    def askEject(self):
        try:
            self._eject_plan = self._service.plan_eject()
        except Exception:
            self._say("Could not work out what ejecting would do.", "bad")
            return
        self._set_sheet(presenter.eject_sheet(self._eject_plan))

    @Slot(str)
    def forgetMarker(self, provider):
        self._report(self._service.forget_marker(provider),
                     "Forgot the missing profile.")

    @Slot()
    def confirm(self):
        """Carry out whatever the open confirmation asked about."""
        sheet = self._sheet
        if sheet.get("kind") != "confirm":
            return
        self._set_sheet({})
        action = sheet["action"]
        if action == "remove":
            plan = self._service.plan_remove(sheet["provider"], sheet["name"])
            self._report(self._service.remove(plan),
                         f"Removed {sheet['name']}.")
        elif action == "eject" and self._eject_plan is not None:
            plan, self._eject_plan = self._eject_plan, None
            result = self._service.eject(plan)
            self._take(result)
            if result.ok:
                self._set_sheet({"kind": "notice", "tone": "ok",
                                 "title": "Shambles has stepped aside",
                                 "messages": [result.summary]})
            else:
                self._say(_error_text(result), "bad")

    @Slot()
    def dismiss(self):
        """Close the sheet. A running sign-in is cancelled, not abandoned."""
        if self._sheet.get("kind") == "login":
            self.cancelLogin()
            return
        self._eject_plan = None
        self._set_sheet({})

    def shutdown(self):
        """Stop a vendor login the window would otherwise orphan."""
        handle, self._handle = self._handle, None
        if handle is not None:
            handle.cancel()
            handle.wait(5)


def _error_text(result) -> str:
    error = result.error
    if not error:
        return "That did not work."
    return " ".join(part for part in (error.message, error.recovery) if part)
