"""A compact window for switching between accounts, grouped by provider."""

import datetime
import signal
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import eject, login, migrate, profiles, state, switcher, usage
from . import providers as provider_registry
from .errors import ShamblesError
from .paths import Paths
from .theme import (ACCENT_BAR_WIDTH, GAP_L, GAP_M, GAP_S, GAP_XS,
                    MAX_HEIGHT_FRACTION, MIN_HEIGHT, NAME_MAX_PX,
                    WINDOW_WIDTH, Theme, elide, scale_for_display)

WINDOW_TITLE = "Shambles"

#: Chip colour keys per expiry severity, resolved against the palette.
CHIP_STYLES = {
    profiles.EXPIRY_OK: ("chip_ok_fg", "chip_ok_bg"),
    profiles.EXPIRY_SOON: ("chip_soon_fg", "chip_soon_bg"),
    profiles.EXPIRY_GONE: ("chip_gone_fg", "chip_gone_bg"),
}

#: Deliberately names no fixed width. Observed refresh windows differ by an
#: order of magnitude across platform and plan samples (docs/token-storage.md),
#: and the chip beside this tooltip already shows the account's real figure.
EXPIRY_TOOLTIP = (
    "Refresh token {verb} {date}.\n\n"
    "This rolling window is what lets Shambles switch to this account without "
    "a verification email. Using the account renews it."
)

RENAME_HINT = "Double-click to rename"

#: DD-1 keeps durations off a card's face but says the raw timestamps stay
#: available in a tooltip. A healthy account renders no chip, so without this
#: there was nothing to hover and the number was unreachable.
EXPIRY_LINE = "Refresh token {verb} {date} ({days})."

#: Decorative glyphs are chosen at runtime from what the font can draw. Tk
#: substitutes a box for a missing glyph and reports nothing, so a character
#: picked on one machine renders as tofu on another -- Ubuntu has no U+FF0B,
#: which is why a hardcoded "＋ Add Account" showed a box.
GLYPH_SPEC = {
    "info": (("ⓘ", "ℹ"), "i"),
    "remove": (("✕", "✖", "×"), "x"),
    "refresh": (("⟳", "↻", "⭯"), "R"),
    "add": (("＋", "+"), "+"),
    "warn": (("⚠", "△"), "!"),
}

USAGE_LABELS = {"session": "session", "week": "week"}

#: Bar geometry. The track fills whatever width the row is given, so only the
#: height and the fixed label/value columns are set here.
BAR_HEIGHT = 8
BAR_LABEL_WIDTH = 8
BAR_VALUE_WIDTH = 5

#: Fill colour per display severity. Red past usage.RED_AT, matching the
#: vendor's own meter; amber only when the vendor itself flags something below
#: that; otherwise the ordinary accent.
BAR_FILL = {"ok": "accent", "soon": "chip_soon_fg", "gone": "chip_gone_fg"}

#: Shown instead of bars when a provider publishes figures but has none yet.
#: Blank space reads as a broken widget; saying why does not. A provider that
#: publishes nothing at all renders neither, since there is nothing to explain.
NO_USAGE_ACTIVE = "usage appears once you run it"
NO_USAGE_IDLE = "no usage recorded yet"

USAGE_TOOLTIP = (
    "{label} usage: {percent}%{resets}\n\n"
    "Read from the figures the vendor caches for this account. {freshness}"
)

FRESH_NOTE = "Updated as you work."
#: For the account signed in as. An old figure here just means nothing has
#: refreshed it lately, not that you left.
IDLE_NOTE = (
    "Last updated {age}. It refreshes as you work, so run a session or press "
    "{refresh} to pick up a newer figure."
)
#: For an account not signed in as, where the number really is frozen.
STALE_NOTE = (
    "Last updated {age}, while this account was active — it has not been "
    "signed in since, so the real figure may have moved on. Switch to it to "
    "see a current number."
)

#: Gap between a widget and its tooltip, and the margin kept from screen edges.
TOOLTIP_OFFSET = 12
TOOLTIP_MARGIN = 8

#: How often to hand control back to Python so pending signals get dispatched.
SIGNAL_POLL_MS = 150

#: The empty-slot placeholder: tall enough to read as a card-shaped gap, and
#: dashed so it reads as a space to fill rather than as a real profile.
PLACEHOLDER_HEIGHT = 62
PLACEHOLDER_DASH = (3, 3)

#: ``{warn}`` is substituted with a glyph the font can draw, resolved once per
#: window rather than hardcoded.
GROUP_STATES = {
    state.UNMANAGED: "No accounts saved yet",
    state.UNKNOWN: "{warn} Not sure which account is live",
    state.MISSING_PROFILE: "{warn} Profile '{profile}' is missing from disk",
    state.DRIFTED: "{warn} Signed in as {live_email}, but '{profile}' expects "
                   "{expected_email}",
}


def tooltip_position(widget_x, widget_y, widget_height, tip_width,
                     screen_width, screen_height, tip_height=0):
    """Where to put a tooltip so it stays on screen.

    Placed below-right of the widget by default. A tooltip anchored to a
    control near the right edge -- the ✕ on a profile card is exactly that --
    would otherwise render partly off the display and clip mid-word.
    """
    x = widget_x + TOOLTIP_OFFSET
    if x + tip_width > screen_width - TOOLTIP_MARGIN:
        x = max(TOOLTIP_MARGIN, screen_width - TOOLTIP_MARGIN - tip_width)

    y = widget_y + widget_height + 6
    if tip_height and y + tip_height > screen_height - TOOLTIP_MARGIN:
        y = max(TOOLTIP_MARGIN, widget_y - tip_height - 6)
    return x, y


def group_status(current, warn: str = "⚠") -> str:
    """The second line of a group heading: who is live, or what is wrong."""
    if current.kind == state.MANAGED:
        return current.live_email or ""
    template = GROUP_STATES.get(current.kind, "")
    return template.format(warn=warn,
                           profile=current.profile or "",
                           live_email=current.live_email or "unknown",
                           expected_email=current.expected_email or "unknown")


