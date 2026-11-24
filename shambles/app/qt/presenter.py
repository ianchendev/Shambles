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
import re
import time

from .. import snapshot as timing

#: D2: a row has one button and at most one badge, and the badge carries
#: what used to be a second button or a sentence. ``kind`` is what the QML
#: keys off; ``action`` is what clicking the badge does, if anything.
NO_BADGE = {"kind": "", "text": "", "icon": "", "tone": "", "tip": "",
            "action": ""}
MOST_ROOM = {"kind": "room", "text": "Most room", "icon": "", "tone": "info",
             "tip": "The account with the most room left in both limits.",
             "action": ""}
#: D3: once the live account has used this much of either limit, the parked
#: account with the most room left is pointed out. A hint: Shambles never
#: switches by itself.
ROOM_FROM = 80

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
#: D4: a sign-in deadline gets a line of its own in the group only this
#: close to it. Before then the row's badge says it.
STRIP_WITHIN_MS = 3 * DAY_MS
DAY_FORMAT = "%a %d %b"

USAGE_LABELS = {"session": "Session", "week": "Week"}

#: What a limit is called where there is room to say what it is.
LIMIT_NAMES = {"session": "5-hour limit", "week": "Weekly limit"}

#: Notices the window draws as something other than a plain banner.
#: The snapshot's state for a live login that is not the marked account's.
DRIFTED = "drifted"
UNSAVED = "unsaved_login"
ELSEWHERE = "signed_in_elsewhere"
SIGN_IN_SOON = "sign_in_soon"
MISSING = "missing_profile"
UNREADABLE = "store_unreadable"
OVERRIDE = "config_override"

NOTICE_TONES = {UNREADABLE: "bad", MISSING: "warn", "sign_in_soon": "warn",
                "signed_in_elsewhere": "warn", OVERRIDE: "info"}

#: Past this many accounts the header grows a filter box. Below it a filter
#: is one more thing to tab past for no gain.
FILTER_FROM = 7

#: Ctrl+1 to Ctrl+9 (D8): the Nth account down the window, by its place
#: among every saved account, so a number never moves to another account
#: when a switch or a lapsed login changes the rows. Nine, because there
#: are nine.
KEYS = "123456789"

DATE_FORMAT = "%a %d %b, %H:%M"


