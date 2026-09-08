# Shambles

![Shambles — local Claude and Codex account switcher](docs/assets/shambles-banner.svg)

<details>
<summary>ASCII version</summary>

```text
╔═[ >_ ⇄ ]═════════════════════════════════════════════════════[ OFFLINE ]═╗
║                                                                          ║
║  ███████╗██╗  ██╗ █████╗ ███╗   ███╗██████╗ ██╗     ███████╗███████╗     ║
║  ██╔════╝██║  ██║██╔══██╗████╗ ████║██╔══██╗██║     ██╔════╝██╔════╝     ║
║  ███████╗███████║███████║██╔████╔██║██████╔╝██║     █████╗  ███████╗     ║
║  ╚════██║██╔══██║██╔══██║██║╚██╔╝██║██╔══██╗██║     ██╔══╝  ╚════██║     ║
║  ███████║██║  ██║██║  ██║██║ ╚═╝ ██║██████╔╝███████╗███████╗███████║     ║
║  ╚══════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═════╝ ╚══════╝╚══════╝╚══════╝     ║
║                                                                          ║
║              Switch Claude and Codex accounts safely.                    ║
╚══════════════════════════════════════════════════════════════════════════╝
```

</details>

Switch between Claude Code accounts — and Codex accounts — without waiting for
a verification email.

Claude Code hardcodes its config path to `~/.claude` and the VS Code extension
host ignores environment variables, so there is no supported way to run more
than one account. Codex has the same problem: `~/.codex/auth.json` is a single
file holding a single account. Shambles keeps each account's login in
`~/.shambles/<provider>/<Name>/` and swaps just that one file into place.