def group_heading(provider, current, warn: str = "⚠") -> str:
    """One line naming a provider and whatever is true about it right now.

    Per-provider rather than a single window header: with two providers there
    are two active accounts and two independent warning states, and a
    fixed-size header cannot render N of them without growing every time a
    provider is added.
    """
    if current.kind == state.MANAGED:
        who = current.profile or "unknown"
        email = current.live_email
        return f"{provider.display_name} · {who}" + (f" — {email}" if email else "")
    template = GROUP_STATES.get(current.kind, "")
    detail = template.format(warn=warn,
                             profile=current.profile or "",
                             live_email=current.live_email or "unknown",
                             expected_email=current.expected_email or "unknown")
    return f"{provider.display_name} · {detail}"


def expiry_line(profile) -> str | None:
    """One line naming when this account's window closes, or None."""
    ms = profile.liveness.expires_at_ms
    if ms is None:
        return None
    when = datetime.datetime.fromtimestamp(ms / 1000)
    days = profile.liveness.days_left
    if days is None:
        span = "date known"
    elif days < 0:
        span = f"{abs(days)}d ago"
    elif days == 0:
        span = "today"
    else:
        span = f"in {days}d"
    verb = "expired" if days is not None and days < 0 else "expires"
    return EXPIRY_LINE.format(verb=verb,
                              date=when.strftime("%d %b %Y, %H:%M"),
                              days=span)


def name_tooltip(profile) -> str:
    """What hovering a profile name says: its window, then the rename hint."""
    line = expiry_line(profile)
    return f"{line}\n\n{RENAME_HINT}" if line else RENAME_HINT


def expiry_tooltip(profile) -> str:
    """The exact date behind a closing/closed chip with a known expiry."""
    when = datetime.datetime.fromtimestamp(profile.liveness.expires_at_ms / 1000)
    days = profile.liveness.days_left
    verb = "expired" if days is not None and days < 0 else "expires"
    return EXPIRY_TOOLTIP.format(verb=verb, date=when.strftime("%d %b %Y, %H:%M"))


def chip_tooltip(profile) -> str:
    """Tooltip for the face chip: date prose when known, else warning copy."""
    if profile.liveness.expires_at_ms is not None:
        return expiry_tooltip(profile)
    return profiles.warning(profile) or ""


class Tooltip:
    """Tkinter has no tooltip widget, so here is the smallest useful one.

    The popup is an override-redirect Toplevel, which means the window manager
    draws no frame around it and offers no way to close it. Anything that can
    leave one visible without an owner strands it on the desktop permanently,
    so every path that could do so is closed off below.
    """

    #: Every tooltip currently showing, so shutdown can sweep them up.
    _open = set()

    def __init__(self, widget, text, theme=None):
        self.widget, self.text, self.theme, self.tip = widget, text, theme, None
        # Bound to the widget *and* everything inside it. Tk delivers <Enter>
        # to the deepest widget under the pointer, so a tooltip on a container
        # whose children cover it would never fire.
        for target in self._tree(widget):
            target.bind("<Enter>", self._show, add="+")
            target.bind("<Leave>", self._maybe_hide, add="+")
            # refresh() destroys every row widget on each switch. Without this
            # a tooltip visible at that moment never sees <Leave> and is
            # orphaned on the desktop.
            target.bind("<Destroy>", self._hide, add="+")

    @staticmethod
    def _tree(widget):
        found = [widget]
        for child in widget.winfo_children():
            found.extend(Tooltip._tree(child))
        return found

    def _maybe_hide(self, _event=None):
        """Ignore a <Leave> that is only the pointer crossing into a child."""
        try:
            under = self.widget.winfo_containing(
                self.widget.winfo_pointerx(), self.widget.winfo_pointery())
        except tk.TclError:
            under = None
        if under is not None and under in self._tree(self.widget):
            return
        self._hide()

    def _show(self, _event=None):
        if self.tip or not self.text:
            return
        # One at a time. Crossing from a chip onto a bar could otherwise leave
        # both on screen, overlapping each other.
        Tooltip.hide_all()
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        opts = {}
        if self.theme:
            opts = {"font": self.theme.body, "bg": "#22242a", "fg": "#f4f5f7"}
        tk.Label(self.tip, text=self.text, justify="left", relief="flat",
                 wraplength=340, padx=GAP_S, pady=GAP_XS + 2, **opts).pack()

        # Measure before placing: the clamp needs the rendered size, and a
        # tooltip on a right-edge control would otherwise hang off the display.
        self.tip.update_idletasks()
        x, y = tooltip_position(
            self.widget.winfo_rootx(), self.widget.winfo_rooty(),
            self.widget.winfo_height(), self.tip.winfo_reqwidth(),
            self.widget.winfo_screenwidth(), self.widget.winfo_screenheight(),
            self.tip.winfo_reqheight())
        self.tip.wm_geometry(f"+{x}+{y}")
        Tooltip._open.add(self)

    def _hide(self, _event=None):
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None
        Tooltip._open.discard(self)

    @classmethod
    def hide_all(cls):
        for tip in list(cls._open):
            tip._hide()