def view(snapshot, *, filter_text: str = "", now_ms: int | None = None,
         hidden_deadlines=frozenset()) -> dict:
    """The whole window, as data.

    ``filter_text`` narrows the accounts shown. Number keys belong to each
    account's place among all of them, so filtering does not renumber.

    ``now_ms`` is the moment the window is drawn, which can be long after the
    snapshot was read: a limit can reset, and a reading grow old, while the
    window sits open. Defaults to the clock.

    ``hidden_deadlines`` holds ``provider/account`` for each deadline line
    the user closed today (D4).
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    needle = filter_text.strip().casefold()
    total = sum(len(g.accounts) for g in snapshot.groups)
    places = iter(KEYS)
    numbers = {f"{g.provider}/{a.name}": next(places, "")
               for g in snapshot.groups for a in g.accounts}
    groups = [_group(g, needle, now_ms, numbers=numbers,
                     hidden=frozenset(hidden_deadlines))
              for g in snapshot.groups]

    # What Ctrl+N does: the account's own button, where it has a working
    # one. Only accounts on show; nothing for the live one.
    keys = {}
    for group in groups:
        for account in group["others"]:
            if account["key"] and account["action"] \
                    and account["actionEnabled"]:
                keys[account["key"]] = {"provider": account["provider"],
                                        "name": account["name"],
                                        "action": account["action"]}

    return {
        "groups": groups,
        "count": total,
        "showFilter": total >= FILTER_FROM,
        "filtering": bool(needle),
        "matches": sum(len(g["others"]) + (1 if g["live"] else 0)
                       for g in groups),
        "keys": keys,
    }


def _group(group, needle: str, now_ms: int, *, numbers, hidden) -> dict:
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
                "is signed in to an account that is marked as another."
                if group.state == DRIFTED else
                f"Use {settle_to} above first. Until then this machine is "
                "signed in to an account that is not marked in use.")
    else:
        hold = ""
    accounts = [_account(group, a,
                         hold="" if a.name == settle_to else hold,
                         now_ms=now_ms,
                         key=numbers.get(f"{group.provider}/{a.name}", ""))
                for a in group.accounts]
    _most_room(accounts)
    shown = [a for a in accounts if _matches(a, needle)]
    live = next((a for a in shown if a["live"]), None)
    attention = sum(1 for a in group.accounts if a.needs_login)

    save = None
    settle = None
    deadline = None
    notices = []
    names = [a.name for a in group.accounts]

    def said(text):
        # The service's words as the window writes them (D9): no quotes
        # round names, the tool by its name.
        return as_the_window_says(text or "", tool=group.display_name,
                                  names=names)

    for notice in group.notices:
        if notice.code == SIGN_IN_SOON:
            # D4: a line of its own in the last days, the row's badge
            # before then; never the paragraph.
            if deadline is None:
                deadline = _deadline(group, notice, accounts, now_ms, hidden)
            continue
        if notice.code == ELSEWHERE and notice.account:
            # Drawn as a card with the one button that settles it, where the
            # save card would be: this is that state's next step, and the
            # Tk window no longer offers Save here at all.
            settle = {
                "provider": group.provider,
                "account": notice.account,
                "title": said(notice.message),
                "body": said(notice.remedy),
                # Nothing is marked to switch away from when the marked
                # account was deleted or the marker cleared.
                "label": (f"Switch to {notice.account}"
                          if group.state == DRIFTED
                          else f"Use {notice.account}"),
            }
            continue
        if notice.code == UNSAVED:
            # Who, then that it is not saved; why that matters on hover.
            # The service's message also names the marked account, which
            # adds nothing next to the field that saves this one.
            save = {
                "provider": group.provider,
                "email": group.live_email or "",
                "title": (f"Signed in as {group.live_email}"
                          if group.live_email else said(notice.message)),
                "body": "Not saved yet",
                "tip": said(notice.remedy),
                "suggested": suggest_name(group.live_email,
                                          [a.name for a in group.accounts]),
            }
            continue
        if notice.code == MISSING:
            # A marker for a deleted profile can simply be dropped. Offered
            # beside the notice, never instead of saving a live login.
            action, action_label = "forget", "Forget the missing account"
        else:
            action, action_label = "", ""
        notices.append({
            "code": notice.code,
            "tone": NOTICE_TONES.get(notice.code, "info"),
            "message": said(notice.message),
            "remedy": said(notice.remedy),
            "provider": group.provider,
            "account": notice.account or "",
            "action": action,
            "actionLabel": action_label,
            "collapsed": notice.code == OVERRIDE,
        })

    # D6: a tool that is not installed is one line in the heading, with
    # no card and no notice.
    missing = not group.can_sign_in
    if not missing:
        missing_tip = ""
    elif group.accounts:
        missing_tip = (f"Shambles runs the {group.cli} command to sign "
                       "accounts in, and it is not installed here. Switching "
                       "between the accounts already saved still works.")
    else:
        missing_tip = (f"Shambles runs the {group.cli} command to sign "
                       f"accounts in. Install {group.display_name}, and this "
                       "section fills in by itself.")

    empty = None
    if not group.accounts and save is None and group.can_sign_in:
        empty = {"kind": "add",
                 "text": f"Add a {group.display_name} account",
                 "detail": ""}

    return {
        "provider": group.provider,
        "title": group.display_name,
        "surfaces": ", ".join(s.label for s in group.surfaces),
        "surfacesTip": _reach(group),
        "summary": _summary(group, attention),
        "missing": missing,
        "missingTip": missing_tip,
        # D1: a reason every row shares, said once above them.
        "hold": hold if any(a["action"] and not a["live"]
                            and a["name"] != settle_to
                            for a in accounts) else "",
        "deadline": deadline,
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


def _reach(group) -> str:
    """Where a switch in this group takes effect, for the i by its name."""
    places = [("the terminal" if s.label.casefold() == "terminal"
               else s.label) for s in group.surfaces]
    if not places:
        return ""
    where = [f"in {place}" for place in places]
    said = where[0] if len(where) == 1 else \
        ", ".join(where[:-1]) + " and " + where[-1]
    return f"Switching changes the {group.display_name} account {said}."


def _deadline(group, notice, accounts, now_ms, hidden):
    """D4's line for the deadline ``notice`` is about, or None."""
    account = next((a for a in group.accounts if a.name == notice.account),
                   None)
    if account is None or account.expires_at_ms is None:
        return None
    if account.expires_at_ms - now_ms > STRIP_WITHIN_MS:
        return None
    key = f"{group.provider}/{account.name}"
    if key in hidden:
        return None
    row = next(a for a in accounts if a["name"] == account.name)
    day = local_time(account.expires_at_ms, DAY_FORMAT)
    return {
        "key": key,
        "provider": group.provider,
        "account": account.name,
        "text": f"{account.name} stops working {day}".strip(),
        # Apart from the name, so a narrow window cuts the name, never the
        # date; the short form for when even that is tight.
        "when": f"stops working {day}".strip(),
        "whenShort": f"stops {day}".strip(),
        "tip": as_the_window_says(
            " ".join(p for p in (notice.message, notice.remedy) if p),
            tool=group.display_name, names=[a.name for a in group.accounts]),
        "canSignIn": bool(row["signIn"] and row["signInEnabled"]),
    }


