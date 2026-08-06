"""A compact window for switching Claude Code accounts."""

import datetime
import signal
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from . import configjson, eject, migrate, profiles, state, switcher, usage
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

#: Deliberately names no fixed width. Observed refresh windows differ by an
#: order of magnitude across platform and plan samples (docs/token-storage.md),
#: and the chip beside this tooltip already shows the account's real figure.
EXPIRY_TOOLTIP = (
    "Refresh token {verb} {date}.\n\n"
    "This rolling window is what lets Shambles switch to this account without "
    "a verification email. Using the account renews it."
)

RENAME_HINT = "Double-click to rename"

#: Usage chips reuse the expiry palette: Claude Code's "normal" is grey,
#: "warning" amber, anything else red.
USAGE_STYLES = {
    "ok": ("chip_ok_fg", "chip_ok_bg"),
    "soon": ("chip_soon_fg", "chip_soon_bg"),
    "gone": ("chip_gone_fg", "chip_gone_bg"),
}

USAGE_LABELS = {"session": "session", "week": "week"}

USAGE_TOOLTIP = (
    "{label} usage: {percent}%{resets}\n\n"
    "Read from the figures Claude Code caches for this account. {freshness}"
)

FRESH_NOTE = "Updated by Claude Code as you work."
STALE_NOTE = (
    "Last updated {age}, while this account was active — it has not been "
    "signed in since, so the real figure may have moved on. Switch to it to "
    "see a current number."
)

#: Gap between a widget and its tooltip, and the margin kept from screen edges.
TOOLTIP_OFFSET = 12
TOOLTIP_MARGIN = 8


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

#: How often to hand control back to Python so pending signals get dispatched.
SIGNAL_POLL_MS = 150


