"""A compact window for switching Claude Code accounts."""

import datetime
import signal
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import links, profiles, switcher
from .errors import ShamblesError
from .paths import Paths
from .theme import (ACCENT_BAR_WIDTH, GAP_L, GAP_M, GAP_S, GAP_XS,
                    WINDOW_WIDTH, Theme, scale_for_display)

WINDOW_TITLE = "Shambles"

#: Chip colour keys per expiry severity, resolved against the palette.
CHIP_STYLES = {
    profiles.EXPIRY_OK: ("chip_ok_fg", "chip_ok_bg"),
    profiles.EXPIRY_SOON: ("chip_soon_fg", "chip_soon_bg"),
    profiles.EXPIRY_GONE: ("chip_gone_fg", "chip_gone_bg"),
}

EXPIRY_TOOLTIP = (
    "Refresh token {verb} {date}.\n\n"
    "This is the rolling 30-day window that lets Shambles switch to this "
    "account without a verification email. Using the account renews it."
)

RENAME_HINT = "Double-click to rename"

#: How often to hand control back to Python so pending signals get dispatched.
SIGNAL_POLL_MS = 150


def header_text(paths, state) -> str:
    """What ~/.claude currently points at.

    Managed profiles return two lines -- name, then email and organisation --
    which the header renders at different weights.
    """
    if state.kind == links.UNMANAGED:
        return "~/.claude is not managed yet — use Save Current Account."
    if state.kind == links.MISSING:
        return "~/.claude is not set up — use Add Empty Account."
    if state.kind == links.FOREIGN:
        return f"⚠ ~/.claude points outside Shambles: {state.target}"
    if state.kind == links.DANGLING:
        return f"⚠ Broken link — '{state.profile}' is missing from disk."

    account = profiles.resolve_account(paths, state.profile, state.profile)
    email = account.get("emailAddress") or "unknown"
    org = account.get("organizationName")
    suffix = f"  ·  {org}" if org else ""
    return f"{state.profile}\n{email}{suffix}"


def expiry_tooltip(profile) -> str:
    """The exact date behind the short countdown chip."""
    when = datetime.datetime.fromtimestamp(profile.refresh_expires_ms / 1000)
    verb = "expired" if profile.days_left < 0 else "expires"
    return EXPIRY_TOOLTIP.format(verb=verb, date=when.strftime("%d %b %Y, %H:%M"))


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
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        # refresh() destroys every row widget on each switch. Without this a
        # tooltip visible at that moment never sees <Leave> and is orphaned.
        widget.bind("<Destroy>", self._hide, add="+")

    def _show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        opts = {}
        if self.theme:
            opts = {"font": self.theme.body, "bg": "#22242a", "fg": "#f4f5f7"}
        tk.Label(self.tip, text=self.text, justify="left", relief="flat",
                 wraplength=340, padx=GAP_S, pady=GAP_XS + 2, **opts).pack()
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
    """Name plus the seed-settings checkbox. Returns (name, seed) or None."""

    def __init__(self, parent, active_name, theme):
        super().__init__(parent)
        self.title("Add Account")
        self.resizable(False, False)
        self.transient(parent)
        self.configure(bg=theme["window"])
        self.result = None

        body = tk.Frame(self, bg=theme["window"], padx=GAP_L, pady=GAP_L)
        body.pack(fill="both", expand=True)

        tk.Label(body, text="PROFILE NAME", font=theme.caption,
                 bg=theme["window"], fg=theme["muted"]).pack(anchor="w")
        self.name_var = tk.StringVar()
        entry = tk.Entry(body, textvariable=self.name_var, font=theme.body,
                         width=26, relief="flat", highlightthickness=1,
                         highlightbackground=theme["border"],
                         highlightcolor=theme["accent"],
                         bg=theme["card"], fg=theme["text"], insertwidth=2)
        entry.pack(fill="x", pady=(GAP_XS, GAP_M), ipady=GAP_XS + 2)

        self.seed_var = tk.BooleanVar(value=bool(active_name))
        if active_name:
            tk.Checkbutton(
                body, variable=self.seed_var, font=theme.body,
                text=f"Copy settings from '{active_name}'",
                bg=theme["window"], fg=theme["text"],
                activebackground=theme["window"], selectcolor=theme["card"],
                highlightthickness=0, anchor="w",
            ).pack(fill="x")
            tk.Label(body, font=theme.body, bg=theme["window"], fg=theme["muted"],
                     text="plugins, permissions, model prefs — not credentials",
                     ).pack(anchor="w", padx=(GAP_L, 0))

        buttons = tk.Frame(body, bg=theme["window"])
        buttons.pack(fill="x", pady=(GAP_M, 0))
        ttk.Button(buttons, text="Cancel", style="Shambles.TButton",
                   command=self.destroy).pack(side="right")
        ttk.Button(buttons, text="Create", style="Accent.TButton",
                   command=self._accept).pack(side="right", padx=(0, GAP_S))

        entry.focus_set()
        self.bind("<Return>", lambda _e: self._accept())
        self.bind("<Escape>", lambda _e: self.destroy())
        self.grab_set()
        self.wait_window(self)

    def _accept(self):
        self.result = (self.name_var.get(), self.seed_var.get())
        self.destroy()


