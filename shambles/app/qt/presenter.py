"""What the window draws, worked out from a snapshot. No Qt in here.

The QML is deliberately dumb: every word, every enabled flag and every
colour name it shows is decided in this module, from a
:class:`~shambles.app.snapshot.Snapshot` and nothing else. That keeps the
decisions where they can be tested without a display, and it keeps the
window from re-deriving rules the service already owns. This module reads
values the snapshot carries; it never looks at ``state``, ``profiles`` or the
disk itself.

Everything returned is plain ``dict`` / ``list`` / ``str`` / ``bool`` /
numbers, because that is what crosses into QML as a ``QVariant`` without a
registered type.
"""

import datetime

#: The chip on an account that needs the user. Keys are the snapshot's
#: ``status_label``; the wording here is the window's own.
CHIPS = {
    "soon": ("Expires soon", "warn"),
    "needs login": ("Needs sign-in", "bad"),
    "signed out": ("Signed out", "bad"),
}

USAGE_LABELS = {"session": "Session", "week": "Week"}

#: Notices the window draws as something other than a plain banner.
UNSAVED = "unsaved_login"
ELSEWHERE = "signed_in_elsewhere"
MISSING = "missing_profile"
UNREADABLE = "store_unreadable"
OVERRIDE = "config_override"

NOTICE_TONES = {UNREADABLE: "bad", MISSING: "warn",
                "signed_in_elsewhere": "warn", OVERRIDE: "info"}

#: Past this many accounts the header grows a filter box. Below it a filter
#: is one more thing to tab past for no gain.
FILTER_FROM = 7

#: Number keys switch straight to an account. Nine, because there are nine.
KEYS = "123456789"

DATE_FORMAT = "%a %d %b, %H:%M"


def view(snapshot, *, filter_text: str = "") -> dict:
    """The whole window, as data.

    ``filter_text`` narrows the accounts shown; number keys are handed out
    after filtering, so the first match is always ``1``.
    """
    needle = filter_text.strip().casefold()
    total = sum(len(g.accounts) for g in snapshot.groups)
    groups = [_group(g, needle) for g in snapshot.groups]

    keys = {}
    spare = iter(KEYS)
    for group in groups:
        for account in group["others"]:
            if account["action"] == "switch" and account["actionEnabled"]:
                key = next(spare, "")
                account["key"] = key
                if key:
                    keys[key] = {"provider": account["provider"],
                                 "name": account["name"]}

    return {
        "groups": groups,
        "count": total,
        "showFilter": total >= FILTER_FROM,
        "filtering": bool(needle),
        "matches": sum(len(g["others"]) + (1 if g["live"] else 0)
                       for g in groups),
        "keys": keys,
    }