def _fullest(account: dict):
    """How much of its fullest limit an account has used, or None.

    A limit that has reset since its figure was read counts as empty.
    """
    used = [0 if w["state"] == "reset" else w["percent"]
            for w in account["usage"]]
    return max(used) if used else None


def _most_room(accounts) -> None:
    """D3: badge the parked account with the most room, once the live one
    is past ROOM_FROM in either limit. Only one Switch could reach, and only
    if it really has more room than the live account."""
    live = next((a for a in accounts if a["live"]), None)
    used = _fullest(live) if live else None
    if used is None or used < ROOM_FROM:
        return
    choices = [a for a in accounts
               if not a["live"] and a["action"] == "switch"
               and a["actionEnabled"] and not a["badge"]["kind"]
               and _fullest(a) is not None]
    best = min(choices, key=_fullest, default=None)
    if best is not None and _fullest(best) < used:
        best["badge"] = dict(MOST_ROOM)


def _summary(group, attention: int) -> str:
    count = len(group.accounts)
    if not count:
        if group.can_save:
            return "Signed in, nothing saved"
        return "Not signed in" if group.can_sign_in else "Not installed"
    text = f"{count} account" + ("" if count == 1 else "s")
    if attention:
        # D9: one word for a login that has ended, everywhere.
        text += f" · {attention} signed out"
    if not group.can_sign_in:
        text += " · Not installed"
    return text


def _matches(account: dict, needle: str) -> bool:
    if not needle:
        return True
    return (needle in account["name"].casefold()
            or needle in account["email"].casefold())


