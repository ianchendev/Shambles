# Shambles

Switch between Claude Code accounts without waiting for a verification email.

Claude Code hardcodes its config path to `~/.claude`, and the VS Code extension
host ignores environment variables — so the only way to run more than one
account is to change what that path resolves to. Shambles keeps each account in
`~/.claude-profiles/<Name>` and swaps an OS-level symlink between them.

## Why this skips the login wait

Email verification is the *initial* OAuth grant only. What keeps you signed in
afterwards is the **refresh token** in `.credentials.json`, valid for a rolling
30 days and renewed on every use. Preserve that file per account and every
later switch is instant — an account only returns to the email flow if it goes
entirely unused for 30+ days.

Rate limits are still enforced server-side per account. Switching gives you the
target account's own bucket; it does not pool or extend any single account's
allowance.

## Install

```bash
sudo apt install python3-tk        # the only dependency
git clone <this repo> && cd Shambles
python3 shambles.py
```

## Using it

### First run

`~/.claude` is still a real directory. Click **Save Current Account** and name
it (e.g. `Work`). Shambles moves the directory into `~/.claude-profiles/Work`
and leaves a symlink behind. Nothing is deleted, and if the symlink cannot be
created the move is rolled straight back.

### Adding an account

Your existing login **cannot** be affected by this. Each profile has its own
`.credentials.json` in its own directory — two separate files. Signing into one
is physically incapable of signing out the other, because there is no shared
credential store to overwrite.

1. **Close any running Claude Code sessions**, in VS Code and in terminals.
2. Click **Add Empty Account**, name it, and leave *Copy settings from …*
   checked so your plugins, permissions and model prefs carry over. The new
   profile becomes active immediately — empty, with no token.
3. In a **terminal**, run `claude`, then `/login`. The OAuth flow writes
   `.credentials.json` into the new profile only. This is the one and only time
   you wait for the verification email for that account.
4. Reload the VS Code window (*Developer: Reload Window*).

Use the terminal rather than VS Code for that `/login`. Not because VS Code
would break anything, but because the extension may still hold a handle on the
now-empty profile and leave you unsure whether the login landed.

### Switching

Click **Switch**, then start a **new** Claude Code session. If the extension
does not pick it up, run *Developer: Reload Window*.

An already-running session keeps the token it loaded at startup — the switch is
a change on disk, not a change inside a live process.

## What it touches

| Path | Treatment |
|---|---|
| `~/.claude` | symlink, swapped atomically |
| `~/.claude.json` | real file; only `oauthAccount` and `cachedUsageUtilization` are spliced |
| `~/.claude-profiles/<Name>/` | the profile directories |
| `~/.claude-profiles/<Name>/.shambles.json` | that profile's stashed identity |
| `~/.claude-profiles/.shambles-backups/` | last 10 copies of `~/.claude.json` |

Project trust, MCP servers and prompt history live in `~/.claude.json` and stay
**shared** across profiles — switching accounts does not make you re-trust your
directories.

## Where the tokens live

```
~/.claude-profiles/<Name>/.credentials.json          mode 600
  claudeAiOauth.accessToken             ~8 hour life, refreshed silently
  claudeAiOauth.refreshToken            the thing that saves you the email
  claudeAiOauth.expiresAt               epoch ms
  claudeAiOauth.refreshTokenExpiresAt   epoch ms — rolling 30 days
  claudeAiOauth.scopes / subscriptionType / rateLimitTier
```

The **email is not in that file**. It lives in `~/.claude.json` under
`oauthAccount.emailAddress`, outside the swapped directory — which is precisely
why Shambles has to splice that one key on every switch. Without it you would
swap the token but keep displaying the previous account's name.

Directory permissions: `~/.claude-profiles/` is created `700`, so no other
local user can traverse into it, and each `.credentials.json` stays `600`.

## Checking token health

Each row shows a countdown chip beside the email:

| Chip | Meaning | Colour |
|---|---|---|
| `29d` | days until the refresh window closes | grey |
| `4d` | seven days or fewer remaining | amber |
| `today` | closes today | amber |
| `expired 12d ago` | window already closed; needs `/login` | red |
| *(none)* + ⚠ | no credentials file — never logged in here | — |

Hover any chip for the exact date and time. A ⚠ still appears alongside a red
chip, carrying the "run /login" tooltip.

### Why an expired token is left in place

Shambles never deletes a `.credentials.json`, even a long-dead one. That is
deliberate:

- **Clock drift makes deletion dangerous.** WSL2's clock can jump when Windows
  resumes from sleep. A drifted clock would mark a perfectly good token dead,
  and an automatic delete would then cost you a real verification email — the
  exact thing this tool exists to avoid. A wrong label is recoverable; a
  deleted refresh token is not.
- **It is diagnostic.** The lapsed file is what lets the UI distinguish
  "this account expired twelve days ago" from "never logged in here".
- **It is never in the way.** Switching to a lapsed profile is not an error.
  Shambles does not validate tokens; it moves a symlink. Claude Code then fails
  its refresh and prompts `/login`, which overwrites the file anyway.

Covered by `tests/test_switch.py::test_switching_to_a_lapsed_profile_is_not_an_error`.