Adding an account opens your browser to sign in. Shambles does not implement
that — it runs the vendor's own `claude auth login` or `codex login`, which
opens the browser and handles the OAuth itself. See [Is this safe?](#is-this-safe).

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

**One command.** The script picks the binary for your OS and architecture out
of the latest [Release](https://github.com/ianchendev/Shambles/releases) and
puts it in `~/.local/bin` — no sudo, nothing to build:

```bash
curl -fsSL https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.sh | bash

# or pin a release
curl -fsSL https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.sh | bash -s v2.0.0
```

Windows PowerShell, which installs into `%LOCALAPPDATA%\Shambles` and adds
that directory to your user PATH:

```powershell
irm https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.ps1 | iex
```

Two things worth knowing before you paste either one. The binaries are
**unsigned**, so Windows SmartScreen warns on first run — that is what an
unsigned publisher looks like. And **a successful install is not a working
switch**: the script fetches whatever binary matches your machine, which says
nothing about whether Shambles can swap an account there. The table below is
the part that says.

`install.sh` also knows the macOS and arm64-Linux asset names, but those
binaries are built for the first time by the *next* tagged release; against
the current latest release it gets a 404 there. Use pipx on those platforms
until then.

**Or pipx**, which involves no unsigned binary and works identically on Linux
and inside WSL:

```bash
sudo apt install python3-tk                              # only for the Tk window
pipx install git+https://github.com/ianchendev/Shambles
shambles
```

**Or download a binary** from [Releases](https://github.com/ianchendev/Shambles/releases)
yourself — a single file, nothing to install. Same unsigned caveat as above.

**Or from a checkout:**

```bash
git clone https://github.com/ianchendev/Shambles && cd Shambles
python3 shambles.py          # or: python3 -m shambles
```

`python3` here has to be **3.10 or newer**. On distributions where it is still
3.8 — Ubuntu 20.04 among them — name the interpreter instead
(`python3.12 shambles.py`); running it on an older one stops with a message
saying so rather than a syntax error from somewhere in the package.

**Not npm, yet.** Shambles is not published to npm, so `npm install -g
shambles` fails today. A launcher package is designed and planned
([plan](docs/superpowers/plans/2026-09-06-npm-distribution.md)) but it stays
unpublished until the macOS and Windows credential-store work below is
resolved — shipping a one-line install to platforms where switching does not
work is exactly the thing this README is trying not to do.

### Before you install, check it applies to you

| Where you run it | Claude Code | Codex |
|---|---|---|
| Linux desktop | **Supported** | **Unverified** — see below |
| WSL (Ubuntu etc.) | **Supported** — the **Linux** build, run **inside WSL** | **Unverified** |
| Windows natively | **Unverified, probably not working** — see below | **Unverified** |
| macOS | **Not supported** — see Platform notes | **Unverified** |

**About Codex.** Codex support is built and tested, but only against fixtures:
no Codex install was available on the development machine, and the research its
adapter is built from was done on macOS with Linux and Windows read from source
rather than executed. The file it swaps is `~/.codex/auth.json`, the same path
on every platform. Treat it as unverified until someone confirms a real switch
takes effect. The contract tests every provider must pass are in
`tests/contract/`.

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
login out of `~/.claude` into `~/.shambles/claude/Work/` and records it as
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

## Terminal interface

`shambles` opens a keyboard-driven dashboard instead of the Tk window whenever
it's run on an actual interactive terminal — stdin and stdout both need to be
one. No `DISPLAY`, no Tk, works the same over SSH:

```bash
shambles      # terminal interface, if run on an interactive terminal
shambles tui  # open it explicitly either way
shambles gui  # open the Tk window instead
```

Piped input or output, a script, a cron job — anything where stdin or stdout
isn't a real terminal — falls through to the usage message, exactly as it did
before this existed. `shambles list` and `shambles switch ...` are unaffected
either way; they're the same non-interactive path they always were.

It is a second front end on the same core, not a separate tool: it reads and
writes exactly what [What it touches](#what-it-touches) describes, through
the same service the Tk window and `shambles switch` use. Switching an
account here has the identical effect, and the identical restart requirement,
as switching it anywhere else — a Claude Code session already running, in a
terminal or in VS Code, keeps the login it loaded at startup no matter which
interface performed the switch. Start a new session, or reload the VS Code
window.

### Keyboard shortcuts

The dashboard footer lists the first-class keys. A full footer is shown when
it fits; a compact set (`switch`, `add`, `eject`, `menu`, `help`, `quit`)
otherwise.

| Key | Action |
|---|---|
| `j` / `↓` | Next account |
| `k` / `↑` | Previous account |
| `Enter` | Switch to the selected account (asks first, if the account needs confirming) |
| `a` | Add — pick a provider and name in an overlay |
| `m` | Account menu — save the current login, rename, remove |
| `l` | Log in the selected account (runs the vendor's own login command) |
| `x` | Eject — see [Leaving cleanly](#leaving-cleanly) |
| `r` | Refresh |
| `?` | Help |
| `q` | Quit |
| `Esc` | Close whatever is open |

Inside the account menu: `s` save current, `n` rename, `d` remove, `Esc`
cancel. `a` add is also available from the dashboard (and from the empty
welcome), not only the menu. Every confirmation, result and login-progress
screen takes `Enter` to confirm or continue and `Esc` to cancel; `q` quits
from any of them. The same reference is one keystroke away inside the app:
press `?`.

### Launching straight back into the vendor CLI

After a successful switch, the result screen offers **Launch** next to
Escape. Choosing it closes the terminal interface — Textual restores the
terminal first — and replaces the Shambles process in place with `claude` or
`codex` (`execvp`, not a child process), inheriting the environment
unchanged. There's no second window: the terminal `shambles` was running in
becomes the vendor CLI's terminal, immediately signed in as the account you
just switched to.

### NO_COLOR

`NO_COLOR` — the [convention](https://no-color.org), detected automatically,
nothing Shambles-specific to set — makes the whole interface monochrome.
`SHAMBLES_NO_MOTION=1` and `--no-motion` remain accepted (the flag before or
after the subcommand) so existing scripts and flags do not break.

## Update checks

**Off by default**, and off means off: with the setting unset, no interface —
terminal, Tk window, or `shambles switch` — makes a network call of any kind.
Nothing here reports usage or phones home under any setting. The `?` help
screen says so in the app itself.

If you would rather hear about new releases:

```bash
shambles config set update.check true     # turn it on
shambles config get update.check          # prints true or false
shambles config set update.check false    # turn it off again
```

What that signs you up for, in full: at most one unauthenticated `GET` per
day to the public GitHub Releases endpoint for this repository, from which
Shambles reads one field — the tag of the latest release. No token, no
account, no machine ID and no query string go with it, so nothing in the
request says who you are. The only thing kept is
`~/.shambles/update-cache.json`, holding that tag and the time of the lookup;
no account name, email or token goes near it. A failed lookup still counts as
the day's attempt, so a machine that is offline is not made to sit through a
connection timeout every time you start the app, and a lookup that fails for
any reason at all — rate limit, captive portal, DNS, an unorderable tag —
produces silence rather than an error.

**It never downloads or replaces anything.** The entire feature is one
sentence saying a newer version exists and how to get it; fetching it stays
your decision.

Where that sentence appears:

- **In the terminal interface** — one line at the bottom of the dashboard,
  and `u` dismisses it for the rest of the session. The lookup runs on a
  background thread after the first frame is drawn, so a slow network cannot
  hold up the interface, and quitting does not wait for it.
- **On `shambles --version`** — printed to stderr, and only from the cache an
  earlier run already filled. `--version` itself never makes a request, which
  keeps it instant and keeps its stdout exactly one line for the scripts that
  read it.

The Tk window shows no notice and performs no lookup, whatever the setting
says.

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

Do **not** uninstall by deleting `~/.shambles/`. That folder holds the
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
| `~/.claude.json` | only `oauthAccount` and `cachedUsageUtilization` spliced |
| `~/.claude/projects/`, `plugins/`, `file-history/`, `settings.json` | **never touched** |
| `~/.codex/auth.json` | swapped — Codex's whole login, identity included |
| `~/.shambles/<provider>/<Name>/credentials.json` | that account's tokens |
| `~/.shambles/claude/<Name>/account.json` | that account's identity (Claude only) |
| `~/.shambles/<provider>/active` | which profile is live, per provider |
| `~/.shambles/.backups/` | last 10 copies of `~/.claude.json` |

`~/.claude` is an ordinary directory and is never replaced. Session history,
plugins, project trust, MCP servers and settings are all **shared across every
account** — switching does not hide your transcripts or make you re-trust your
directories. A profile is about half a kilobyte.

## Where the tokens live

```
~/.shambles/<provider>/<Name>/credentials.json       mode 600
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

Directory permissions: `~/.shambles/` and each directory inside it are
created `700`, and every credentials file is written `600`. On Windows `chmod`
cannot express either, so there the files rely on the user profile's own ACLs —
the same protection Claude Code's own `.credentials.json` gets.

## Checking token health

A card shows a chip beside the email only when the account needs attention:

| Chip | Meaning | Colour |
|---|---|---|
| *(none)* | healthy — nothing to do | — |
| `soon` | the refresh window is closing | amber |
| `needs login` | the window has closed, or this profile has no credential yet | red |

**Durations are deliberately off the card face.** A number counting down on
every row is noise on the days it is not urgent, so the face carries the state
and the figures stay one hover away: point at a profile's name for the exact
date and time, and at a chip for what to do about it.

"Closing" means one day or fewer for Claude Code, two for Codex — not the week
you might expect. The windows differ by an order of magnitude across platforms
and plans (see [docs/token-storage.md](docs/token-storage.md)), and against a
measured window of roughly four days a seven-day threshold would leave every
profile permanently amber. Each provider sets its own figure in its spec.

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
import base64,json,datetime,pathlib

def expiry(blob):
    'Claude records the deadline; Codex hides it in a JWT claim.'
    if 'claudeAiOauth' in blob:
        return blob['claudeAiOauth'].get('refreshTokenExpiresAt')
    token = blob.get('tokens', {}).get('access_token', '')
    payload = token.split('.')[1] if token.count('.') >= 2 else ''
    if not payload: return None
    claims = json.loads(base64.urlsafe_b64decode(payload + '=' * (-len(payload) % 4)))
    return claims.get('exp', 0) * 1000

root = pathlib.Path.home()/'.shambles'
for provider in sorted(p for p in root.iterdir() if p.is_dir() and p.name[0]!='.'):
    for d in sorted(p for p in provider.iterdir() if p.is_dir()):
        c = d/'credentials.json'
        label = f'{provider.name}/{d.name}'
        if not c.exists(): print(f'{label:<22} no token'); continue
        ms = expiry(json.loads(c.read_text()))
        if not ms: print(f'{label:<22} unknown'); continue
        t = datetime.datetime.fromtimestamp(ms/1000)
        print(f'{label:<22} {(t-datetime.datetime.now()).days:>3}d left')"
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

**It is entirely local and cannot touch your Claude or OpenAI account.**

**No network, with one exception you have to switch on yourself.** Shambles
cannot reach Anthropic's or OpenAI's servers at all, so it cannot affect your
login, billing, rate limits or organisation membership; it only moves bytes
between directories on your own disk. The single module that may open a
socket is `shambles/update_check.py`, which asks GitHub for the latest
release tag and runs only once you have enabled
[update checks](#update-checks) — see that section for exactly what the
request contains. That division is not a promise: `tests/test_login.py` walks
the AST of every module in the package, fails on any networking import, and
permits `urllib` in that one file and nowhere else.

**It executes exactly one kind of external program:** the vendor's own login
command — `claude auth login` or `codex login` — and only when you click Add
Account. **Shambles implements no part of signing in.** That command opens
your browser and runs its own callback server; Shambles waits for it to
finish and then files the credential it wrote. No password, no token in
flight, and nothing held that was not already on your disk.

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

800+ tests. Every one runs against a synthetic home in `tmp_path`. None reads or
writes your real `~/.claude`.

CI runs the suite on Linux and Windows across Python 3.10 and 3.12, under
`xvfb` so the GUI render and shutdown tests actually execute rather than skip.
Tagging `v*` builds unsigned single-file binaries for Linux (x86_64 and
arm64), macOS (Intel and Apple Silicon) and Windows x64, and attaches them to
a GitHub Release — but each binary is built only after the suite passes on
that platform, and none is published unless all five build.

The load-bearing test is
`tests/test_switch.py::test_credentials_survive_a_round_trip_unmodified` — it
asserts that `Work → Personal → Work` leaves the credential byte-identical,
refresh token and expiry included. It is parametrized over every provider, so
adding a third means passing a suite that already exists. If it regresses, the
tool stops solving the problem it exists for.

Nothing here runs a real `claude` or `codex`. The login tests drive a `/bin/sh`
stand-in placed on `PATH`, so no browser opens and nothing authenticates.

## Platform notes

Developed and verified on WSL2 Ubuntu with WSLg, Python 3.12, Tk 8.6. The
window is 860px wide with a 560px floor, and a `Switch` click was confirmed
to swap the token and the displayed email together. The Windows code paths
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
| [docs/superpowers/specs/2026-08-07-multi-provider-design.md](docs/superpowers/specs/2026-08-07-multi-provider-design.md) | **Current** design: the provider/store layering, Codex as a peer, and the browser login handoff |
| [TECH_SPEC.md](TECH_SPEC.md) | Architecture reference. Its §-numbered mechanism is authoritative; its single-provider paths describe v1.0 and are superseded — the banner says which |
| [docs/token-storage.md](docs/token-storage.md) | Field research into how Claude and Codex store credentials across macOS, Windows and Linux. Covers platforms this tool does not yet support |
| [docs/design-decisions.md](docs/design-decisions.md) | Recorded decisions and rationale. DD-4 is implemented; DD-2 is amended — the tool now starts the vendor's login rather than printing it |

Where two documents disagree about what the tool does today, the
multi-provider design wins on anything provider-shaped — paths, layering,
login, the store layout — and TECH_SPEC wins on mechanism: switch ordering,
atomic writes, permissions, the state machine, concurrency.

The tests win over both.