class AddAccountDialog(tk.Toplevel):
    """Asks which provider and what to call the profile.

    ``options`` is ``[(provider, available)]``. An unavailable provider is
    shown and disabled rather than omitted: a missing row reads as a bug,
    while a greyed one with a reason reads as an instruction.
    """

    def __init__(self, parent, options, theme, preselect=None):
        super().__init__(parent)
        self.title("Add Account")
        self.resizable(False, False)
        self.transient(parent)
        self.configure(bg=theme["window"])
        self.result = None

        body = tk.Frame(self, bg=theme["window"], padx=GAP_L, pady=GAP_L)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="PROVIDER", font=theme.caption,
                 bg=theme["window"], fg=theme["muted"]).pack(anchor="w")

        available = [p.id for p, ok in options if ok]
        first_available = available[0] if available else None
        # A preselection only wins if that provider can actually be used;
        # otherwise the dialog would open on a disabled radio button.
        chosen = preselect if preselect in available else first_available
        self.provider_var = tk.StringVar(value=chosen or "")
        for provider, ok in options:
            label = (provider.display_name if ok
                     else f"{provider.display_name}  —  not installed")
            tk.Radiobutton(
                body, text=label, value=provider.id,
                variable=self.provider_var, state="normal" if ok else "disabled",
                font=theme.body, bg=theme["window"], fg=theme["text"],
                selectcolor=theme["card"], activebackground=theme["window"],
                activeforeground=theme["text"], disabledforeground=theme["faint"],
                anchor="w", highlightthickness=0,
            ).pack(fill="x", pady=(GAP_XS, 0))

        tk.Label(body, text="PROFILE NAME", font=theme.caption,
                 bg=theme["window"], fg=theme["muted"]).pack(anchor="w",
                                                             pady=(GAP_M, 0))
        self.name_var = tk.StringVar()
        entry = tk.Entry(body, textvariable=self.name_var, font=theme.body,
                         width=26, relief="flat", highlightthickness=1,
                         highlightbackground=theme["border"],
                         highlightcolor=theme["accent"],
                         bg=theme["card"], fg=theme["text"], insertwidth=2)
        entry.pack(fill="x", pady=(GAP_XS, GAP_M), ipady=GAP_XS + 2)

        tk.Label(body, font=theme.body, bg=theme["window"], fg=theme["muted"],
                 anchor="w", justify="left",
                 text="Browser will open to sign in.",
                 ).pack(fill="x")

        buttons = tk.Frame(body, bg=theme["window"])
        buttons.pack(fill="x", pady=(GAP_M, 0))
        ttk.Button(buttons, text="Cancel", style="Shambles.TButton",
                   command=self.destroy).pack(side="right")
        self.create = ttk.Button(buttons, text="Create", style="Accent.TButton",
                                 command=self._accept)
        self.create.pack(side="right", padx=(0, GAP_S))
        if first_available is None:
            self.create.config(state="disabled")

        entry.focus_set()
        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.wait_window(self)

    def _accept(self):
        if self.provider_var.get():
            self.result = (self.name_var.get(), self.provider_var.get())
        self.destroy()


class LoginDialog(tk.Toplevel):
    """Waits while the vendor's own login runs.

    Shows whatever the command prints, because the line that matters arrives
    first: both vendors print a URL to open by hand when they cannot launch a
    browser, which is normal under WSL and over SSH.

    ``succeeded`` is True only on a clean exit.
    """

    def __init__(self, parent, provider, profile_name, theme):
        super().__init__(parent)
        self.title(f"Sign in to {provider.display_name}")
        self.resizable(False, False)
        self.transient(parent)
        self.configure(bg=theme["window"])
        self.succeeded = False
        self._process = None

        body = tk.Frame(self, bg=theme["window"], padx=GAP_L, pady=GAP_L)
        body.pack(fill="both", expand=True)

        tk.Label(body, text=f"Signing in as '{profile_name}'", font=theme.name,
                 bg=theme["window"], fg=theme["text"], anchor="w").pack(fill="x")
        self.status = tk.Label(
            body, font=theme.body, bg=theme["window"], fg=theme["muted"],
            anchor="w", justify="left", wraplength=360,
            text="Your browser should have opened. Complete the sign-in there.")
        self.status.pack(fill="x", pady=(GAP_XS, GAP_S))

        self.output = tk.Text(body, height=6, width=52, font=theme.body,
                              relief="flat", bg=theme["card"], fg=theme["muted"],
                              highlightthickness=1,
                              highlightbackground=theme["border"], wrap="word")
        self.output.pack(fill="both", expand=True)
        self.output.config(state="disabled")

        buttons = tk.Frame(body, bg=theme["window"])
        buttons.pack(fill="x", pady=(GAP_M, 0))

        # The vendor opens a browser itself when it can. Under WSL and over
        # SSH it cannot, and prints a URL instead -- which was reaching the
        # user as unselectable text in a disabled widget. These appear only
        # once such a URL has actually been printed.
        self._url = None
        self.open_button = ttk.Button(buttons, text="Open sign-in page",
                                      style="Accent.TButton",
                                      command=self._open_url, state="disabled")
        self.open_button.pack(side="left")
        self.copy_button = ttk.Button(buttons, text="Copy link",
                                      style="Shambles.TButton",
                                      command=self._copy_url, state="disabled")
        self.copy_button.pack(side="left", padx=(GAP_S, 0))

        self.close = ttk.Button(buttons, text="Cancel",
                                style="Shambles.TButton", command=self._cancel)
        self.close.pack(side="right")

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self.grab_set()
        self.after(0, lambda: self._start(provider))
        self.wait_window(self)

    def _start(self, provider):
        try:
            self._process = login.LoginProcess(login.command(provider))
            # Both callbacks fire on a worker thread; `after` marshals them
            # back. Touching Tk from that thread would corrupt the interpreter
            # lock and hang the window.
            self._process.start(
                on_line=lambda line: self.after(0, self._append, line),
                on_exit=lambda code: self.after(0, self._finish, code))
        except ShamblesError as exc:
            self._append(str(exc))
            self._finish(1)

    def _offer_url(self, url):
        """Enable the link controls once the vendor has printed an address."""
        self._url = url
        self.open_button.config(state="normal")
        self.copy_button.config(state="normal")
        self.status.config(
            text="Your browser did not open. Use the button below.")

    def _open_url(self):
        if not self._url:
            return
        # webbrowser launches a handler; it makes no network call of its own,
        # so the no-network property tests/test_login.py asserts is untouched.
        import webbrowser
        try:
            opened = webbrowser.open(self._url)
        except Exception:
            opened = False
        if not opened:
            self._copy_url()
            messagebox.showinfo(
                WINDOW_TITLE,
                "No browser could be launched from here, which is usual under "
                "WSL and over SSH.\n\nThe link is on your clipboard — paste "
                "it into a browser to finish signing in.",
                parent=self)

    def _copy_url(self):
        if not self._url:
            return
        self.clipboard_clear()
        self.clipboard_append(self._url)
        self.copy_button.config(text="Copied")
        self.after(1500, lambda: self.copy_button.config(text="Copy link"))

    def _append(self, line):
        try:
            self.output.config(state="normal")
            self.output.insert("end", line + "\n")
            self.output.see("end")
            self.output.config(state="disabled")
        except tk.TclError:
            return  # the dialog closed while a line was in flight

        if self._url is None:
            found = login.find_url(line)
            if found:
                self._offer_url(found)

    def _finish(self, code):
        self.succeeded = (code == 0)
        if self.succeeded:
            self.destroy()
            return
        try:
            self.status.config(text="Sign-in did not complete. The profile was "
                                    "created but has no login yet.")
            self.close.config(text="Close", command=self.destroy)
        except tk.TclError:
            pass

    def _cancel(self):
        if self._process is not None:
            self._process.cancel()
        self.succeeded = False
        self.destroy()