class ShamblesApp(tk.Tk):
    def __init__(self, paths=None):
        super().__init__()
        self.paths = paths or Paths.real()
        scale_for_display(self)
        self.theme = Theme(self)
        t = self.theme

        self.title(WINDOW_TITLE)
        self.configure(bg=t["window"])
        self.resizable(False, False)

        # -- header ------------------------------------------------------
        head = tk.Frame(self, bg=t["window"], padx=GAP_L, pady=GAP_L)
        head.pack(fill="x")
        self.caption = tk.Label(head, text="ACTIVE PROFILE", font=t.caption,
                                bg=t["window"], fg=t["faint"], anchor="w")
        self.caption.pack(fill="x")
        self.title_label = tk.Label(head, font=t.title, bg=t["window"],
                                    fg=t["text"], anchor="w", justify="left",
                                    wraplength=WINDOW_WIDTH - 2 * GAP_L)
        self.title_label.pack(fill="x", pady=(GAP_XS, 0))
        self.subtitle = tk.Label(head, font=t.body, bg=t["window"],
                                 fg=t["muted"], anchor="w", justify="left")
        self.subtitle.pack(fill="x")

        # -- profile cards -----------------------------------------------
        self.rows = tk.Frame(self, bg=t["window"], padx=GAP_L)
        self.rows.pack(fill="both", expand=True)

        # -- footer ------------------------------------------------------
        footer = tk.Frame(self, bg=t["window"], padx=GAP_L, pady=GAP_L)
        footer.pack(fill="x")
        self.save_button = ttk.Button(footer, text="Save Current Account",
                                      style="Shambles.TButton", command=self.on_save)
        self.save_button.pack(side="left")
        ttk.Button(footer, text="＋  Add Account", style="Accent.TButton",
                   command=self.on_add).pack(side="right")

        self.minsize(WINDOW_WIDTH, 0)

        self._pump = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._install_signal_handlers()
        self._pump_signals()
        self.refresh()

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
        t = self.theme
        state = links.inspect(self.paths)

        lines = header_text(self.paths, state).split("\n")
        managed = state.kind == links.MANAGED
        self.caption.config(text="ACTIVE PROFILE" if managed else "STATUS")
        self.title_label.config(
            text=lines[0],
            font=t.title if managed else t.name,
            fg=t["text"] if managed else t["warn"])
        self.subtitle.config(text=lines[1] if len(lines) > 1 else "")

        self.save_button.config(
            state="normal" if state.kind == links.UNMANAGED else "disabled")

        for child in self.rows.winfo_children():
            child.destroy()

        found = profiles.discover(self.paths, state.profile, switcher.now_ms())
        if not found:
            tk.Label(self.rows, text="No profiles yet.", font=t.body,
                     bg=t["window"], fg=t["faint"]).pack(anchor="w")
            return

        for profile in found:
            self._render_card(profile)

        if state.kind == links.DANGLING:
            ttk.Button(self.rows, text="Remove broken link",
                       style="Shambles.TButton",
                       command=self.on_remove_link).pack(anchor="w", pady=(GAP_S, 0))

    def _render_card(self, profile):
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

        name = tk.Label(top, text=profile.name, font=t.name, bg=bg,
                        fg=t["text"], cursor="hand2")
        name.pack(side="left")
        name.bind("<Double-Button-1>", lambda _e, p=profile: self.on_rename_prompt(p.name))
        Tooltip(name, RENAME_HINT, t)

        if profile.active:
            tk.Label(top, text="ACTIVE", font=t.caption, bg=bg,
                     fg=t["accent"]).pack(side="left", padx=(GAP_S, 0))
        else:
            ttk.Button(top, text="Switch", style="Switch.TButton",
                       command=lambda p=profile: self.on_switch(p.name)).pack(side="right")

        bottom = tk.Frame(card, bg=bg)
        bottom.pack(fill="x", pady=(GAP_XS, 0))
        tk.Label(bottom, text=profile.email or "unknown", font=t.body,
                 bg=bg, fg=t["muted"]).pack(side="left")

        label = profiles.expiry_label(profile)
        if label:
            fg_key, bg_key = CHIP_STYLES[profiles.expiry_severity(profile)]
            chip = tk.Label(bottom, text=f" {label} ", font=t.chip,
                            bg=t[bg_key], fg=t[fg_key], padx=GAP_S, pady=1)
            chip.pack(side="left", padx=(GAP_S, 0))
            Tooltip(chip, expiry_tooltip(profile), t)

        if profile.warning:
            badge = tk.Label(bottom, text="⚠", font=t.body, bg=bg, fg=t["warn"])
            badge.pack(side="left", padx=(GAP_S, 0))
            Tooltip(badge, profile.warning, t)

    # -- actions ----------------------------------------------------------

    def _guarded(self, action):
        """Run an action, turning any ShamblesError into a dialog."""
        try:
            action()
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
        finally:
            self.refresh()

    def on_switch(self, name):
        self._guarded(lambda: switcher.switch(self.paths, name))

    def on_rename_prompt(self, old_name):
        new_name = simpledialog.askstring(
            "Rename profile", "New name:", initialvalue=old_name, parent=self)
        if new_name is None or new_name.strip() == old_name:
            return
        self._guarded(
            lambda: switcher.rename_profile(self.paths, old_name, new_name))

    def on_remove_link(self):
        self._guarded(lambda: switcher.remove_dangling_link(self.paths))

    def on_save(self):
        if switcher.crosses_filesystem(self.paths):
            proceed = messagebox.askokcancel(
                WINDOW_TITLE,
                "~/.claude is on a different filesystem from your home "
                "directory, so this will be a slow copy rather than an "
                "instant move.\n\nContinue?",
                parent=self)
            if not proceed:
                return
        name = simpledialog.askstring("Save Current Account", "Profile name:",
                                      initialvalue="Default", parent=self)
        if name is not None:
            self._guarded(lambda: switcher.save_current_account(self.paths, name))

    def on_add(self):
        state = links.inspect(self.paths)
        dialog = AddAccountDialog(self, state.profile, self.theme)
        if dialog.result is None:
            return
        name, seed = dialog.result
        self._guarded(
            lambda: switcher.add_empty_account(self.paths, name, seed_settings=seed))
        messagebox.showinfo(
            WINDOW_TITLE,
            "Profile created and activated.\n\n"
            "Run 'claude' in a terminal, then /login.",
            parent=self)


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