def _group(group, needle: str) -> dict:
    codes = {n.code for n in group.notices}
    settle_to = next((n.account for n in group.notices
                      if n.code == ELSEWHERE and n.account), None)
    if UNREADABLE in codes:
        hold = ("The current login cannot be read, so nothing can be "
                "switched until that is fixed.")
    elif group.can_save:
        # Whoever is signed in is not saved anywhere. Any switch would
        # replace that login with no copy kept, so nothing moves until it
        # is saved. The core refuses most of these itself; the window does
        # not make the user click to find out.
        hold = ("Save the signed-in login above first. Switching now would "
                "replace it with no copy kept.")
    elif settle_to:
        # The live login is saved as settle_to, by its address. Switching
        # anywhere else would file it under the marked account's name, which
        # the core refuses; switching to settle_to is the answer. Its own
        # row stays switchable.
        hold = (f"Switch to {settle_to} above first. Until then this machine "
                "is signed in to an account that is marked as another.")
    else:
        hold = ""
    accounts = [_account(group, a,
                         hold="" if a.name == settle_to else hold)
                for a in group.accounts]
    shown = [a for a in accounts if _matches(a, needle)]
    live = next((a for a in shown if a["live"]), None)
    attention = sum(1 for a in group.accounts if a.needs_login)

    save = None
    settle = None
    notices = []
    for notice in group.notices:
        if notice.code == ELSEWHERE and notice.account:
            # Drawn as a card with the one button that settles it, where the
            # save card would be: this is that state's next step, and the
            # Tk window no longer offers Save here at all.
            settle = {
                "provider": group.provider,
                "account": notice.account,
                "title": notice.message,
                "body": notice.remedy,
                "label": f"Switch to {notice.account}",
            }
            continue
        if notice.code == UNSAVED:
            save = {
                "provider": group.provider,
                "email": group.live_email or "",
                "title": notice.message,
                "body": notice.remedy,
                "suggested": suggest_name(group.live_email,
                                          [a.name for a in group.accounts]),
            }
            continue
        notices.append({
            "code": notice.code,
            "tone": NOTICE_TONES.get(notice.code, "info"),
            "message": notice.message,
            "remedy": notice.remedy,
            "provider": group.provider,
            # A marker for a deleted profile can simply be dropped. Offered
            # beside the notice, never instead of saving a live login.
            "action": "forget" if notice.code == MISSING else "",
            "actionLabel": "Forget that profile"
                           if notice.code == MISSING else "",
            "collapsed": notice.code == OVERRIDE,
        })

    if not group.can_sign_in and group.accounts:
        notices.append({
            "code": "cli_missing", "tone": "info", "provider": group.provider,
            "message": f"{group.cli} is not on your PATH, so accounts cannot "
                       "be added or signed in here.",
            "remedy": "Switching between accounts you already saved still "
                      f"works. Install {group.cli}, then refresh.",
            "action": "", "actionLabel": "", "collapsed": False,
        })

    empty = None
    if not group.accounts and save is None:
        if group.can_sign_in:
            empty = {"kind": "add",
                     "text": f"Add a {group.display_name} account",
                     "detail": ""}
        else:
            empty = {"kind": "cli",
                     "text": f"The {group.cli} command is not on your PATH",
                     "detail": "Shambles runs it to sign you in. Install "
                               f"{group.display_name}, then refresh to add "
                               "accounts here."}

    return {
        "provider": group.provider,
        "title": group.display_name,
        "surfaces": ", ".join(s.label for s in group.surfaces),
        "summary": _summary(group, attention),
        "canSignIn": group.can_sign_in,
        "cli": group.cli,
        "save": save,
        "settle": settle,
        "notices": notices,
        "live": live,
        "others": [a for a in shown if not a["live"]],
        "empty": empty,
        "hidden": bool(needle) and not shown,
    }


def _summary(group, attention: int) -> str:
    count = len(group.accounts)
    if not count:
        if group.can_save:
            return "Signed in, nothing saved"
        return "Not signed in" if group.can_sign_in else "Not installed"
    text = f"{count} account" + ("" if count == 1 else "s")
    if attention:
        text += f" · {attention} need" + ("s" if attention == 1 else "")
        text += " sign-in"
    return text


def _matches(account: dict, needle: str) -> bool:
    if not needle:
        return True
    return (needle in account["name"].casefold()
            or needle in account["email"].casefold())


def _account(group, account, *, hold: str) -> dict:
    chip_text, chip_tone = CHIPS.get(account.status_label, ("", ""))
    usage = [_window(w, live=account.active) for w in account.usage]

    stale = any(w.stale for w in account.usage)
    age = next((w.age_label for w in account.usage if w.age_label), "")

    # The marker alone does not make an account live. With somebody else
    # signed in, the marked account is just another saved one, and badging
    # it Live would put a stranger's session under its name.
    live = account.active and group.state == "managed"

    action, label, enabled, reason = "", "", False, ""
    if account.needs_login:
        # Never Switch on a lapsed login: that installs a dead token and
        # leaves the vendor prompting for the sign-in this button runs.
        action, label = "signin", "Sign in"
        enabled = group.can_sign_in and not hold
        if not group.can_sign_in:
            reason = (f"{group.cli} is not installed, so this account cannot "
                      "be signed in from here.")
    elif not live:
        action, label = "switch", "Switch"
        enabled = not hold
    if hold and action:
        reason = hold

    email = account.email or ""
    return {
        "id": f"{group.provider}/{account.name}",
        "provider": group.provider,
        "providerTitle": group.display_name,
        "name": account.name,
        "email": email,
        "plan": plan_label(account.plan),
        "subtitle": " · ".join(p for p in (email or "Address unknown",
                                           plan_label(account.plan)) if p),
        "initial": (account.name[:1] or "?").upper(),
        "live": live,
        "chip": chip_text,
        "chipTone": chip_tone,
        "action": action,
        "actionLabel": label,
        "actionEnabled": enabled,
        "actionReason": reason,
        "key": "",
        "usage": usage,
        "usageSummary": " · ".join(
            f"{w['percent']}% {w['label'].lower()}" for w in usage),
        "usageNote": (f"as of {age}" if stale and age else ""),
        # Blank space reads as a broken widget; saying why does not. A
        # provider that publishes nothing gets no line at all.
        "usageHint": ("" if usage or not account.publishes_usage
                      else "Usage appears once you run it" if live
                      else "No usage recorded yet"),
        "login": login_line(account),
        "canRemove": not account.active,
    }