def _account(group, account, *, hold: str, now_ms: int, key: str) -> dict:
    usage = [_window(w, live=account.active, now_ms=now_ms)
             for w in account.usage]

    # The marker alone does not make an account live. With somebody else
    # signed in, the marked account is just another saved one, and badging
    # it Live would put a stranger's session under its name.
    live = account.active and group.state == "managed"

    # A sign-in is offered for a login that has lapsed, and for one that
    # still works but that only a new sign-in keeps past its fixed date
    # (sign_in_due: a Claude login near its deadline). The first can only be
    # signed in, and that is its button. The second can still be switched
    # to, so Switch stays its one button and the sign-in rides on its badge
    # (D2) -- two buttons are what pushed the row's menu off the card (F3).
    due = account.sign_in_due and not account.needs_login
    sign_in = (account.needs_login or due) and group.can_sign_in
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
    if account.needs_login:
        badge = {"kind": "signedout", "text": "Signed out", "icon": "",
                 "tone": "bad", "tip": login_line(account), "action": ""}
    elif due:
        can = sign_in and not hold
        when = local_time(account.expires_at_ms)
        left = _left(account.expires_at_ms, now_ms)
        badge = {"kind": "due", "tone": "warn", "icon": "clock",
                 "text": left or "Soon",
                 "tip": (f"Sign in by {when}." if when else "Sign in soon.")
                 + (" Click to sign in again now." if can else ""),
                 "action": "signin" if can else ""}
    elif account.status_label == "soon":
        # Closing, but kept by using it (Codex): the nudge DD-1 asks for,
        # with what to do on hover. Switching is the fix, so no click.
        left = _left(account.expires_at_ms, now_ms)
        badge = {"kind": "soon", "tone": "warn", "icon": "clock",
                 "text": left or "Soon",
                 "tip": login_line(account), "action": ""}
    else:
        badge = dict(NO_BADGE)
    return {
        "id": f"{group.provider}/{account.name}",
        "provider": group.provider,
        "providerTitle": group.display_name,
        "name": account.name,
        "email": email,
        "plan": plan_label(account.plan),
        "subtitle": " · ".join(p for p in (email or "Address unknown",
                                           plan_label(account.plan)) if p),
        # D1: the address once. An account named after it says it already.
        "showAddress": bool(email) and email.casefold()
        != account.name.casefold(),
        "initial": (account.name[:1] or "?").upper(),
        "live": live,
        "badge": badge,
        "action": action,
        "actionLabel": label,
        "actionEnabled": enabled,
        # Why the button is off, for its tooltip (D1: reasons on hover).
        "actionReason": reason,
        "actionTip": (f"Sign in to {account.name}" if action == "signin"
                      else f"Switch to {account.name}" if action else ""),
        # Whether a sign-in is offered at all, from the row's button or its
        # badge, and whether it can start now.
        "signIn": sign_in,
        "signInEnabled": sign_in and not hold,
        "key": key,
        "usage": usage,
        "usageSummary": " · ".join(
            f"{w['label'].lower()} reset" if w["state"] == "reset"
            else f"{w['percent']}% {w['label'].lower()}" for w in usage),
        # How old a reading is shows in the bar's look and its tooltip (U1),
        # not as an "as of" sentence. Kept, empty, for QML that still reads it.
        "usageNote": "",
        "usageTip": " ".join(w["tip"] for w in usage),
        # Blank space reads as a broken widget; saying why does not. A
        # provider that publishes nothing gets no line at all.
        "usageHint": ("" if usage or not account.publishes_usage
                      else "Usage appears once you run it" if live
                      else "No usage recorded yet"),
        "login": login_line(account),
        "canRemove": not account.active,
    }


def _window(window, *, live: bool, now_ms: int) -> dict:
    """One limit, as the window draws it at ``now_ms``.

    ``state`` is what the bar's look keys off: ``reset`` (the window rolled
    over after the figure was read, so the figure is history), ``old`` (read
    over an hour ago) or ``current``. ``tip`` says the rest in words.
    """
    percent = window.used_percent or 0
    reset = window.reset or timing.has_reset(window.resets_at_ms, now_ms)
    if window.fetched_at_ms is not None:
        age_ms = now_ms - window.fetched_at_ms
        old = age_ms > timing.STALE_AFTER_MS
        age = timing.age_words(age_ms)
    else:
        old, age = window.stale, window.age_label
    state = "reset" if reset else "old" if old else "current"

    exact = window.resets_label or timing.date_label(window.resets_at_ms)
    until = timing.until_label(window.resets_at_ms, now_ms) or exact
    name = LIMIT_NAMES.get(window.label, window.label.capitalize())

    if reset:
        read = (f" when last read at "
                f"{timing.moment_label(window.fetched_at_ms, now_ms)}"
                if window.fetched_at_ms is not None else "")
        when = timing.moment_label(window.resets_at_ms, now_ms)
        tip = (f"{name}: {percent}%{read}. "
               + (f"It reset at {when}." if when else "It has since reset."))
        tone = "reset"
    else:
        tip = f"{name}: {percent}%."
        if exact:
            tip += f" Resets {exact}."
        if old and age:
            tip += f" Read {age}."
        # An old figure is greyed only on an account not in use. On the live
        # one it is still the real number, just one nothing has refreshed
        # lately.
        tone = "dim" if (old and not live) else window.severity

    return {
        "label": USAGE_LABELS.get(window.label, window.label.capitalize()),
        "percent": percent,
        "fill": 0.0 if reset else max(0.0, min(1.0, percent / 100.0)),
        "tone": tone,
        # What the figure means, kept when ``tone`` says "dim": an old bar
        # is drawn striped in this colour, not greyed (D12).
        "severity": window.severity,
        "state": state,
        "text": "reset" if reset else f"{percent}%",
        "resets": "" if reset or not until else f"Resets {until}",
        "resetsIn": "" if reset else until,
        "resetsExact": exact,
        "tip": tip,
    }


