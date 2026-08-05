"""A compact window for switching Claude Code accounts."""

import tkinter as tk
from tkinter import messagebox, ttk

from . import links, profiles, switcher
from .errors import ShamblesError
from .paths import Paths

WINDOW_TITLE = "Shambles"
PAD = 10


def header_text(paths, state) -> str:
    """One line describing what ~/.claude currently points at."""
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


class Tooltip:
    """Tkinter has no tooltip widget, so here is the smallest useful one."""

    def __init__(self, widget, text):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _event=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 16
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", relief="solid",
                 borderwidth=1, wraplength=300, padx=6, pady=4).pack()

    def _hide(self, _event=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class AddAccountDialog(tk.Toplevel):
    """Name plus the seed-settings checkbox. Returns (name, seed) or None."""

    def __init__(self, parent, active_name):
        super().__init__(parent)
        self.title("Add Account")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None

        body = ttk.Frame(self, padding=PAD)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="Name:").grid(row=0, column=0, sticky="w")
        self.name_var = tk.StringVar()
        entry = ttk.Entry(body, textvariable=self.name_var, width=24)
        entry.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.seed_var = tk.BooleanVar(value=bool(active_name))
        if active_name:
            ttk.Checkbutton(
                body, variable=self.seed_var,
                text=f"Copy settings from '{active_name}'",
            ).grid(row=1, column=0, columnspan=2, sticky="w", pady=(PAD, 0))
            ttk.Label(
                body, foreground="grey",
                text="plugins, permissions, model prefs — not credentials",
            ).grid(row=2, column=0, columnspan=2, sticky="w")

        buttons = ttk.Frame(body)
        buttons.grid(row=3, column=0, columnspan=2, sticky="e", pady=(PAD, 0))
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="left")
        ttk.Button(buttons, text="Create", command=self._accept).pack(
            side="left", padx=(6, 0))

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
        self.title(WINDOW_TITLE)
        self.resizable(False, False)
        self.minsize(420, 0)

        self.header = ttk.Label(self, justify="left", padding=(PAD, PAD, PAD, 0))
        self.header.pack(anchor="w", fill="x")
        ttk.Separator(self).pack(fill="x", pady=(PAD, 0))

        self.rows = ttk.Frame(self, padding=PAD)
        self.rows.pack(fill="both", expand=True)

        ttk.Separator(self).pack(fill="x")
        footer = ttk.Frame(self, padding=PAD)
        footer.pack(fill="x")
        self.save_button = ttk.Button(footer, text="Save Current Account",
                                      command=self.on_save)
        self.save_button.pack(side="left")
        ttk.Button(footer, text="Add Empty Account", command=self.on_add).pack(
            side="left", padx=(6, 0))

        self.refresh()

    # -- rendering --------------------------------------------------------

    def refresh(self):
        """Re-read everything from disk. No cached view state, ever."""
        state = links.inspect(self.paths)
        self.header.config(text=header_text(self.paths, state))
        self.save_button.config(
            state="normal" if state.kind == links.UNMANAGED else "disabled")

        for child in self.rows.winfo_children():
            child.destroy()

        found = profiles.discover(self.paths, state.profile, switcher.now_ms())
        if not found:
            ttk.Label(self.rows, foreground="grey",
                      text="No profiles yet.").grid(row=0, column=0, sticky="w")
            return

        for index, profile in enumerate(found):
            self._render_row(index, profile)

        if state.kind == links.DANGLING:
            ttk.Button(self.rows, text="Remove broken link",
                       command=self.on_remove_link).grid(
                row=len(found) * 2, column=0, sticky="w", pady=(PAD, 0))

    def _render_row(self, index, profile):
        top = index * 2
        marker = "●" if profile.active else "○"
        ttk.Label(self.rows, text=marker).grid(row=top, column=0, sticky="w")

        name_var = tk.StringVar(value=profile.name)
        entry = ttk.Entry(self.rows, textvariable=name_var, width=18)
        entry.grid(row=top, column=1, sticky="w", padx=(4, 0))
        entry.bind("<Return>",
                   lambda _e, p=profile, v=name_var: self.on_rename(p.name, v.get()))
        entry.bind("<FocusOut>",
                   lambda _e, p=profile, v=name_var: self.on_rename(p.name, v.get()))

        if not profile.active:
            ttk.Button(self.rows, text="Switch",
                       command=lambda p=profile: self.on_switch(p.name)).grid(
                row=top, column=2, sticky="e", padx=(PAD, 0))

        detail = ttk.Frame(self.rows)
        detail.grid(row=top + 1, column=1, columnspan=2, sticky="w",
                    pady=(0, PAD))
        ttk.Label(detail, foreground="grey",
                  text=profile.email or "unknown").pack(side="left")
        if profile.warning:
            badge = ttk.Label(detail, text=" ⚠")
            badge.pack(side="left")
            Tooltip(badge, profile.warning)

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

    def on_rename(self, old_name, new_name):
        if (new_name or "").strip() == old_name:
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
        name = self._ask_name("Save Current Account", "Default")
        if name is not None:
            self._guarded(lambda: switcher.save_current_account(self.paths, name))

    def on_add(self):
        state = links.inspect(self.paths)
        dialog = AddAccountDialog(self, state.profile)
        if dialog.result is None:
            return
        name, seed = dialog.result
        self._guarded(
            lambda: switcher.add_empty_account(self.paths, name,
                                               seed_settings=seed))
        messagebox.showinfo(
            WINDOW_TITLE,
            "Profile created and activated.\n\n"
            "Run 'claude' in a terminal, then /login.",
            parent=self)

    def _ask_name(self, title, initial):
        from tkinter import simpledialog
        return simpledialog.askstring(title, "Profile name:",
                                      initialvalue=initial, parent=self)


def run(paths=None) -> int:
    ShamblesApp(paths).mainloop()
    return 0
