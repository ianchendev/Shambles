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

from PySide6.QtCore import Property, QObject, QTimer, Signal, Slot

import datetime
import threading
import time

from ... import __version__
from ..service import ActionError, ActionResult, waiting_for_refresh
from . import placement, presenter, theme

# None of these says what a running session does after the change. Claude
# Code 2.1.300 re-reads a changed login at its next request; older versions
# and Codex are unconfirmed, so a claim either way could be wrong. See
# tests/test_wording.py.
SWITCHED = "Switched to {name}."
SETTLED = "{name} is the account in use, and its login is saved."
SIGNED_IN = "{name} is signed in and in use."
NO_BROWSER = ("No browser could be launched from here, which is usual under "
              "WSL and over SSH. The link is on your clipboard.")
UNREADABLE = "Could not read your accounts. Press Refresh to try again."
#: D10: what the busy line says while a switch waits on Claude Code's own
#: renewal. The full reason, with the time limit, goes behind its i.
WAITING = "Waiting for Claude Code to finish renewing"
CLOSES = " Shambles closes when it is done."

#: How often the window redraws what it already holds, so a countdown ("in
#: 1h 52m") stays true and a limit shows as reset when its time comes. Reads
#: nothing; a redraw is the presenter run again at the new time.
REDRAW_MS = 30_000

#: U2. How often the window checks whether Claude Code or Codex wrote a file
#: (a stat of a handful of paths), and how often it re-reads regardless.
#: Both re-read files only; see ShamblesService.refresh_files.
POLL_MS = 2_000
REREAD_MS = 60_000
#: Coming back to the window re-reads at most this often.
FOCUS_GAP_MS = 2_000

UPDATED_TIP = ("Shambles re-reads Claude Code's and Codex's files when you "
               "return to the window, when those files change, and every "
               "minute. Nothing goes online. Refresh reads everything now.")
OUTSIDE_TEXT = "Changed outside Shambles · Refresh"
OUTSIDE_TIP = ("{message} The window still shows what it read before. Press "
               "Refresh to read the new login; Shambles reads the Keychain "
               "or Credential Manager only when you ask.")