def header_text(paths, current) -> str:
    """Who is logged in right now.

    Managed profiles return two lines -- name, then email and organisation --
    which the header renders at different weights.
    """
    if current.kind == state.LEGACY_LAYOUT:
        # Startup repairs this automatically, so reaching here means the
        # merge failed and the reason was already shown in a dialog.
        return "⚠ Could not merge your split session history — see the error."
    if current.kind == state.UNMANAGED:
        return "No accounts saved yet — use Save Current Account."
    if current.kind == state.UNKNOWN:
        return "⚠ Not sure which account is live — use Save Current Account."
    if current.kind == state.MISSING_PROFILE:
        return f"⚠ Profile '{current.profile}' is missing from disk."
    if current.kind == state.DRIFTED:
        return (f"⚠ Signed in as {current.live_email}, "
                f"but '{current.profile}' expects {current.expected_email}.")

    account = profiles.resolve_account(paths, current.profile, current.profile)
    email = account.get("emailAddress") or current.live_email or "unknown"
    org = account.get("organizationName")
    suffix = f"  ·  {org}" if org else ""
    return f"{current.profile}\n{email}{suffix}"


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
    """Asks for a profile name. Returns the name, or None if cancelled."""

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

        tk.Label(body, font=theme.body, bg=theme["window"], fg=theme["muted"],
                 anchor="w", justify="left",
                 wraplength=260,
                 text=("Your settings, plugins and session history are shared "
                       "with every account — only the login differs."),
                 ).pack(fill="x")

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
        self.result = self.name_var.get()
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
        self.eject_button = ttk.Button(footer, text="Eject",
                                       style="Shambles.TButton",
                                       command=self.on_eject)
        self.eject_button.pack(side="right", padx=(0, GAP_S))
        Tooltip(self.eject_button,
                "Stop using Shambles and hand ~/.claude back as a stock "
                "Claude Code install. Nothing is deleted.", t)

        self.minsize(WINDOW_WIDTH, 0)

        self._pump = None
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self._install_signal_handlers()
        self._pump_signals()
        self._repair_legacy_layout()
        self.refresh()

    def _repair_legacy_layout(self):
        """Convert the pre-1.0 layout on sight.

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
            f"Nothing was deleted. The old copies are still in "
            f"~/.claude-profiles/ if you want to check them, and you can "
            f"delete those folders once you are satisfied.",
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
        t = self.theme
        current = state.inspect(self.paths)

        lines = header_text(self.paths, current).split("\n")
        managed = current.kind == state.MANAGED
        self.caption.config(text="ACTIVE ACCOUNT" if managed else "STATUS")
        self.title_label.config(
            text=lines[0],
            font=t.title if managed else t.name,
            fg=t["text"] if managed else t["warn"])
        self.subtitle.config(text=lines[1] if len(lines) > 1 else "")

        savable = current.kind in (state.UNMANAGED, state.UNKNOWN, state.DRIFTED)
        self.save_button.config(state="normal" if savable else "disabled")

        for child in self.rows.winfo_children():
            child.destroy()

        found = profiles.discover(self.paths, current.profile, switcher.now_ms())
        if not found:
            tk.Label(self.rows, text="No profiles yet.", font=t.body,
                     bg=t["window"], fg=t["faint"]).pack(anchor="w")
            return

        for profile in found:
            self._render_card(profile)

        override = state.config_dir_override(self.paths)
        if override:
            self._render_override_banner(override)

        if current.kind == state.MISSING_PROFILE:
            ttk.Button(self.rows, text="Forget that profile",
                       style="Shambles.TButton",
                       command=self.on_forget_marker).pack(anchor="w", pady=(GAP_S, 0))

    def _render_override_banner(self, target: str):
        """CLAUDE_CONFIG_DIR is set, so the CLI reads a tree Shambles never
        touches. Switches still work in VS Code -- the extension host does not
        inherit shell environment variables -- but a terminal `claude` would
        silently ignore them, which looks like Shambles doing nothing."""
        t = self.theme
        card = tk.Frame(self.rows, bg=t["chip_gone_bg"], padx=GAP_M, pady=GAP_M)
        card.pack(fill="x", pady=(0, GAP_S))
        tk.Label(card, text="⚠  CLAUDE_CONFIG_DIR is set", font=t.name,
                 bg=t["chip_gone_bg"], fg=t["chip_gone_fg"], anchor="w",
                 justify="left").pack(fill="x")
        tk.Label(card, bg=t["chip_gone_bg"], fg=t["chip_gone_fg"], font=t.body,
                 anchor="w", justify="left",
                 wraplength=WINDOW_WIDTH - 4 * GAP_L,
                 text=(f"Your environment points the claude CLI at:\n{target}\n\n"
                       "Shambles swaps the login inside ~/.claude, so switches "
                       "will not affect that terminal. VS Code is unaffected — "
                       "the extension host does not read shell variables.\n\n"
                       "Unset it in your shell profile to use Shambles from the "
                       "CLI."),
                 ).pack(fill="x", pady=(GAP_XS, 0))

    def _render_usage(self, card, bg, profile):
        """Session and weekly figures, or nothing at all.

        Nothing is the honest answer more often than it looks: a switch clears
        the cache so Claude Code refetches, and a profile that has never been
        active has none stashed. An empty row beats a number that might be
        wrong.
        """
        if not profile.usage:
            return
        t = self.theme
        now = switcher.now_ms()
        stale = profile.usage.is_stale(now)
        age = profile.usage.age_label(now)

        row = tk.Frame(card, bg=bg)
        row.pack(fill="x", pady=(GAP_XS + 2, 0))

        for bar in profile.usage.bars:
            fg_key, bg_key = USAGE_STYLES.get(bar.severity, USAGE_STYLES["gone"])
            # A stale figure loses its colour: an amber chip that is a day old
            # says "act now" about a number nobody has checked since.
            fg = t["muted"] if stale else t[fg_key]
            chip_bg = t["card"] if stale else t[bg_key]
            label = f" {USAGE_LABELS.get(bar.label, bar.label)} {bar.percent}% "
            chip = tk.Label(row, text=label, font=t.chip, bg=chip_bg, fg=fg,
                            padx=GAP_XS, pady=1)
            chip.pack(side="left", padx=(0, GAP_XS))

            resets = bar.resets_label()
            Tooltip(chip, USAGE_TOOLTIP.format(
                label=USAGE_LABELS.get(bar.label, bar.label).capitalize(),
                percent=bar.percent,
                resets=f", resets {resets}" if resets else "",
                freshness=STALE_NOTE.format(age=age) if stale else FRESH_NOTE,
            ), t)

        if stale and age:
            tk.Label(row, text=age, font=t.chip, bg=bg,
                     fg=t["faint"]).pack(side="left")

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
            # Inactive profiles only. The active one has no ✕ at all, so the
            # login you are currently using cannot be deleted by a misclick.
            remove = ttk.Button(top, text="✕", style="Danger.TButton", width=2,
                                command=lambda p=profile: self.on_remove(p.name))
            # Sits inboard of Switch: the rightmost slot is the easiest to hit,
            # and that should belong to the action used constantly rather than
            # the one that destroys a login. The gap is deliberate too.
            remove.pack(side="right", padx=(0, GAP_M))
            Tooltip(remove, f"Remove '{profile.name}'. Its saved login is "
                            "deleted and that account needs a new /login.", t)

        bottom = tk.Frame(card, bg=bg)
        bottom.pack(fill="x", pady=(GAP_XS, 0))
        tk.Label(bottom, text=profile.email or "unknown", font=t.body,
                 bg=bg, fg=t["muted"]).pack(side="left")

        self._render_usage(card, bg, profile)

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

    def on_forget_marker(self):
        self._guarded(lambda: switcher.forget_active_marker(self.paths))

    def on_remove(self, name):
        if not messagebox.askyesno(
                "Remove Profile",
                f"Are you sure you want to delete the profile '{name}'? "
                "This will permanently destroy its stored login token.",
                parent=self):
            return
        self._guarded(lambda: switcher.remove_profile(self.paths, name))

    def on_eject(self):
        """Hand the machine back as a stock Claude Code install."""
        plan = eject.survey(self.paths)
        others = (f"\n\nLogins for {', '.join(plan.other_profiles)} stay on "
                  f"disk — they are only recoverable through a new "
                  f"verification email, so removing them is your call."
                  if plan.other_profiles else "")
        if not messagebox.askokcancel(
                WINDOW_TITLE,
                "Stop using Shambles?\n\n"
                "~/.claude keeps its current login, history, plugins and "
                "settings, and goes back to being an ordinary Claude Code "
                f"install. Nothing is deleted.{others}\n\nContinue?",
                parent=self):
            return
        try:
            done = eject.run(self.paths)
        except ShamblesError as exc:
            messagebox.showerror(WINDOW_TITLE, str(exc), parent=self)
            return
        messagebox.showinfo(WINDOW_TITLE, eject.summary(done), parent=self)
        self.refresh()

    def on_save(self):
        name = simpledialog.askstring("Save Current Account", "Profile name:",
                                      initialvalue="Default", parent=self)
        if name is not None:
            self._guarded(lambda: switcher.save_current_account(self.paths, name))

    def on_add(self):
        current = state.inspect(self.paths)
        dialog = AddAccountDialog(self, current.profile, self.theme)
        if dialog.result is None:
            return
        self._guarded(
            lambda: switcher.add_empty_account(self.paths, dialog.result))
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