def _window(window, *, live: bool) -> dict:
    percent = window.used_percent or 0
    # An old figure is greyed only on an account not in use. On the live one
    # it is still the real number, just one nothing has refreshed lately.
    tone = "dim" if (window.stale and not live) else window.severity
    return {
        "label": USAGE_LABELS.get(window.label, window.label.capitalize()),
        "percent": percent,
        "fill": max(0.0, min(1.0, percent / 100.0)),
        "tone": tone,
        "resets": (f"Resets {window.resets_label}"
                   if window.resets_label else ""),
    }


def plan_label(plan) -> str:
    """``max_5x`` as ``Max 5x``. The vendor's word, made readable."""
    if not plan:
        return ""
    text = str(plan).replace("claude_", "").replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def local_time(ms) -> str:
    """``ms`` as a local date, or ``""`` if it is not a representable one.

    The value is whatever the credential said and is never range-checked,
    so a vendor emitting microseconds lands outside ``datetime``'s range.
    """
    try:
        return datetime.datetime.fromtimestamp(ms / 1000).strftime(DATE_FORMAT)
    except (ValueError, OverflowError, OSError, TypeError):
        return ""


#: For a login whose deadline is fixed at sign-in (Claude's, about thirty
#: days). The same words as the Tk window, so the two cannot disagree.
FIXED_DEADLINE = ("Using the account does not move this date. Sign in again "
                  "before then to keep it.")


def login_line(account) -> str:
    """One sentence on the saved login: its state, its date, what to do.

    The date DD-1 keeps off an account's face. Shown when a row is opened.
    """
    when = local_time(account.expires_at_ms)
    state = account.state
    if state == "absent":
        return "No login saved yet. Sign in to fill it."
    if state == "signed-out":
        return ("This login was cleared, so it cannot sign in. The account "
                "and its details are intact. Sign in again to restore it.")
    if state == "closed":
        return (f"Expired {when}. Sign in again to renew it." if when
                else "Expired. Sign in again to renew it.")
    if state == "closing":
        if account.renewed_by_use:
            return (f"Expires {when}. Switch to it before then to keep it."
                    if when else "Expires soon. Switch to it to keep it.")
        return (f"Expires {when}. {FIXED_DEADLINE}" if when
                else f"Expires soon. {FIXED_DEADLINE}")
    if when:
        if account.renewed_by_use:
            return f"Healthy. Good until {when}. Using the account renews it."
        return f"Healthy. Good until {when}. {FIXED_DEADLINE}"
    return "Healthy."


def suggest_name(email, taken) -> str:
    """A name to pre-fill when saving a login, never one already in use."""
    local = (email or "").partition("@")[0]
    words = [w for w in local.replace(".", " ").replace("_", " ")
             .replace("-", " ").replace("+", " ").split() if w]
    base = " ".join(w.capitalize() for w in words) or "Default"
    used = {name.casefold() for name in taken}
    if base.casefold() not in used:
        return base
    number = 2
    while f"{base} {number}".casefold() in used:
        number += 1
    return f"{base} {number}"


# -- sheets -----------------------------------------------------------------

#: What a settled sign-in is called when it did not simply work. Keyed by the
#: service's error code; anything else falls back to the generic title.
LOGIN_TITLES = {
    "login_other_account": "That was a different account",
    "login_duplicate": "That account is already saved",
    "login_failed": "Sign-in did not finish",
    "login_not_written": "Sign-in did not finish",
    "login_unavailable": "The sign-in command is missing",
}

#: Codes that mean the sign-in itself ran and ended, as opposed to a refusal
#: before anything started (a bad name, say), which belongs on the form.
LOGIN_CODES = frozenset(LOGIN_TITLES) | {"login_cancelled"}


def login_sheet(*, provider_title: str, name: str, email: str,
                previous: str, adding: bool) -> dict:
    """The sheet shown while the vendor's sign-in runs."""
    steps = []
    if previous and previous != name:
        steps.append({"text": f"{previous} is saved and set aside",
                      "state": "done"})
    steps += [
        {"text": f"{provider_title}'s sign-in is starting", "state": "active"},
        {"text": "Waiting for you to finish in your browser", "state": "todo"},
        {"text": f"Save the new login to {name}", "state": "todo"},
    ]
    if email:
        who = (f"Sign in as {email}. If your browser is already signed in as "
               "someone else, use a private window.")
    else:
        who = ("Sign in as the account you want to add. If your browser is "
               "already signed in as a different one, use a private window.")
    if previous and previous != name:
        cancel = f"Cancel puts you back on {previous}. Nothing is lost."
    elif adding:
        cancel = f"Cancel keeps {name} as an empty account you can sign in later."
    else:
        cancel = "Cancel leaves everything as it was."
    return {
        "kind": "login",
        "title": f"Sign in to {name}",
        "subtitle": " · ".join(p for p in (provider_title, email) if p),
        "who": who,
        "steps": steps,
        "url": "",
        "copied": False,
        "cancelNote": cancel,
    }