class Bridge(QObject):
    viewChanged = Signal()
    sheetChanged = Signal()
    toastChanged = Signal()
    themeChanged = Signal()
    updatedChanged = Signal()
    filterChanged = Signal()
    #: An account just became live: ``provider/name``. The card pulses.
    confirmed = Signal(str)
    ctrlHeldChanged = Signal()

    busyChanged = Signal()
    #: The window asked to close mid-switch and the switch has now finished.
    quitRequested = Signal()

    _lineArrived = Signal(str)
    _loginSettled = Signal(object)
    _switchWaited = Signal()
    _switchFinished = Signal(object)

    def __init__(self, service, *, clipboard=None, system_dark=None,
                 motion=True, runner=None, screens=None, clock_ms=None,
                 parent=None):
        super().__init__(parent)
        #: The time the window draws at. A test passes its own.
        self._clock_ms = clock_ms or (lambda: int(time.time() * 1000))
        self._clock = QTimer(self)
        self._clock.setInterval(REDRAW_MS)
        self._clock.timeout.connect(self.tick)
        self._poll = QTimer(self)
        self._poll.setInterval(POLL_MS)
        self._poll.timeout.connect(self.poll)
        self._minute = QTimer(self)
        self._minute.setInterval(REREAD_MS)
        self._minute.timeout.connect(self.reread)
        #: When the accounts were last read, and the files' fingerprint then.
        self._read_at = None
        self._signature = None
        self._updated = ""
        self._tip = UPDATED_TIP
        #: Set when an automatic read found a login changed outside
        #: Shambles; cleared by the next full read.
        self._outside = ""
        #: How a switch is run off the window's thread. A test passes one
        #: that runs it inline; the window uses a thread of its own.
        self._runner = runner or self._in_thread
        self._worker = None
        #: The switch in flight, if any, and whether the window is waiting
        #: for it to finish before closing.
        self._switching = None
        self._quit_pending = False
        self._busy_text = ""
        self._busy_detail = ""
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
        self._toast = {"text": "", "tone": "ok", "serial": 0,
                       "actionLabel": ""}
        #: What the toast's button does, if it has one.
        self._toast_action = None
        self._save_errors = {}
        #: The running vendor login, and what it is for.
        self._handle = None
        self._login = None
        self._eject_plan = None
        self._lineArrived.connect(self._on_line)
        self._loginSettled.connect(self._on_settled)
        self._place = self._opening_place(screens)
        #: D4: deadline lines closed, ``{"provider/account": day}``. Read
        #: with the accounts, not on every redraw.
        self._hidden = {}
        self._ctrl_held = False
        self._switchWaited.connect(self._on_switch_waited)
        self._switchFinished.connect(self._on_switch_finished)

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

    @Property(bool, notify=busyChanged)
    def busy(self):
        """A switch is running. Everything that changes an account waits."""
        return self._switching is not None

    @Property(str, notify=busyChanged)
    def busyText(self):
        return self._busy_text

    @Property(str, notify=busyChanged)
    def busyDetail(self):
        """Why the busy line has taken so long, for its i. Empty when the
        line says all there is."""
        return self._busy_detail

    @Property("QVariantMap", constant=True)
    def place(self):
        """Where the window opens and how big: ``x``, ``y``, ``width``,
        ``height``, ``maximized``. Read once, when the window is made."""
        return self._place

    @Property(bool, notify=ctrlHeldChanged)
    def ctrlHeld(self):
        """Ctrl (Command on macOS) is held: every account shows its number
        (D8)."""
        return self._ctrl_held

    def set_ctrl_held(self, held):
        held = bool(held)
        if held != self._ctrl_held:
            self._ctrl_held = held
            self.ctrlHeldChanged.emit()

    @Property(bool, constant=True)
    def motion(self):
        return self._motion

    @Property(str, constant=True)
    def version(self):
        return __version__

    @Property(str, notify=filterChanged)
    def filter(self):
        return self._filter

    @Property(str, notify=updatedChanged)
    def updatedText(self):
        """``Updated just now`` / ``Updated 5m ago``, for the header."""
        return self._updated

    @Property(str, notify=updatedChanged)
    def updatedTip(self):
        return self._tip

    # -- state changes ----------------------------------------------------

    def _set_sheet(self, sheet):
        self._sheet = sheet or {}
        self.sheetChanged.emit()

    def _say(self, text, tone="ok", action=None):
        """Show ``text``. ``action`` is ``(label, callable)`` for a button
        on the message that offers the obvious next step."""
        if not text:
            return
        label, self._toast_action = action if action else ("", None)
        self._toast = {"text": text, "tone": tone,
                       "serial": self._toast["serial"] + 1,
                       "actionLabel": label}
        self.toastChanged.emit()

    @Slot()
    def toastAction(self):
        """The toast's button. Runs once; a later message replaces it."""
        action, self._toast_action = self._toast_action, None
        if action is not None and not self._occupied():
            action()

    def _rebuild(self, *, only_if_changed=False):
        """Work the view out again from the snapshot held.

        ``only_if_changed`` is for redraws nobody asked for. The QML feeds
        its Repeaters plain arrays, so every ``viewChanged`` recreates every
        card: an open menu closes, focus and tooltips go. A timer must not
        do that to a window nobody is touching when nothing on it moved.
        """
        if self._snapshot is None:
            return
        now_ms = self._clock_ms()
        today = _day(now_ms)
        model = presenter.view(
            self._snapshot, filter_text=self._filter, now_ms=now_ms,
            hidden_deadlines={key for key, day in self._hidden.items()
                              if day == today})
        for group in model["groups"]:
            if group["save"] is not None:
                group["save"]["error"] = self._save_errors.get(
                    group["provider"], "")
        if only_if_changed and model == self._view:
            return
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
            self._mark_read()
        self._rebuild()

    def _mark_read(self):
        self._outside = ""
        self._read_at = self._clock_ms()
        try:
            self._signature = self._service.watch_signature()
        except Exception:
            self._signature = None
        self._say_updated()

    def _say_updated(self):
        tip = UPDATED_TIP
        if self._outside:
            text = OUTSIDE_TEXT
            tip = OUTSIDE_TIP.format(message=self._outside)
        elif self._read_at is None:
            text = ""
        else:
            minutes = max(0, self._clock_ms() - self._read_at) // 60_000
            text = ("Updated just now" if minutes < 1
                    else f"Updated {minutes}m ago" if minutes < 60
                    else f"Updated {minutes // 60}h ago")
        if (text, tip) != (self._updated, self._tip):
            self._updated, self._tip = text, tip
            self.updatedChanged.emit()

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
        self._clock.start()
        self._poll.start()
        self._minute.start()

    @Slot()
    def tick(self):
        """Redraw at the current time if that changes anything. Reads
        nothing from disk; most ticks do nothing at all."""
        self._rebuild(only_if_changed=True)
        self._say_updated()

    # -- U2: re-reading by itself, files only --------------------------------

    @Slot()
    def reread(self):
        """Re-read what the vendors wrote, without the Keychain.

        Everything that runs without the user asking comes here, never to
        :meth:`refresh`. Skipped while a switch or a sign-in is moving a
        login: their own result brings the fresh state when they finish.
        """
        if self._occupied():
            return
        try:
            result = self._service.refresh_files()
        except Exception:
            return
        fresh = getattr(result, "snapshot", None)
        error = getattr(result, "error", None)
        if error is not None and error.code == "changed_outside":
            # What is on screen stays, and the header says to Refresh. The
            # fingerprint is taken so the poll does not ask again every 2 s.
            self._outside = error.message
            try:
                self._signature = self._service.watch_signature()
            except Exception:
                pass
            self._say_updated()
            return
        if fresh is None:
            # No answer without the Keychain. What is on screen stays.
            return
        self._snapshot = fresh
        self._mark_read()
        self._rebuild(only_if_changed=True)

    @Slot()
    def poll(self):
        """Re-read if Claude Code or Codex wrote a file since the last read."""
        if self._occupied():
            return
        try:
            signature = self._service.watch_signature()
        except Exception:
            return
        if signature != self._signature:
            self.reread()

    @Slot()
    def windowFocused(self):
        """The window came back to the front: worth a look, files only."""
        if (self._read_at is not None
                and self._clock_ms() - self._read_at < FOCUS_GAP_MS):
            return
        self.reread()

    @Slot()
    def refresh(self):
        if self._switching is not None:
            return
        try:
            self._hidden = dict(self._service.hidden_deadlines())
        except Exception:
            pass
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

    # -- where the window is ------------------------------------------------

    def _opening_place(self, screens):
        """Where the window was left, unless no screen shows it any more.

        ``screens`` returns ``(available areas, primary area)`` as
        ``(x, y, width, height)`` tuples; the application passes Qt's.
        """
        try:
            stored = self._service.window_place()
        except Exception:
            stored = None
        areas, primary = screens() if screens is not None else ([], None)
        return placement.opening_place(stored, list(areas), primary)

    @Slot(int, int, int, int, bool)
    def rememberPlace(self, x, y, width, height, maximized):
        """Keep where the window is, for the next time it opens.

        Failing to save is not worth a message. The next window opens in
        the centre instead, and nothing else depends on it.
        """
        try:
            self._service.set_window_place(x, y, width, height, maximized)
        except Exception:
            pass

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
                or not account["actionEnabled"] or self._occupied()):
            return
        self._run_switch(provider, name, SWITCHED.format(name=name))

    def _occupied(self):
        """A sign-in or a switch is running, and nothing else may start."""
        return self._handle is not None or self._switching is not None

    def _set_busy(self, text, detail=""):
        self._busy_text = text
        self._busy_detail = detail
        self.busyChanged.emit()

    def _run_switch(self, provider, name, success):
        """Switch on a thread of its own and report back on this one.

        A switch can wait up to 15 s for Claude Code to finish renewing its
        login. Run here, on the window's thread, that is 15 s of a window
        that draws nothing and answers no clicks -- which is what the Tk
        window does. The worker only ever emits signals; Qt queues them onto
        this thread, where all state lives.
        """
        self._switching = {"provider": provider, "name": name,
                           "success": success}
        self._set_busy(f"Switching to {name}\u2026")

        def work():
            try:
                result = self._service.switch(
                    provider, name, on_wait=self._switchWaited.emit)
            except Exception:
                result = ActionResult(False, "switch", error=ActionError(
                    "switch_failed", "The switch could not be completed.",
                    "Refresh to see where things stand, then retry."))
            self._switchFinished.emit(result)

        self._runner(work)

    def _in_thread(self, work):
        # Not a daemon. An interpreter exiting under a switch would stop it
        # between replacing the live login and moving the marker; shutdown()
        # waits for it instead.
        self._worker = threading.Thread(target=work, name="shambles-switch")
        self._worker.start()

    @Slot()
    def _on_switch_waited(self):
        if self._switching is None:
            return
        text = WAITING
        if self._quit_pending:
            text += "." + CLOSES
        self._set_busy(text, waiting_for_refresh())

    @Slot(object)
    def _on_switch_finished(self, result):
        switching, self._switching = self._switching, None
        self._set_busy("")
        if switching is not None and self._report(result,
                                                  switching["success"]):
            self.confirmed.emit(
                f"{switching['provider']}/{switching['name']}")
        if self._quit_pending:
            self.quitRequested.emit()

    @Slot(result=bool)
    def closeRequested(self):
        """Whether the window may close now. Not while a switch is running:
        it closes itself once the switch has finished."""
        if self._switching is None:
            return True
        if not self._quit_pending:
            self._quit_pending = True
            text = self._busy_text.rstrip()
            if not text.endswith((".", "\u2026")):
                text += "."
            self._set_busy(text + CLOSES, self._busy_detail)
        return False

    @Slot(str)
    def settle(self, provider):
        """Switch to the saved account the live login's address names.

        Only to the account the snapshot names, and only through the
        service's ordinary switch, which files the live login there and
        keeps the one it replaces. Not gated on that account's own row: its
        saved login may have lapsed while the live one is fresh, and this is
        exactly what puts the fresh one in its place.
        """
        group = presenter.find_group(self._view, provider)
        settle = group["settle"] if group else None
        if not settle or self._occupied():
            return
        name = settle["account"]
        self._run_switch(provider, name, SETTLED.format(name=name))

    @Slot(str)
    def pressKey(self, key):
        """Ctrl+N: the Nth account's own button, as if it were clicked."""
        target = self._view["keys"].get(key)
        if not target or self._sheet:
            return
        if target.get("action") == "signin":
            self.signIn(target["provider"], target["name"])
        else:
            self.switchTo(target["provider"], target["name"])

    @Slot(str)
    def hideDeadline(self, key):
        """D4's ×: hide that deadline line until tomorrow. The row's badge
        still says it."""
        today = _day(self._clock_ms())
        self._hidden[key] = today
        try:
            self._service.hide_deadline(key, today)
        except Exception:
            pass
        self._rebuild()

    # -- signing in and adding ------------------------------------------------

    @Slot(str, str)
    def signIn(self, provider, name):
        account = self._account(provider, name)
        # Wherever the presenter offers it: the row's own action for a lapsed
        # login, or a second button beside Switch for one that is due.
        if (not account or not account["signIn"]
                or not account["signInEnabled"] or self._occupied()):
            return
        self._begin(provider, name, adding=False, email=account["email"],
                    title=account["providerTitle"])

    @Slot(str)
    def openAdd(self, provider):
        if self._occupied():
            return
        self._set_sheet(presenter.add_sheet(self._view, provider=provider))

    @Slot(str, str)
    def submitAdd(self, provider, name):
        group = presenter.find_group(self._view, provider)
        if not group or not group["canSignIn"] or self._occupied():
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
        if account and account["signIn"]:
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
        if self._occupied():
            return
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
        if self._occupied():
            return
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
        if self._occupied():
            return
        account = self._account(provider, name)
        # The live account is never removable: not offered, and not honoured
        # if something asks anyway.
        if account and account["canRemove"]:
            self._set_sheet(presenter.remove_sheet(account))

    @Slot()
    def askEject(self):
        if self._occupied():
            return
        try:
            self._eject_plan = self._service.plan_eject()
        except Exception:
            self._say("Could not work out what ejecting would do.", "bad")
            return
        self._set_sheet(presenter.eject_sheet(self._eject_plan))

    @Slot(str)
    def forgetMarker(self, provider):
        if self._occupied():
            return
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
        """Stop a vendor login the window would otherwise orphan, and let a
        switch that is under way finish rather than exit under it."""
        self._clock.stop()
        self._poll.stop()
        self._minute.stop()
        handle, self._handle = self._handle, None
        if handle is not None:
            handle.cancel()
            handle.wait(5)
        worker = self._worker
        if worker is not None and worker.is_alive():
            # Bounded by the refresh lock's own limit plus the switch itself.
            worker.join(60)


def _day(ms) -> str:
    """The local date at ``ms``, as the settings file keeps it."""
    return datetime.date.fromtimestamp(ms / 1000).isoformat()


def _error_text(result) -> str:
    error = result.error
    if not error:
        return "That did not work."
    return " ".join(part for part in (error.message, error.recovery) if part)