For a countdown without opening the app:

```bash
.venv/bin/python -c "
import json,datetime,pathlib
for d in sorted(p for p in (pathlib.Path.home()/'.claude-profiles').iterdir()
                if p.is_dir() and p.name[0]!='.'):
    c = d/'.credentials.json'
    if not c.exists(): print(f'{d.name:<14} no token'); continue
    ms = json.loads(c.read_text())['claudeAiOauth']['refreshTokenExpiresAt']
    t = datetime.datetime.fromtimestamp(ms/1000)
    print(f'{d.name:<14} {(t-datetime.datetime.now()).days:>3}d left')"
```

Two things worth understanding:

- **Ignore the access token.** It expires within hours and is refreshed
  automatically. Only `refreshTokenExpiresAt` decides whether you face the
  email flow again — it is the one the UI counts down.
- **The 30-day clock resets on use, not on the calendar.** Every refresh mints
  a replacement with a fresh window. Rotating between accounts normally keeps
  all of them alive indefinitely; an account parked and untouched for 30+ days
  is the only one that needs a new `/login`.

## Is this safe?

**It is entirely local and cannot touch your Claude account.** The complete
import list across the application is `json`, `os`, `shutil`, `sys`, `time`,
`pathlib`, `dataclasses`, `tkinter`. There is no `socket`, no `urllib`, no
`requests`, no `subprocess`. It cannot reach Anthropic's servers, so it cannot
affect your login, billing, rate limits or organisation membership. It only
moves bytes between directories on your own disk.

What protects your data:

- Every write to `~/.claude.json` is preceded by a backup into
  `.shambles-backups/` and performed atomically (temp file + `os.replace`),
  preserving all other keys and their original order.
- The symlink swap is a rename over the top, so `~/.claude` never briefly
  ceases to exist. A crash mid-switch leaves either the old link or the new
  one, never nothing.
- `Save Current Account` rolls the directory move back if the symlink cannot be
  created — without that, a Windows privilege error would leave you with no
  `~/.claude` at all.
- Shambles refuses to touch a `~/.claude` symlink pointing outside
  `~/.claude-profiles/`.
- There is no delete-profile button. The only deletions in the entire codebase
  are pruning backups past ten, removing its own temporary symlink, and
  unlinking a dangling `~/.claude` when you explicitly click *Remove broken
  link*. Nothing deletes profile data.

### Closing the window

The title-bar X, `Ctrl+C` in the launching terminal, and `kill <pid>` all shut
Shambles down cleanly.

`Ctrl+C` needs explaining, because Tk does not give it to you for free. Tk's
`mainloop()` blocks inside C waiting on X events, while Python only dispatches
signal handlers between bytecode instructions — so by default `Ctrl+C` is
recorded and never delivered. The app looks frozen, and the natural next move
is `Ctrl+Z`, which SIGSTOPs the process. A stopped process cannot answer the
window manager's close request, leaving a window that nothing on the desktop
can shut, surviving even after you kill the terminal.

Shambles avoids this with a 150 ms no-op timer that hands control back to the
interpreter often enough for signals to land. Covered by
`tests/test_shutdown.py`.

**If you ever do end up with a frozen window** (from an older build, or after
pressing `Ctrl+Z`):

```bash
pkill -CONT -f shambles.py && pkill -f shambles.py
```

The `-CONT` matters — a stopped process cannot act on `SIGTERM` until it is
resumed first.

### The one real caveat

**Do not switch while a Claude Code session is running.** A live session holds
its token in memory and rewrites `~/.claude.json` periodically. If it writes
after Shambles does, last-writer-wins and the spliced identity is clobbered.
The backups in `.shambles-backups/` cover you, but the clean habit is: finish
or close your sessions, switch, then start fresh.

This is a race with another process, not a flaw the tool can fully close from
the outside — Claude Code holds no lock Shambles could wait on.

## Tests

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

107 tests. Every one runs against a synthetic home in `tmp_path`. None reads or
writes your real `~/.claude`.

The load-bearing test is
`tests/test_switch.py::test_credentials_survive_a_round_trip_unmodified` — it
asserts that `Work → Personal → Work` leaves `.credentials.json` byte-identical,
`refreshToken` and `refreshTokenExpiresAt` included. If that regresses, the tool
stops solving the problem it exists for.

## Platform notes

Developed and verified on WSL2 Ubuntu with WSLg, Python 3.12, Tk 8.6. The
window renders at 420×292 and a `Switch` click was confirmed to swap the token
and the displayed email together. The Windows code paths
(`target_is_directory=True`, the WinError 1314 Developer Mode message) are
written to spec but **have not been exercised** — there was no Windows-side
Claude Code install to test against.

**macOS is not supported.** Claude Code stores credentials in the system
Keychain there, not in `.credentials.json`, so swapping the directory would
swap everything *except* the login — which is the one thing this tool exists to
swap.

Do not point a Windows `%USERPROFILE%\.claude` at a WSL path or vice versa.
Cross-boundary symlinks break Claude Code's file operations and produce 9p
permission problems on a `600` credentials file. Run Shambles inside whichever
environment you use Claude Code in.