class ShamblesApp(tk.Tk):
    def __init__(self, paths=None, providers=None, platform=None):
        super().__init__()
        self.paths = paths or Paths.real()
        self.providers = (providers if providers is not None
                          else provider_registry.all_providers())
        self.platform = platform or sys.platform
        scale_for_display(self)
        self.theme = Theme(self)
        self.glyph = self.theme.resolve_glyphs(GLYPH_SPEC)
        t = self.theme

        self.title(WINDOW_TITLE)
        self.configure(bg=t["window"])
        self.resizable(False, False)

        # The footer is packed before the card list so it claims the
        # full-width bottom strip. Packed after, it would take a right-hand
        # slab instead and strand the cards in a narrow column.
        footer = tk.Frame(self, bg=t["window"], padx=GAP_L, pady=GAP_L)
        footer.pack(side="bottom", fill="x")
        ttk.Button(footer, text=f"{self.glyph['add']}  Add Account", style="Accent.TButton",
                   command=self.on_add).pack(side="right")
        refresh = ttk.Button(footer, text=self.glyph["refresh"],
                             style="Shambles.TButton", width=3,
                             command=self.refresh)
        refresh.pack(side="left")
        Tooltip(refresh,
                "Re-read what is on disk.\n\n"
                "Local files only — no network call, and nothing a running "
                "session would notice. Usage figures update as you work, so "
                "this picks up whatever has been written since the window "
                "opened.", t)

        self.eject_button = ttk.Button(footer, text="Eject",
                                       style="Shambles.TButton",
                                       command=self.on_eject)
        self.eject_button.pack(side="right", padx=(0, GAP_S))
        Tooltip(self.eject_button,
                "Stop using Shambles and hand every account back as a stock "
                "install. Nothing is deleted.", t)

        # The card list scrolls only when it has to. A fixed-size window that
        # grows with every profile eventually pushes the footer off the bottom,
        # and with no resize handle those buttons cannot be reached again. Two
        # provider groups make that far easier to hit than one.
        self._body = tk.Frame(self, bg=t["window"])
        self._body.pack(fill="both", expand=True)
        body = self._body

        self._viewport = tk.Canvas(body, bg=t["window"], highlightthickness=0,
                                   bd=0)
        self._scrollbar = ttk.Scrollbar(body, orient="vertical",
                                        command=self._viewport.yview)
        self._viewport.configure(yscrollcommand=self._scrollbar.set)
        self._viewport.pack(side="left", fill="both", expand=True)

        self.rows = tk.Frame(self._viewport, bg=t["window"], padx=GAP_L,
                             pady=GAP_L)
        self._rows_window = self._viewport.create_window(
            (0, 0), window=self.rows, anchor="nw")
        self.rows.bind("<Configure>", self._fit_viewport)
        self._viewport.bind(
            "<Configure>",
            lambda e: self._viewport.itemconfigure(self._rows_window,
                                                   width=e.width))
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.bind_all(seq, self._on_wheel)

        self.minsize(WINDOW_WIDTH, MIN_HEIGHT)

        self._pump = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._install_signal_handlers()
        self._pump_signals()
        self._repair_legacy_layout()
        self._migrate_store()
        self.refresh()

    # -- startup repairs --------------------------------------------------

    def _repair_legacy_layout(self):
        """Convert the pre-1.0 symlink layout on sight.

        Deliberately not a choice. That layout gave every account its own copy
        of ~/.claude, so switching hid your session history -- there is no
        version of that anyone wants, and offering it as an option would only
        leave people running the broken arrangement for longer. The merge is
        additive, so there is nothing to undo if it turns out to be unwanted.
        """
        if not migrate.needed(self.paths):
            return
        try:
            plan = migrate.run(self.paths, now_ms=switcher.now_ms())
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
            return

        others = ", ".join(plan.others) or "the other profiles"
        messagebox.showinfo(
            WINDOW_TITLE,
            "Your session history was split across accounts and has been "
            "merged.\n\n"
            f"{plan.merged_files} files brought over from {others} into one "
            f"shared ~/.claude. Every account can now see every session, and "
            f"switching will not hide them again.\n\n"
            f"Nothing was deleted. The old copies are still on disk if you "
            f"want to check them.",
            parent=self)

    def _migrate_store(self):
        """Move a v1.0 store into the provider-scoped layout, unprompted.

        Not offered as a choice, for the same reason the history merge is not:
        the old layout cannot hold a second provider, so staying on it is not
        an option anyone would pick knowingly. Nothing is deleted -- the old
        store stays on disk and the dialog says where.
        """
        if not migrate.store_migration_needed(self.paths):
            return
        try:
            plan = migrate.migrate_store(self.paths)
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
            return
        if not plan.profiles:
            return
        messagebox.showinfo(
            WINDOW_TITLE,
            f"Your profiles moved to {plan.dest}.\n\n"
            f"{len(plan.profiles)} account(s) are now filed under the provider "
            f"they belong to, which is what lets Shambles hold Codex accounts "
            f"alongside Claude ones.\n\n"
            f"Nothing was deleted — the old {plan.source} is still there, and "
            f"you can remove it once you are satisfied.",
            parent=self)

    # -- shutdown ---------------------------------------------------------

    def _install_signal_handlers(self):
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                signal.signal(sig, self._on_signal)
            except (ValueError, OSError):
                pass  # not the main thread; nothing we can install

    def _on_signal(self, _signum, _frame):
        self.on_close()

    def _pump_signals(self):
        """Hand control back to Python on a timer.

        Tk's mainloop blocks inside C waiting on X events, and Python only
        dispatches signal handlers between bytecode instructions. Without this
        tick, Ctrl+C is recorded and never delivered: the window looks frozen,
        the user reaches for Ctrl+Z, and a SIGSTOPped process cannot answer the
        window manager's close request. The result is a window that nothing on
        the desktop can shut. This callback does nothing except exist, which is
        enough to give the interpreter a moment to run pending handlers.
        """
        self._pump = self.after(SIGNAL_POLL_MS, self._pump_signals)

    def on_close(self):
        """The single exit path, shared by the title-bar X and by signals."""
        Tooltip.hide_all()
        if self._pump is not None:
            try:
                self.after_cancel(self._pump)
            except tk.TclError:
                pass
            self._pump = None
        try:
            self.grab_release()
        except tk.TclError:
            pass
        self.quit()

    # -- rendering --------------------------------------------------------

    def refresh(self):
        """Re-read everything from disk. No cached view state, ever."""
        for child in self.rows.winfo_children():
            child.destroy()

        for provider in self.providers:
            # Rotating providers go stale in the background; correct that
            # before reading, so the row and the stash agree.
            switcher.restash_active(self.paths, provider, platform=self.platform)

            current = state.inspect(self.paths, provider, platform=self.platform)
            self._render_group(provider, current)

            override = state.config_dir_override(provider, home=self.paths.home)
            if override:
                self._render_override_banner(provider, override)

    def _render_group(self, provider, current):
        t = self.theme
        heading = tk.Frame(self.rows, bg=t["window"])
        heading.pack(fill="x", pady=(GAP_M, GAP_XS))

        warned = current.kind not in (state.MANAGED, state.UNMANAGED)

        # Three lines rather than one: the provider in small caps, then the
        # active account at title weight, then its address or the warning.
        # A single window-wide header cannot represent N providers, each with
        # its own active account and its own warning state; repeating the
        # treatment per group scales to a third provider without redesign.
        titles = tk.Frame(heading, bg=t["window"])
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(titles, text=provider.display_name.upper(), font=t.caption,
                 bg=t["window"], fg=t["faint"], anchor="w").pack(fill="x")

        live = current.profile if current.kind == state.MANAGED else None
        tk.Label(titles, text=elide(live or "Not signed in", t.title,
                                    WINDOW_WIDTH - 4 * GAP_L),
                 font=t.title if live else t.name,
                 bg=t["window"], fg=t["text"] if live else t["muted"],
                 anchor="w").pack(fill="x")

        status = group_status(current, self.glyph["warn"])
        if status:
            tk.Label(titles, text=status, font=t.body, bg=t["window"],
                     fg=t["warn"] if warned else t["muted"], anchor="w",
                     justify="left",
                     wraplength=WINDOW_WIDTH - 3 * GAP_L).pack(fill="x")

        # Offered only when there is genuinely a login to save. The state
        # alone does not say: a machine with no profiles and no credential is
        # UNMANAGED too, and the button would refuse the moment it was
        # clicked. That refusal is correct -- switcher.save_current_account
        # still raises -- but a control that exists only to say no is worse
        # than no control.
        savable = (current.kind in (state.UNMANAGED, state.UNKNOWN, state.DRIFTED)
                   and self._has_live_login(provider))
        if savable:
            ttk.Button(heading, text="Save current login",
                       style="Shambles.TButton",
                       command=lambda p=provider: self.on_save(p)).pack(side="right")

        # Record the active account's live figures first, so its own card has
        # something to show rather than being the one guaranteed to be blank.
        # A no-op unless the vendor blob is present and provably this account's.
        usage.capture_live(self.paths, provider.id, current.profile,
                           now_ms=switcher.now_ms())

        found = profiles.discover(self.paths, provider, current.profile,
                                  switcher.now_ms(), platform=self.platform)
        usable = login.available(provider)

        # The install hint is additive, not a replacement for the list. Saved
        # profiles stay switchable without the vendor binary -- switching
        # copies a file and runs nothing -- so hiding them would take away
        # something that still works. With no profiles there is no list to sit
        # beside, and the placeholder carries the same message in one box
        # rather than two.
        if not usable and found:
            self._render_missing_vendor(provider)

        if not found:
            self._render_placeholder(provider, usable=usable)
            return

        for profile in found:
            self._render_card(provider, profile)

        if current.kind == state.MISSING_PROFILE:
            ttk.Button(self.rows, text="Forget that profile",
                       style="Shambles.TButton",
                       command=lambda p=provider: self.on_forget_marker(p)
                       ).pack(anchor="w", pady=(GAP_S, 0))

    def _has_live_login(self, provider) -> bool:
        """Whether this provider is signed in right now.

        Read from the store rather than inferred from ``State.live_email``: a
        credential whose identity cannot be resolved -- Claude with no
        ``~/.claude.json`` yet -- is still a login worth saving.
        """
        try:
            store = provider.store(home=self.paths.home, platform=self.platform)
            return store.read() is not None
        except ShamblesError:
            return False

    def _render_placeholder(self, provider, *, usable: bool):
        """The empty slot a first account would fill.

        A dashed outline rather than a line of grey text: it occupies the
        space a profile card will occupy, so the section reads as a place
        something goes rather than as a section that failed to load. Clicking
        it opens Add Account with this provider already chosen, which is the
        only thing anyone would want from an empty slot.

        Drawn on a Canvas because Tk's frame reliefs are all solid; only
        canvas items take a dash pattern.
        """
        t = self.theme
        canvas = tk.Canvas(self.rows, height=PLACEHOLDER_HEIGHT,
                           bg=t["window"], highlightthickness=0, bd=0)
        canvas.pack(fill="x", pady=(0, GAP_S))

        if usable:
            label = f"{self.glyph['add']}   Add a {provider.display_name} account"
            ink = t["accent"]
            canvas.config(cursor="hand2")
            canvas.bind("<Button-1>", lambda _e, p=provider: self.on_add(p))
            Tooltip(canvas, f"Sign in to {provider.display_name} and save it "
                            f"as your first profile here.", t)
        else:
            # Nothing to click: Add Account disables a provider whose CLI is
            # absent, so an inviting box would lead somewhere that refuses.
            label = (f"{login.binary(provider)} is not on your PATH — install "
                     f"it to add {provider.display_name} accounts")
            ink = t["faint"]

        def draw(_event=None):
            canvas.delete("all")
            width = canvas.winfo_width()
            # Inset by one pixel so the dashes are not clipped by the edge.
            canvas.create_rectangle(1, 1, width - 2, PLACEHOLDER_HEIGHT - 2,
                                    dash=PLACEHOLDER_DASH, outline=t["border"])
            canvas.create_text(width // 2, PLACEHOLDER_HEIGHT // 2,
                               text=label, font=t.body, fill=ink)

        # Width is unknown until Tk lays the canvas out, and changes if the
        # window is resized, so the drawing follows the widget rather than
        # being done once at pack time.
        canvas.bind("<Configure>", draw)
        return canvas

    def _expandable_banner(self, *, bg, fg, summary, detail, summary_font=None):
        """One-line summary with Details/Hide for the full explanation.

        Always starts collapsed. ``refresh()`` rebuilds the tree, so expand
        state is never persisted — that is intentional.
        """
        t = self.theme
        card = tk.Frame(self.rows, bg=bg, padx=GAP_M, pady=GAP_M)
        card.pack(fill="x", pady=(0, GAP_S))

        top = tk.Frame(card, bg=bg)
        top.pack(fill="x")
        tk.Label(top, text=summary, font=summary_font or t.body, bg=bg, fg=fg,
                 anchor="w", justify="left",
                 wraplength=WINDOW_WIDTH - 6 * GAP_L).pack(side="left",
                                                          fill="x", expand=True)

        detail_label = tk.Label(
            card, text=detail, font=t.body, bg=bg, fg=fg,
            anchor="w", justify="left",
            wraplength=WINDOW_WIDTH - 4 * GAP_L)
        # Not packed until expanded.

        def toggle():
            if detail_label.winfo_ismapped():
                detail_label.pack_forget()
                toggle_btn.config(text="Details")
            else:
                detail_label.pack(fill="x", pady=(GAP_XS, 0))
                toggle_btn.config(text="Hide")

        toggle_btn = ttk.Button(top, text="Details", style="Shambles.TButton",
                                command=toggle)
        toggle_btn.pack(side="right", padx=(GAP_S, 0))
        return card

    def _render_missing_vendor(self, provider):
        """Say why signing in is unavailable, without hiding what still works.

        'No accounts yet' beside an uninstalled CLI would be a lie of
        omission: the user would only discover the binary is missing at the
        moment they expected a browser.
        """
        t = self.theme
        binary = login.binary(provider)
        self._expandable_banner(
            bg=t["card"], fg=t["muted"],
            summary=f"{binary} not on PATH — can't add accounts",
            detail=(f"Install {binary} to add {provider.display_name} accounts — "
                    f"Shambles runs it to sign you in.\n"
                    f"Switching between accounts you already saved still "
                    f"works."),
        )

    def _render_override_banner(self, provider, target: str):
        """The provider's config-dir variable is set, so a terminal reads a
        tree Shambles never touches. VS Code is unaffected -- neither extension
        host inherits shell environment variables, which is why this tool
        exists."""
        t = self.theme
        name = provider.spec.get("config_dir", {}).get("env", "the config dir")
        # Keep the collapsed line short; full path lives in the expanded body.
        path_hint = target if len(target) <= 40 else target[:37] + "…"
        self._expandable_banner(
            bg=t["chip_gone_bg"], fg=t["chip_gone_fg"],
            summary=f"{self.glyph['warn']}  {name} is set — {path_hint}",
            detail=(f"Your environment points {provider.display_name} at:\n"
                    f"{target}\n\nShambles swaps the login in the default "
                    f"location, so switches will not affect that terminal. "
                    f"VS Code is unaffected. Unset it in your shell profile "
                    f"to use Shambles from the CLI."),
            summary_font=t.name,
        )

    def _fit_viewport(self, _event=None):
        """Size the canvas to its content, up to the screen-height cap.

        Below the cap the window behaves exactly as before -- no scrollbar and
        nothing to scroll.
        """
        self._viewport.configure(scrollregion=self._viewport.bbox("all"))
        needed = self.rows.winfo_reqheight()

        # Chrome is measured, not guessed. A hardcoded allowance is wrong by
        # however much the header and footer differ from it -- and they differ
        # by font, by platform, and by how many warnings are showing. A guess
        # that is too large hands the list less room than it has, which showed
        # up as a scrollbar for a single profile on a 768px display.
        chrome = sum(child.winfo_reqheight() for child in self.winfo_children()
                     if child is not self._body)
        room = int(self.winfo_screenheight() * MAX_HEIGHT_FRACTION) - chrome
        room = max(room, MIN_HEIGHT // 2)
        self._viewport.configure(height=min(needed, room))
        if needed > room:
            self._scrollbar.pack(side="right", fill="y")
        else:
            self._scrollbar.pack_forget()
            self._viewport.yview_moveto(0)

    def _on_wheel(self, event):
        """Wheel scrolling, but only while there is somewhere to scroll."""
        try:
            if not self._scrollbar.winfo_ismapped():
                return
        except tk.TclError:
            return
        down = getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0
        self._viewport.yview_scroll(2 if down else -2, "units")

    def _render_usage(self, parent, bg, profile):
        """Session and weekly figures as full-width rows beneath the identity.

        Rendered only for providers that publish figures at all -- Codex
        exposes nothing readable, and an explanatory line there would be
        explaining an absence that is permanent rather than temporary.
        """
        if not profile.publishes_usage:
            return

        t = self.theme
        now = switcher.now_ms()

        if not profile.usage:
            tk.Label(parent,
                     text=NO_USAGE_ACTIVE if profile.active else NO_USAGE_IDLE,
                     font=t.chip, bg=bg, fg=t["faint"], anchor="w",
                     ).pack(fill="x", pady=(GAP_S, 0))
            return

        stale = profile.usage.is_stale(now)
        age = profile.usage.age_label(now)

        for index, bar in enumerate(profile.usage.bars):
            row = tk.Frame(parent, bg=bg)
            row.pack(fill="x", pady=(GAP_S if index == 0 else GAP_XS, 0))

            tk.Label(row, text=USAGE_LABELS.get(bar.label, bar.label),
                     font=t.chip, bg=bg,
                     fg=t["faint"] if stale else t["muted"],
                     width=BAR_LABEL_WIDTH, anchor="w").pack(side="left")

            # Packed right-to-left: the icon sits outermost, the value inside
            # it, and the track then takes whatever is left.
            info = tk.Label(row, text=self.glyph["info"], font=t.chip, bg=bg,
                            fg=t["faint"], cursor="hand2")
            info.pack(side="right", padx=(GAP_XS, 0))

            tk.Label(row, text=f"{bar.percent}%", font=t.chip, bg=bg,
                     fg=t["faint"] if stale else t["text"],
                     width=BAR_VALUE_WIDTH, anchor="e").pack(side="right",
                                                             padx=(GAP_S, 0))

            track = tk.Frame(row, bg=t["border"], height=BAR_HEIGHT)
            track.pack(side="left", fill="x", expand=True)
            track.pack_propagate(False)
            fill = t["faint"] if stale else t[BAR_FILL[bar.display_severity]]
            if bar.fill > 0:
                tk.Frame(track, bg=fill).place(
                    relwidth=bar.fill, relheight=1.0, x=0, y=0)

            resets = bar.resets_label()
            if not stale:
                freshness = FRESH_NOTE
            elif profile.active:
                freshness = IDLE_NOTE.format(age=age,
                                             refresh=self.glyph["refresh"])
            else:
                freshness = STALE_NOTE.format(age=age)
            # Bound to the icon alone. A whole row lighting up as the pointer
            # crossed it was too eager to live with.
            Tooltip(info, USAGE_TOOLTIP.format(
                label=USAGE_LABELS.get(bar.label, bar.label).capitalize(),
                percent=bar.percent,
                resets=f", resets {resets}" if resets else "",
                freshness=freshness), t)

        if stale and age:
            tk.Label(parent, text=f"as of {age}", font=t.chip, bg=bg,
                     fg=t["faint"], anchor="e").pack(fill="x",
                                                     pady=(GAP_XS, 0))

    def _render_card(self, provider, profile):
        """One profile as a bordered card, accented when it is the active one."""
        t = self.theme
        bg = t["card_active"] if profile.active else t["card"]
        edge = t["border_active"] if profile.active else t["border"]

        shell = tk.Frame(self.rows, bg=edge, highlightthickness=0)
        shell.pack(fill="x", pady=(0, GAP_S))

        # A coloured spine down the left edge marks the active profile far
        # more legibly than a filled/hollow bullet did.
        tk.Frame(shell, bg=edge if profile.active else t["border"],
                 width=ACCENT_BAR_WIDTH).pack(side="left", fill="y")

        card = tk.Frame(shell, bg=bg, padx=GAP_M, pady=GAP_M)
        card.pack(side="left", fill="both", expand=True)

        top = tk.Frame(card, bg=bg)
        top.pack(fill="x")

        # Tk labels do not truncate, so an over-long name stretches the whole
        # window rather than being clipped. The full value stays on hover.
        shown = elide(profile.name, t.name, NAME_MAX_PX)
        name = tk.Label(top, text=shown, font=t.name, bg=bg,
                        fg=t["text"], cursor="hand2")
        name.pack(side="left")
        name.bind("<Double-Button-1>",
                  lambda _e, p=profile: self.on_rename_prompt(provider, p.name))
        hint = name_tooltip(profile)
        Tooltip(name,
                f"{profile.name}\n\n{hint}" if shown != profile.name else hint,
                t)

        if not profile.active:
            # Inactive profiles only. The active one has no remove control at
            # all, so the login in use cannot be deleted by a misclick. The gap
            # between the two is deliberate: one destroys a login and sits
            # beside the button reached most often.
            remove = ttk.Button(top, text=self.glyph["remove"],
                                style="Danger.TButton", width=2,
                                command=lambda p=profile: self.on_remove(provider, p.name))
            remove.pack(side="right")
            ttk.Button(top, text="Switch", style="Switch.TButton",
                       command=lambda p=profile: self.on_switch(provider, p.name)
                       ).pack(side="right", padx=(0, GAP_M))
            Tooltip(remove, f"Remove '{profile.name}'. Its saved login is "
                            "deleted and that account needs a new sign-in.", t)

        bottom = tk.Frame(card, bg=bg)
        bottom.pack(fill="x", pady=(GAP_XS, 0))
        tk.Label(bottom, text=profile.email or "unknown", font=t.body,
                 bg=bg, fg=t["muted"]).pack(side="left")

        label = profiles.expiry_label(profile)
        if label:
            severity = profiles.expiry_severity(profile)
            fg_key, bg_key = CHIP_STYLES[severity]
            chip = tk.Label(bottom, text=f" {label} ", font=t.chip,
                            bg=t[bg_key], fg=t[fg_key], padx=GAP_S, pady=1)
            chip.pack(side="left", padx=(GAP_S, 0))
            Tooltip(chip, chip_tooltip(profile), t)

        self._render_usage(card, bg, profile)

    # -- actions ----------------------------------------------------------

    def _guarded(self, action):
        """Run an action, turning any ShamblesError into a dialog."""
        try:
            action()
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
        finally:
            self.refresh()

    def on_switch(self, provider, name):
        self._guarded(lambda: switcher.switch(self.paths, provider, name,
                                              platform=self.platform))

    def on_rename_prompt(self, provider, old_name):
        new_name = simpledialog.askstring(
            "Rename profile", "New name:", initialvalue=old_name, parent=self)
        if new_name is None or new_name.strip() == old_name:
            return
        self._guarded(lambda: switcher.rename_profile(self.paths, provider,
                                                      old_name, new_name))

    def on_forget_marker(self, provider):
        self._guarded(lambda: switcher.forget_active_marker(self.paths, provider))

    def on_remove(self, provider, name):
        if not messagebox.askyesno(
                "Remove Profile",
                f"Are you sure you want to delete the profile '{name}'? "
                "This will permanently destroy its stored login token.",
                parent=self):
            return
        self._guarded(lambda: switcher.remove_profile(self.paths, provider, name,
                                                      platform=self.platform))

    def on_save(self, provider):
        name = simpledialog.askstring(
            f"Save Current {provider.display_name} Account", "Profile name:",
            initialvalue="Default", parent=self)
        if name is not None:
            self._guarded(lambda: switcher.save_current_account(
                self.paths, provider, name, platform=self.platform))

    def on_eject(self):
        """Hand the machine back as a stock install for every provider."""
        plan = eject.survey(self.paths, self.providers, platform=self.platform)
        parked = sorted({n for e in plan.providers for n in e.other_profiles})
        others = (f"\n\nLogins for {', '.join(parked)} stay on disk — they are "
                  f"only recoverable through a new verification email, so "
                  f"removing them is your call." if parked else "")
        if not messagebox.askokcancel(
                WINDOW_TITLE,
                "Stop using Shambles?\n\n"
                "Every account keeps its current login, history, plugins and "
                f"settings, and goes back to being an ordinary install. "
                f"Nothing is deleted.{others}\n\nContinue?",
                parent=self):
            return
        try:
            done = eject.run(self.paths, self.providers, platform=self.platform)
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
            return
        messagebox.showinfo(WINDOW_TITLE, eject.summary(done), parent=self)
        self.refresh()

    # -- adding an account ------------------------------------------------

    def add_account_options(self):
        """Every provider, paired with whether its CLI can actually be run."""
        return [(provider, login.available(provider))
                for provider in self.providers]

    def stash_after_login(self, provider, name) -> bool:
        """File whatever the vendor just wrote under the new profile.

        Returns whether a credential was found. The vendor writes to its own
        live location; this is the step that makes it a Shambles profile.
        """
        try:
            switcher.stash_live_login(self.paths, provider, name,
                                      platform=self.platform)
        except ShamblesError:
            return False
        return self.paths.credentials(provider.id, name).exists()

    def on_add(self, provider=None):
        """Add an account, optionally starting on a chosen provider.

        ``provider`` comes from clicking a group's empty placeholder, where
        the user has already said which one they mean. The footer button
        passes nothing and the dialog picks the first available.
        """
        options = self.add_account_options()
        dialog = AddAccountDialog(self, options, self.theme,
                                  preselect=provider.id if provider else None)
        if dialog.result is None:
            return
        name, provider_id = dialog.result
        provider = next(p for p in self.providers if p.id == provider_id)

        # Remembered before anything moves. Adding an account has to switch to
        # it -- the vendor writes its credential to the one live location, so
        # the slot must be empty and current before the login runs -- which
        # signs the user out of a working account until the login lands.
        previous = state.inspect(self.paths, provider,
                                 platform=self.platform).profile

        try:
            created = switcher.add_empty_account(self.paths, provider, name,
                                                 platform=self.platform)
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
            self.refresh()
            return

        # The profile is active and empty. The vendor's own command fills it.
        session = LoginDialog(self, provider, created, self.theme)
        if session.succeeded and self.stash_after_login(provider, created):
            messagebox.showinfo(
                WINDOW_TITLE,
                f"'{created}' is signed in and active.\n\n"
                "Start a new session to pick it up — a running one keeps the "
                "token it loaded at startup.",
                parent=self)
        else:
            # No credential arrived, so put the user back where they were
            # rather than leaving them signed out of a working account. The
            # profile is kept, so the sign-in can be retried without naming it
            # again.
            restored = False
            try:
                restored = switcher.abandon_new_account(
                    self.paths, provider, created, previous,
                    platform=self.platform)
            except ShamblesError:
                restored = False

            back = (f"\n\nYou are back on '{previous}' — nothing was lost."
                    if restored else
                    "\n\nSwitching to another profile is safe — nothing was "
                    "lost.")
            messagebox.showwarning(
                WINDOW_TITLE,
                f"'{created}' was created but has no login yet.\n\n"
                f"{provider.login_hint()}{back}",
                parent=self)
        self.refresh()


def run(paths=None) -> int:
    app = ShamblesApp(paths)
    try:
        app.mainloop()
    finally:
        # on_close only leaves the mainloop; the teardown belongs here so it
        # also runs if mainloop exits by any other route.
        Tooltip.hide_all()
        try:
            app.destroy()
        except tk.TclError:
            pass
    return 0