def plan_label(plan) -> str:
    """``max_5x`` as ``Max 5x``. The vendor's word, made readable."""
    if not plan:
        return ""
    text = str(plan).replace("claude_", "").replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def local_time(ms, fmt: str = DATE_FORMAT) -> str:
    """``ms`` as a local date, or ``""`` if it is not a representable one.

    The value is whatever the credential said and is never range-checked,
    so a vendor emitting microseconds lands outside ``datetime``'s range.
    """
    try:
        return datetime.datetime.fromtimestamp(ms / 1000).strftime(fmt)
    except (ValueError, OverflowError, OSError, TypeError):
        return ""


def _left(ms, now_ms) -> str:
    """Time left until ``ms``, rounded down: ``2d``, ``5h``, ``<1h``.

    Only on a sign-in deadline's badge, and only in its last days, where
    the state DD-1 asks for is already "sign in soon"; the number says how
    soon. Rounded down so it never promises time that is not there.
    """
    if ms is None:
        return ""
    gap = ms - now_ms
    if gap <= 0:
        return ""
    if gap >= DAY_MS:
        return f"{gap // DAY_MS}d"
    if gap >= HOUR_MS:
        return f"{gap // HOUR_MS}h"
    return "<1h"


#: For a login whose deadline is fixed at sign-in (Claude's, about thirty
#: days). The same words as the Tk window, so the two cannot disagree.
FIXED_DEADLINE = ("Using the account does not move this date. Sign in again "
                  "before then to keep it.")
FIXED_USE = "Using the account does not move this date."


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
        return (f"Signed out since {when}. Sign in to use it again." if when
                else "Signed out. Sign in to use it again.")
    if state == "closing":
        if account.renewed_by_use:
            return (f"Switch to it by {when} to keep it." if when
                    else "Switch to it soon to keep it.")
        # D9: "sign in by", the window's one phrase for a deadline.
        return (f"Sign in by {when} to keep it. {FIXED_USE}" if when
                else f"Sign in soon to keep it. {FIXED_USE}")
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


#: The two ways into a provider that offers a device code (S2).
SIGN_IN_METHODS = (
    {"id": "browser", "label": "This browser"},
    {"id": "device", "label": "Another device"},
)

LINK_WAITING = "Your browser should open by itself."
LINK_SHOWN = "Browser didn't open? Use this link."
CODE_TIP = ("Only needed when the page shows a code instead of saying you're "
            "signed in. That happens when you open the link on another "
            "device, or the browser can't reach this machine.")
DEVICE_SHOWN = "Open the link on any device and enter this code:"
DEVICE_TIP = ("Works only if your account allows sign-in with a code. Enter "
              "it only for a sign-in you started here, never for a code "
              "someone else gave you.")


def login_sheet(*, provider_title: str, name: str, email: str,
                previous: str, adding: bool, method: str = "browser",
                offers_device: bool = False) -> dict:
    """The sheet shown while the vendor's sign-in runs.

    D7: one labelled progress line instead of four sentences. Each label
    keeps its sentence as a tooltip, and the advice about which browser
    profile to use sits behind the link's ⓘ.
    """
    device = method == "device"
    steps = []
    if previous and previous != name:
        steps.append({"label": "Saved", "state": "done",
                      "tip": f"{previous} is saved and set aside."})
    steps += [
        {"label": "Ready", "state": "active",
         "tip": f"{provider_title}'s sign-in is starting."},
        ({"label": "Other device", "state": "todo",
          "tip": "Waiting for the code to be entered on the other device."}
         if device else
         {"label": "Your browser", "state": "todo",
          "tip": "Waiting for you to finish in your browser."}),
        {"label": "Save", "state": "todo",
         "tip": f"Then the new login is saved to {name}."},
    ]
    if email:
        link_tip = (f"Open it in the browser profile that is signed in as "
                    f"{email}, or in a private window.")
    else:
        link_tip = ("Open it in a browser profile signed in as the account "
                    "you want to add, or in a private window.")
    if previous and previous != name:
        cancel = f"Cancel puts you back on {previous}."
    elif adding:
        cancel = f"Cancel keeps {name}, signed out."
    else:
        cancel = "Cancel leaves everything as it was."
    return {
        "kind": "login",
        "title": f"Sign in to {name}",
        "subtitle": " · ".join(p for p in (provider_title, email) if p),
        "steps": steps,
        "url": "",
        "copied": False,
        "linkHint": LINK_WAITING,
        "linkTip": link_tip,
        "acceptsCode": False,
        "codeTip": CODE_TIP,
        "codeError": "",
        "codeSent": False,
        "methods": [dict(m) for m in SIGN_IN_METHODS] if offers_device else [],
        "method": "device" if device else "browser",
        "device": {"code": "", "url": "", "expiresAtMs": 0},
        "deviceHint": f"Getting a code from {provider_title}.",
        "deviceTip": DEVICE_TIP,
        "expiresIn": "",
        "codeCopied": False,
        #: Between choosing the other method and its sign-in starting.
        "restarting": False,
        "cancelNote": cancel,
    }


