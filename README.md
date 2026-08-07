# Shambles

Switch between Claude Code accounts without waiting for a verification email.

Claude Code hardcodes its config path to `~/.claude` and the VS Code extension
host ignores environment variables, so there is no supported way to run more
than one account. Shambles keeps each account's login in
`~/.claude-profiles/<Name>/` and swaps just that one file into place.

`~/.claude` itself is never moved or replaced. Your session history, plugins,
settings and project trust stay exactly where they are and are shared by every
account, which is how Claude Code behaves on its own.

## Why this skips the login wait

Email verification is the *initial* OAuth grant only. What keeps you signed in
afterwards is the **refresh token** in `.credentials.json`, valid for a rolling
window that is re-minted on every use. Preserve that file per account and every
later switch is instant — an account only returns to the email flow if it sits
entirely unused long enough for that window to lapse.

How wide is the window? **It varies, so Shambles reads it rather than assuming.**
Measurements differ by an order of magnitude: ~28 days across three credential
blobs on Linux/Team, ~4 days on a macOS/Max 5x sample
([evidence](docs/token-storage.md)). The countdown chip shows whatever your own
token says. What holds in every sample is the rolling behaviour — an account you
use regularly never approaches its deadline.

Rate limits are still enforced server-side per account. Switching gives you the
target account's own bucket; it does not pool or extend any single account's
allowance.

## Install

**Recommended — pipx.** No signing warnings, works identically on Linux and
inside WSL:

```bash
sudo apt install python3-tk                              # the only dependency
pipx install git+https://github.com/ianchendev/Shambles
shambles
```