def login_started(sheet: dict) -> dict:
    """The same sheet once the vendor has said anything at all."""
    steps = [dict(step) for step in sheet["steps"]]
    for index, step in enumerate(steps):
        if step["state"] == "active" and index + 1 < len(steps):
            step["state"] = "done"
            step["text"] = step["text"].replace("is starting", "is ready")
            steps[index + 1]["state"] = "active"
            break
    return {**sheet, "steps": steps}


def result_sheet(result, *, name: str) -> dict:
    """A sign-in that ended some way other than working."""
    error = result.error
    code = error.code if error else ""
    return {
        "kind": "result",
        "tone": "warn" if code in ("login_other_account",
                                   "login_duplicate") else "bad",
        "title": LOGIN_TITLES.get(code, "Sign-in did not finish"),
        "message": error.message if error else "",
        "remedy": error.recovery if error else "",
        "retry": code != "login_unavailable",
        "retryLabel": "Try again",
        "name": name,
    }


def remove_sheet(account: dict) -> dict:
    who = account["email"] or "this account"
    return {
        "kind": "confirm",
        "action": "remove",
        "title": f"Remove {account['name']}?",
        "message": f"This deletes the saved login for {who}. Signing back in "
                   "later needs a new verification email. Nothing else on "
                   "this machine changes.",
        "confirmLabel": "Remove account",
        "provider": account["provider"],
        "name": account["name"],
    }


#: Said only when the service's plan says nothing. The plan's own words
#: come first otherwise: what eject does belongs to the service, and adding a
#: sentence of the window's own in front of them said it twice.
EJECT_FALLBACK = ("Every account keeps its current login, history and "
                  "settings and goes back to being an ordinary install. "
                  "Nothing is deleted.")


def eject_sheet(plan) -> dict:
    parts = [part.strip() for part in plan.warnings if part and part.strip()]
    return {
        "kind": "confirm",
        "action": "eject",
        "title": "Stop using Shambles?",
        "message": "\n\n".join(parts) if parts else EJECT_FALLBACK,
        "confirmLabel": "Eject",
        "provider": "",
        "name": "",
    }


def add_sheet(view_model: dict, *, provider: str = "", error: str = "",
              name: str = "") -> dict:
    """The add-account form. Unavailable providers are shown, disabled.

    A missing row reads as a bug; a greyed one with a reason reads as an
    instruction.
    """
    options = [{
        "id": g["provider"],
        "title": g["title"],
        "detail": g["surfaces"] if g["canSignIn"]
                  else "Not installed on this machine",
        "enabled": g["canSignIn"],
    } for g in view_model["groups"]]
    usable = [o["id"] for o in options if o["enabled"]]
    chosen = provider if provider in usable else (usable[0] if usable else "")
    return {
        "kind": "add",
        "options": options,
        "provider": chosen,
        "name": name,
        "error": error,
        "canSubmit": bool(usable),
    }


def rename_sheet(account: dict, *, error: str = "") -> dict:
    return {
        "kind": "rename",
        "title": f"Rename {account['name']}",
        "provider": account["provider"],
        "name": account["name"],
        "error": error,
    }


def notice_sheet(notices) -> dict:
    """Startup migrations, said once."""
    return {
        "kind": "notice",
        "title": ("Shambles updated how it stores your accounts"
                  if all(n.ok for n in notices)
                  else "An update to your account store could not finish"),
        "tone": "ok" if all(n.ok for n in notices) else "bad",
        "messages": [n.message for n in notices],
    }


def find_account(view_model: dict, provider: str, name: str):
    """The account dict for ``provider``/``name``, or None."""
    for group in view_model["groups"]:
        if group["provider"] != provider:
            continue
        for account in ([group["live"]] if group["live"] else []) \
                + group["others"]:
            if account["name"] == name:
                return account
    return None


def find_group(view_model: dict, provider: str):
    return next((g for g in view_model["groups"]
                 if g["provider"] == provider), None)