def login_started(sheet: dict) -> dict:
    """The same sheet once the vendor has said anything at all."""
    steps = [dict(step) for step in sheet["steps"]]
    for index, step in enumerate(steps):
        if step["label"] == "Ready" and step["state"] == "active":
            step["state"] = "done"
            step["tip"] = step["tip"].replace("is starting", "is ready")
            steps[index + 1]["state"] = "active"
            return {**sheet, "steps": steps}
    return sheet


def login_link(sheet: dict, url: str) -> dict:
    """The sheet with the vendor's sign-in link, if it has none yet."""
    if not url or sheet.get("url"):
        return sheet
    return {**sheet, "url": url, "linkHint": LINK_SHOWN}


def login_takes_code(sheet: dict, accepts: bool) -> dict:
    """S1: whether to draw the field for the code from the browser page."""
    return {**sheet, "acceptsCode": bool(accepts), "codeError": "",
            "codeSent": False}


def login_code_result(sheet: dict, result) -> dict:
    """What became of a pasted code. The code itself is never kept here."""
    if result.ok:
        return {**sheet, "codeSent": True, "codeError": ""}
    message = result.error.message if result.error else ""
    return {**sheet, "codeSent": False, "codeError": message}


def expiry_label(expires_at_ms: int, now_ms: int) -> str:
    """``expires in 14:32``, ``expired``, or nothing without a deadline."""
    if not expires_at_ms:
        return ""
    left = expires_at_ms - now_ms
    if left <= 0:
        return "expired"
    seconds = -(-left // 1000)
    return f"expires in {seconds // 60}:{seconds % 60:02d}"


def login_device(sheet: dict, offer, *, now_ms: int) -> dict:
    """S2: the one-time code and its link, once the vendor shows them."""
    device = {"code": offer.user_code, "url": offer.verification_url,
              "expiresAtMs": int(offer.expires_at_ms)}
    return {**login_started(sheet), "device": device,
            "deviceHint": DEVICE_SHOWN,
            "expiresIn": expiry_label(device["expiresAtMs"], now_ms)}


def login_tick(sheet: dict, *, now_ms: int) -> dict:
    """The device sheet a second later: only the countdown moves."""
    label = expiry_label(sheet.get("device", {}).get("expiresAtMs", 0), now_ms)
    if label == sheet.get("expiresIn"):
        return sheet
    return {**sheet, "expiresIn": label}


def _words(text: str) -> list:
    return [w.strip(".,;:'\"").casefold() for w in text.split()]


def _restates(title: str, message: str) -> bool:
    """Whether ``message`` only says ``title`` again, in a few more words."""
    said, again = _words(title), _words(message)
    return bool(said) and all(w in again for w in said) \
        and len(again) <= len(said) + 2


def as_the_window_says(text: str, *, tool: str = "", names=()) -> str:
    """The service's words in the window's own (D9).

    The tool by its name where the service says "the vendor", and account
    names without the quotes the service puts round them: the rest of the
    window writes ``work``, not ``'work'``. Only the names given lose their
    quotes, so an apostrophe elsewhere ("vendor's", "O'Brien") is left be.
    """
    if tool:
        text = re.sub(r"\b[Tt]he vendor's\b", f"{tool}'s", text)
        text = re.sub(r"\b[Tt]he vendor\b", tool, text)
    for name in sorted(set(names), key=len, reverse=True):
        if name:
            text = text.replace(f"'{name}'", name)
    return text


def result_sheet(result, *, name: str, provider_title: str = "",
                 names=()) -> dict:
    """A sign-in that ended some way other than working.

    D7: the body does not repeat the title, and "Sign in to try again" is
    not said right above the Try again button. ``provider_title`` names the
    tool and ``names`` are the provider's accounts, for
    :func:`as_the_window_says`.
    """
    error = result.error
    code = error.code if error else ""
    title = LOGIN_TITLES.get(code, "Sign-in did not finish")
    retry = code != "login_unavailable"
    message = error.message if error else ""
    if _restates(title, message):
        message = ""
    elif code == "login_not_written" and provider_title:
        message = f"{provider_title} did not save a usable login."
    remedy = error.recovery if error else ""
    if retry:
        remedy = re.sub(rf"\s*Sign in to '{re.escape(name)}' to try again\.\s*$",
                        "", remedy)
    names = {name, *names}
    message = as_the_window_says(message, tool=provider_title, names=names)
    remedy = as_the_window_says(remedy, tool=provider_title, names=names)
    return {
        "kind": "result",
        "tone": "warn" if code in ("login_other_account",
                                   "login_duplicate") else "bad",
        "title": title,
        "message": message,
        "remedy": remedy,
        "retry": retry,
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


#: D7: eject in a few lines, where the plan comes in parts.
EJECT_SHORT = ("Each tool goes back to being an ordinary install. Nothing is "
               "deleted.")
PARKED_TIP = ("They are kept because each one is only recoverable through a "
              "new verification email. Delete the folder yourself once you "
              "are sure.")


def _names(names) -> str:
    """``A``, ``A and B``, ``A, B and C``."""
    names = list(names)
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def eject_sheet(plan) -> dict:
    parts = [part.strip() for part in plan.warnings if part and part.strip()]
    sheet = {
        "kind": "confirm",
        "action": "eject",
        "title": "Stop using Shambles?",
        "message": "\n\n".join(parts) if parts else EJECT_FALLBACK,
        "lines": [],
        "path": "",
        "pathLabel": "",
        "pathTip": "",
        "confirmLabel": "Eject",
        "provider": "",
        "name": "",
    }
    details = getattr(plan, "details", None) or {}
    if not details.get("keeps") and not details.get("store"):
        return sheet
    lines = []
    for keep in details.get("keeps") or []:
        if keep.get("signedIn") and keep.get("account"):
            lines.append(f"{keep['provider']} stays signed in as "
                         f"{keep['account']}.")
        elif keep.get("signedIn"):
            lines.append(f"{keep['provider']} stays signed in.")
        else:
            lines.append(f"{keep['provider']} will ask you to sign in.")
    parked = details.get("parked") or []
    store = details.get("store") or ""
    if parked:
        label = f"Saved logins for {_names(parked)} stay in"
    elif store:
        label = "You can delete this folder afterwards"
    else:
        label = ""
    sheet.update(message=EJECT_SHORT, lines=lines, path=store,
                 pathLabel=label, pathTip=PARKED_TIP if parked else "")
    return sheet


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


#: Why the store moved, behind the i on the short version (D7).
STORE_MOVED_TIP = ("That is what lets Shambles hold Codex accounts alongside "
                   "Claude ones. Nothing was deleted.")


def _notice_items(notice) -> list:
    """What one migration notice says, as ``{text, path, tip}`` lines. A
    path goes on a line of its own; the why goes behind an i."""
    details = getattr(notice, "details", None) or {}
    if getattr(notice, "code", "") == "store_moved" and details.get("dest"):
        count = details.get("count", 0)
        many = count != 1
        return [
            {"text": f"{count} account{'s' if many else ''} "
                     f"{'are' if many else 'is'} now kept by provider, in",
             "path": details["dest"], "tip": STORE_MOVED_TIP},
            {"text": "The old folder is still there. Remove it when you are "
                     "ready",
             "path": details.get("source", ""), "tip": ""},
        ]
    return [{"text": notice.message, "path": "", "tip": ""}]


def notice_sheet(notices) -> dict:
    """Startup migrations, said once."""
    return {
        "kind": "notice",
        "title": ("Shambles updated how it stores your accounts"
                  if all(n.ok for n in notices)
                  else "An update to your account store could not finish"),
        "tone": "ok" if all(n.ok for n in notices) else "bad",
        "messages": [item for n in notices for item in _notice_items(n)],
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