**Or download a binary** from [Releases](https://github.com/ianchendev/Shambles/releases)
— a single file, nothing to install. See the platform notes below first; the
binaries are unsigned, so Windows SmartScreen will warn on first run.

**Or from a checkout:**

```bash
git clone https://github.com/ianchendev/Shambles && cd Shambles
python3 shambles.py          # or: python3 -m shambles
```

### Before you install, check it applies to you

| You run Claude Code in… | Status |
|---|---|
| Linux desktop | **Supported** — binary or pipx |
| WSL (Ubuntu etc.) | **Supported** — the **Linux** build, run **inside WSL** |
| Windows natively | **Unverified, probably not working** — see below |
| macOS | **Not supported** — see Platform notes |

**About Windows.** Claude Code does not use the same credential store on every
platform. On Linux it writes `~/.claude/.credentials.json`, which is the file
Shambles swaps. On Windows it appears to use the Credential Manager instead, in
which case that file never exists and switching would quietly do nothing. A
Windows binary is built and tested, but that only proves the app runs — nobody
has confirmed an account switch actually takes effect there. Treat Windows as
untested until someone does. The evidence is in
[docs/token-storage.md](docs/token-storage.md).

**WSL is the sharp edge.** A Windows `.exe` manages
`C:\Users\<you>\.claude`, which is a *different* Claude Code installation from
the one in your WSL home directory. If you use Claude Code inside WSL, install
inside WSL.

**Windows needs Developer Mode** (Settings → System → For developers) only when
migrating from a pre-1.0 layout, which used symlinks. Ordinary switching needs
no special privileges — but see the Windows caveat above before relying on it.

## CLI or VS Code extension — both

Shambles works below either one. The `claude` CLI and the VS Code extension are
the same product reading the same two paths, so swapping the login swaps it for
both at once:

```
~/.claude/.credentials.json      the login
~/.claude.json                   oauthAccount, projects, MCP servers
```

Verified by running the standalone CLI and watching it read and write the same
`~/.claude` the extension uses.

A **running** session is unaffected either way — it holds the token it loaded at
startup. After switching, start a new `claude` session, or run *Developer:
Reload Window* in VS Code.

### Why not just use `CLAUDE_CONFIG_DIR`?

Claude Code honours `CLAUDE_CONFIG_DIR`, and pointing it somewhere per account
looks like it would do the same job without any of this. It does not: it moves
the **entire** config tree, so each account gets its own `projects/` directory
and your session history splits per account. That is precisely the bug this
tool used to have and no longer does.

It also does not help inside VS Code, where the extension host does not see
shell environment variables.

## Desktop shortcuts without a console window

Tkinter apps launched through `python.exe` drag a blank terminal along behind
the GUI. Each install route has a quiet path:

| Route | Quiet launcher |
|---|---|
| Release binary | Already quiet — built with `--windowed` on Windows |
| pipx / pip | `shamblesw` (the `gui-scripts` entry, backed by `pythonw.exe`) |
| From a checkout | `pythonw.exe` on Windows, `python3` on Linux |

`shambles` (console) stays available everywhere so `--version` and `--help`
still print. On Windows a `gui-scripts` binary has nowhere to write, which is
exactly why both exist.

**Windows shortcut, from a checkout.** Right-click → New → Shortcut:

```
Target:      C:\Path\To\python\pythonw.exe C:\Path\To\Shambles\shambles.py
Start in:    C:\Path\To\Shambles
Run:         Normal window
```

`pythonw.exe` sits next to `python.exe` in the same install. Confirm with
`where pythonw`. Nothing else is required — no `cmd /c`, no `start`, both of
which reintroduce the console.

**Windows shortcut, pipx install:**

```
Target:      %USERPROFILE%\.local\bin\shamblesw.exe
```

**Building the binary yourself.** These are the exact commands the release
workflow runs. PyInstaller writes a `shambles.spec` as it goes; that file is a
generated artefact and is not tracked, so build from the flags rather than from
a spec:

```bash
pip install pyinstaller

# Windows — --windowed is what suppresses the console window
pyinstaller --onefile --windowed --name shambles shambles/__main__.py

# Linux — no --windowed, or it swallows --version and --help output
pyinstaller --onefile --name shambles shambles/__main__.py
```

The binary lands in `dist/`. On Windows it launches with no console attached.

**Linux desktop entry** — `~/.local/share/applications/shambles.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Shambles
Comment=Switch Claude Code accounts
Exec=/home/you/.local/bin/shambles
Terminal=false
Categories=Development;Utility;
```

`Terminal=false` is the equivalent setting. Run `update-desktop-database
~/.local/share/applications` afterwards if it does not appear.

## Using it

### First run

Click **Save Current Account** and name it (e.g. `Work`). Shambles copies the
login out of `~/.claude` into `~/.claude-profiles/Work/` and records it as
active. Nothing moves and nothing is deleted — `~/.claude` is left exactly as
it was.

### Adding an account

Your existing login **cannot** be lost by this. It is copied into its profile
before anything is replaced, so the account you are leaving is always
recoverable by switching back.

1. **Close any running Claude Code sessions**, in VS Code and in terminals.
2. Click **Add Account** and name it. Settings and plugins are shared, so there
   is nothing to copy across. The new
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

## If CLAUDE_CONFIG_DIR is set

Claude Code honours `CLAUDE_CONFIG_DIR`, and it relocates the **whole** config
tree — config, credentials and `projects/` together. Shambles swaps the login
inside `~/.claude`, so a shell with that variable set reads a tree Shambles
never touches and every switch appears to do nothing there.

Shambles detects this on startup and shows a warning naming the directory. The
warning is CLI-only in effect: the VS Code extension host does not inherit
shell environment variables, which is the reason this tool exists.

To use Shambles from the terminal, remove the variable from your shell profile.

## Leaving cleanly

Do **not** uninstall by deleting `~/.claude-profiles/`. That folder holds the
refresh tokens for every account you saved, and each one is only recoverable
through a fresh verification email.

Click **Eject** instead. It leaves `~/.claude` exactly as a stock Claude Code
install expects — still signed in as the current account, with history, plugins
and settings untouched — and removes only Shambles' own bookkeeping (the
`active` marker, and the legacy `.shambles.json` if present).

Eject never deletes a credentials file. Profiles stay on disk and the dialog
tells you where, so removing them is a decision you make deliberately rather
than a side effect of uninstalling.

### Removing an account

Each inactive profile carries a **✕** beside its Switch button. The active
profile has none — the login you are signed in as cannot be deleted by a
misclick, and the same rule is enforced in the code rather than only in the UI.

Confirming deletes that profile's directory and the refresh token in it. That
account then needs a fresh `/login` and its verification email to come back.
Nothing else is affected: session history, plugins and settings are shared and
live elsewhere.

To stop using Shambles entirely without deleting anything, use **Eject** below.

## What it touches

Only your **login** is account-scoped. Everything else in `~/.claude` is
machine-scoped and stays shared, which is how Claude Code behaves on its own.

| Path | Treatment |
|---|---|
| `~/.claude/.credentials.json` | swapped — this is the only file that moves |
| `~/.claude.json` | `oauthAccount` spliced; `cachedUsageUtilization` cleared so the usage meter refetches |
| `~/.claude/projects/`, `plugins/`, `file-history/`, `settings.json` | **never touched** |
| `~/.claude-profiles/<Name>/credentials.json` | that account's tokens |
| `~/.claude-profiles/<Name>/account.json` | that account's identity |
| `~/.claude-profiles/active` | which profile is live |
| `~/.claude-profiles/.shambles-backups/` | last 10 copies of `~/.claude.json` |

`~/.claude` is an ordinary directory and is never replaced. Session history,
plugins, project trust, MCP servers and settings are all **shared across every
account** — switching does not hide your transcripts or make you re-trust your
directories. A profile is about half a kilobyte.

## Where the tokens live

```
~/.claude-profiles/<Name>/credentials.json           mode 600
  claudeAiOauth.accessToken             ~8 hour life, refreshed silently
  claudeAiOauth.refreshToken            the thing that saves you the email
  claudeAiOauth.expiresAt               epoch ms
  claudeAiOauth.refreshTokenExpiresAt   epoch ms — rolling; width varies
  claudeAiOauth.scopes / subscriptionType / rateLimitTier
```

The **email is not in that file**. It lives in `~/.claude.json` under
`oauthAccount.emailAddress`, which is precisely why Shambles has to splice that
one key on every switch. Without it you would swap the token but keep
displaying the previous account's name.

Directory permissions: `~/.claude-profiles/` and each profile inside it are
created `700`, and every credentials file is written `600`. On Windows `chmod`
cannot express either, so there the files rely on the user profile's own ACLs —
the same protection Claude Code's own `.credentials.json` gets.

## Usage at a glance

Each card carries the two figures that decide which account to reach for:

```
Admin                                       [✕] [Switch]
admin@example.com                  28d

session   ▇▇▇▇▇▇░░░░░░░░░░░░░░░░░░░░░░░░░░   49%
week      ▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇▇░░░░   90%

Ian-Work  ACTIVE
me@example.com                     27d

usage appears once you run Claude
```

Bars are full-width rows beneath the identity, so they line up down the window
whatever a name or address happens to be. **A bar turns red at 80%**, the same
threshold the VS Code extension uses, so the two never disagree on screen.
Below that it is the ordinary accent — unless Claude Code itself flags the
bucket, in which case its warning shows through rather than being painted over.

**⟳ re-reads the figures on disk.** It opens local files and nothing else — no
network call, no credential written, no marker moved, nothing a running Claude
Code session can notice. Claude Code updates those figures as you work, so
press it after a session to pick up what it has written.

Only the **signed-in** account can have current figures. Claude Code caches
usage for whoever is logged in, and there is no way to ask the server about a
second account without using that account's token — which would rotate it and
leave the copy Shambles holds dead. Other accounts therefore show their last
known figures with an age, and never anything newer.

An account with no figures yet says so rather than leaving a gap. That happens
in two cases:

- **Just after a switch.** Shambles clears the usage cache so Claude Code
  refetches for the account you moved to, and the account has not reported yet.
- **An account never used while Shambles was open.**

In both, the line reads *usage appears once you run Claude*, and figures show up
on the next refresh. Shambles records the active account's numbers whenever it
sees them, so a profile keeps its last known figures once it has been used.

Showing nothing rather than a guess is deliberate. An earlier version restored
each profile's stashed figures into `~/.claude.json` on switch, which made the
VS Code meter display hours-old numbers as though they were current.

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
  Shambles does not validate tokens; it copies a file. Claude Code then fails
  its refresh and prompts `/login`, which overwrites it anyway.

For a countdown without opening the app:

```bash
.venv/bin/python -c "
import json,datetime,pathlib
for d in sorted(p for p in (pathlib.Path.home()/'.claude-profiles').iterdir()
                if p.is_dir() and p.name[0]!='.'):
    c = d/'credentials.json'
    if not c.exists(): print(f'{d.name:<14} no token'); continue
    ms = json.loads(c.read_text())['claudeAiOauth']['refreshTokenExpiresAt']
    t = datetime.datetime.fromtimestamp(ms/1000)
    print(f'{d.name:<14} {(t-datetime.datetime.now()).days:>3}d left')"
```

Two things worth understanding:

- **Ignore the access token.** It expires within hours and is refreshed
  automatically. Only `refreshTokenExpiresAt` decides whether you face the
  email flow again — it is the one the UI counts down.
- **The clock resets on use, not on the calendar.** Every refresh mints
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
- The outgoing login is copied into its profile **before** the incoming one is
  installed, so switching away can never strand an account.
- Credentials are written to a temporary file, `chmod 600`, then renamed into
  place, so a half-written credentials file is never visible.
- A `~/.claude.json` that fails to parse aborts the switch **before** anything
  moves. Without that check, splicing onto an unreadable config would replace
  every project, MCP server and machine ID in it with two keys.
- If the live login belongs to an account other than the one Shambles thinks is
  active — someone ran `/login` by hand — the UI says so rather than
  mislabelling it.
- The only automatic deletions are pruning backups past ten and clearing the
  live credentials file when you switch to a profile that has never been logged
  in. Removing a profile is possible but never automatic: the ✕ appears only on
  inactive profiles and asks for confirmation naming the account first.
- `~/.claude` is never moved, replaced or deleted. Session history, plugins and
  settings are simply not part of what switching touches.

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

### Your session history is shared

Session transcripts live in `~/.claude/projects/`, keyed by project path rather
than by account, and Shambles leaves that directory alone. Every account sees
every session, exactly as it does without Shambles installed.

**Versions before 1.0 got this wrong.** They swapped the whole `~/.claude`
directory, so each account had its own `projects/` folder and switching
appeared to erase weeks of history. If you used one of those, Shambles repairs
it the next time you open the window — automatically, with nothing to click.
There is no version of split history anyone wants, so it is not offered as a
choice. The merge is additive: nothing is deleted, and the old profile folders
stay on disk for you to remove once you are satisfied.

Open Shambles with **no Claude Code sessions running**. The repair briefly
replaces `~/.claude`, and a live session writes there continuously.

Unrelated but worth knowing: Claude Code prunes sessions older than 30 days on
its own. Raise `cleanupPeriodDays` in `~/.claude/settings.json` if you want to
keep them longer.

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
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

139 tests. Every one runs against a synthetic home in `tmp_path`. None reads or
writes your real `~/.claude`.

CI runs the suite on Linux and Windows across Python 3.10 and 3.12, under
`xvfb` so the GUI render and shutdown tests actually execute rather than skip.
Tagging `v*` builds unsigned single-file binaries for Linux and Windows and
attaches them to a GitHub Release — but only after the suite passes on both.

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
Keychain there rather than in `.credentials.json`, so there is no file for
Shambles to swap.

Run Shambles inside whichever environment you actually use Claude Code in. A
Windows build manages `C:\Users\<you>\.claude`, which is a different
installation from the one in a WSL home directory.

## Documentation

| Document | What it is |
|---|---|
| [TECH_SPEC.md](TECH_SPEC.md) | **Definitive** architecture reference for shipped v1.0 — mechanism, concurrency, permissions, token lifecycle, test coverage |
| [docs/token-storage.md](docs/token-storage.md) | Field research into how Claude and Codex store credentials across macOS, Windows and Linux. Covers platforms this tool does not yet support |
| [docs/design-decisions.md](docs/design-decisions.md) | Recorded decisions and rationale. DD-1–DD-3 describe shipped behaviour; DD-4 is an unimplemented proposal |

Where a document disagrees with TECH_SPEC about what the tool does today,
TECH_SPEC wins.
