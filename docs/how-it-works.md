# How Shambles works

The reference detail behind the [README](../README.md). Read that first for
install and everyday use. This file covers the mechanism: what a switch does
step by step, which files it touches, how token expiry works, and what
protects your data.

---

## What a switch does

```text
   switching Claude from "Work" to "Personal"

   1  copy the live login  ~/.claude/.credentials.json
                             └──► ~/.shambles/claude/Work/credentials.json
      (the outgoing account is saved BEFORE anything is replaced, so a
       failed switch can never strand the account you were on)

   2  back up ~/.claude.json  ──► ~/.shambles/.backups/   (last 10 kept)

   3  install the incoming login
      ~/.shambles/claude/Personal/credentials.json
                             └──► ~/.claude/.credentials.json   (600, atomic)

   4  splice identity into ~/.claude.json: oauthAccount only, every other
      key and its original order preserved

   5  record it:  ~/.shambles/claude/active  ←  "Personal"
```

A **running** session does not notice. It holds the token it loaded at
startup. Start a new `claude` session, or run *Developer: Reload Window* in
VS Code.

### The CLI and the VS Code extension both follow

They are the same product reading the same two paths, so one swap covers both:

```text
~/.claude/.credentials.json      the login
~/.claude.json                   oauthAccount, projects, MCP servers
```

Confirmed by running the standalone CLI and watching it read and write the
same `~/.claude` the extension uses.

### Why not just use CLAUDE_CONFIG_DIR?

Claude Code honours `CLAUDE_CONFIG_DIR`, and pointing it somewhere per account
looks like it would do this job with none of the above. It does not. It moves
the **whole** config tree, so each account gets its own `projects/` directory
and your session history splits per account. That is the exact bug this tool
used to have and no longer has.

It also does nothing inside VS Code, where the extension host never sees your
shell environment variables.

**If it is already set,** Shambles still swaps the login inside `~/.claude`. A
shell with that variable set reads a tree Shambles never touches, so every
switch looks like it did nothing. Shambles spots this at startup and shows a
warning naming the directory. To use Shambles from the terminal, take the
variable out of your shell profile. The VS Code extension works either way,
because the extension host does not inherit shell variables. That is the
reason this tool exists.

---

## What it touches

Only your **login** belongs to one account. Everything else in `~/.claude`
belongs to the machine and stays shared.

| Path | Treatment |
|---|---|
| `~/.claude/.credentials.json` | swapped. The only file that moves |
| `~/.claude.json` | only `oauthAccount` and `cachedUsageUtilization` spliced |
| `~/.claude/projects/`, `plugins/`, `file-history/`, `settings.json` | **never touched** |
| `~/.codex/auth.json` | swapped. Codex's whole login, identity included |
| `~/.shambles/<provider>/<Name>/credentials.json` | that account's tokens |
| `~/.shambles/claude/<Name>/account.json` | that account's identity (Claude only) |
| `~/.shambles/<provider>/active` | which profile is live, per provider |
| `~/.shambles/.backups/` | last 10 copies of `~/.claude.json` |

`~/.claude` is an ordinary directory and never gets replaced. Session history,
plugins, project trust, MCP servers and settings are **shared across every
account**. Switching does not hide your transcripts or make you re-trust your
directories. A profile takes about half a kilobyte.

### Where the tokens live

```text
~/.shambles/<provider>/<Name>/credentials.json       mode 600
  claudeAiOauth.accessToken             ~8 hour life, refreshed silently
  claudeAiOauth.refreshToken            the thing that saves you the email
  claudeAiOauth.expiresAt               epoch ms
  claudeAiOauth.refreshTokenExpiresAt   epoch ms, rolling, width varies
  claudeAiOauth.scopes / subscriptionType / rateLimitTier
```

**Your email is not in that file.** It lives in `~/.claude.json` under
`oauthAccount.emailAddress`. That is why Shambles splices that one key on
every switch. Without it you would swap the token and keep showing the
previous account's name.

Shambles creates `~/.shambles/` and every directory inside it as `700`, and
writes every credentials file as `600`. Windows `chmod` cannot express either,
so there the files rely on your user profile's own ACLs. That is the same
protection Claude Code's own `.credentials.json` gets.

---

## Token health

"Closing" means one day or less for Claude Code, and two for Codex. That is
shorter than you might expect. The windows differ by an order of magnitude
across platforms and plans (see [token-storage.md](token-storage.md)), and
against a measured window of about four days a seven-day threshold would leave
every profile permanently amber. Each provider sets its own figure.

Two things worth knowing:

- **Ignore the access token.** It expires within hours and refreshes on its
  own. Only `refreshTokenExpiresAt` decides whether you face the email again.
- **The clock resets on use, not on the calendar.** Every refresh mints a
  replacement with a fresh window. Rotating between accounts normally keeps
  them all alive forever. Only an account parked untouched for 30+ days needs
  a new login.

### Why Shambles leaves an expired token in place

Shambles never deletes a `.credentials.json`, even a long-dead one. Three
reasons:

- **Clock drift makes deleting dangerous.** WSL2's clock can jump when Windows
  wakes from sleep. A drifted clock would mark a good token dead, and deleting
  it would cost you a real verification email. That is the exact thing this
  tool exists to prevent. You can recover from a wrong label. You cannot
  recover a deleted refresh token.
- **It helps diagnose.** The lapsed file is what lets the UI tell "this
  account expired twelve days ago" apart from "never logged in here".
- **It never gets in the way.** Switching to a lapsed profile is not an error.
  Shambles does not check tokens. It copies a file. Claude Code then fails its
  refresh and prompts `/login`, which overwrites the file anyway.

### A countdown for every profile, without opening the app

```bash
python3 -c "
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

---

## What protects your data

- Every write to `~/.claude.json` gets a backup first and happens atomically
  (temp file, then `os.replace`), keeping all other keys in their original
  order.
- Shambles copies the outgoing login into its profile **before** installing
  the incoming one, so switching away can never strand an account.
- Credentials go to a temporary file, get `chmod 600`, then get renamed into
  place. A half-written credentials file is never visible.
- A `~/.claude.json` that fails to parse aborts the switch **before** anything
  moves. Without that check, splicing onto an unreadable config would wipe
  every project, MCP server and machine ID in it.
- If the live login belongs to a different account than Shambles expects,
  because someone ran `/login` by hand, the UI says so instead of mislabelling
  it.
- The only automatic deletions are pruning backups past ten, and clearing the
  live credentials file when you switch to a profile that has never been
  logged in. Removing a profile is possible but never automatic.
- `~/.claude` is never moved, replaced or deleted.

### Your session history is shared

Session transcripts live in `~/.claude/projects/`, filed by project path
rather than by account, and Shambles leaves that directory alone. Every
account sees every session, exactly as it would without Shambles installed.

**Versions before 1.0 got this wrong.** They swapped the whole `~/.claude`
directory, so each account had its own `projects/` folder and switching looked
like it erased weeks of history. If you used one of those, Shambles repairs it
the next time you open the window, with nothing to click. The merge only adds.
Nothing is deleted, and the old profile folders stay on disk for you to remove
when you are satisfied. Open Shambles with **no Claude Code sessions running**
when that happens. The repair briefly replaces `~/.claude`, and a live session
writes there constantly.

One unrelated note: Claude Code prunes sessions older than 30 days on its own.
Raise `cleanupPeriodDays` in `~/.claude/settings.json` to keep them longer.

### The one real caveat

**Do not switch while a Claude Code session is running.** A live session holds
its token in memory and rewrites `~/.claude.json` from time to time. If it
writes after Shambles does, the last writer wins and your spliced identity is
gone. The backups cover you. The clean habit is simpler: finish or close your
sessions, switch, then start fresh.

This is a race with another process, not something the tool can close from
outside. Claude Code holds no lock Shambles could wait on.

---

## The window, in detail

### Adding an account, step by step

You **cannot** lose your existing login this way. Shambles copies it into its
profile before replacing anything, so you can always get back by switching
back.

1. **Close any running Claude Code sessions**, in VS Code and in terminals.
2. **＋ Add Account** → pick the provider, type a name → **Create**. A
   provider whose CLI is missing from your PATH shows greyed out rather than
   hidden. A missing row reads as a bug; a greyed one reads as an instruction.
3. Shambles creates the profile and **makes it active right away**, empty,
   with no token. It has to. The vendor writes to one fixed place, so that
   slot must be free first.
4. A sign-in window opens and runs `claude auth login` (or `codex login`),
   streaming its output. Your browser should open on its own. If it does not,
   **Open sign-in page** and **Copy link** light up as soon as the URL
   appears. Under WSL and over SSH the link goes to your clipboard either way,
   because the browser openers there claim success while doing nothing.
5. On success Shambles tells you the account is signed in and active. **Start
   a new session** to pick it up.

If sign-in does not finish, Shambles switches you back to your previous
account and says so. It **keeps** the empty profile, so you can retry without
renaming anything.

### Every control

| Control | Where | What it does |
|---|---|---|
| **Switch** | Any card that is not live | Makes that account the one every surface uses |
| **✕** | Any card that is not live | Deletes that profile, after a confirmation naming it |
| Double-click the name | Any card | Rename the profile |
| **Save …** | Group heading, when a live login is unsaved | Files the current login as a new profile |
| **Forget that profile** | Group heading, if the active marker points at something gone | Clears the stale marker |
| **＋ Add Account** | Footer | Create a profile and sign into it |
| **Eject** | Footer | Hand every account back as a stock install |
| **⟳** | Footer, far left | Re-read what is on disk. Local files only, no network |
| **Details** / **Hide** | On a banner | Expand or collapse the explanation |

The live card has **no buttons at all**. You cannot delete the login you are
using by misclicking. The code enforces that, not just the layout.

Shambles picks the glyphs (`＋`, `⟳`, `✕`, `⚠`, `ⓘ`) at runtime based on what
your font can draw, falling back to `+`, `R`, `x`, `!` and `i`.

### Why dates stay off the card

A countdown on every row is noise on the days it does not matter. So the state
sits on the card and the numbers sit one hover away. Point at the name for the
exact expiry date, and at the chip for what to do. Anything with something to
say gives you a tooltip right away: the name, the chip, the ✕, the ⓘ next to a
usage bar, and both footer buttons.

### Banners

Two warnings can appear, each collapsed to one line with a **Details** button:

- **`codex not on PATH, can't add accounts`**. Switching between accounts you
  already saved still works. You just cannot create new ones until you install
  the vendor CLI.
- **`⚠ CLAUDE_CONFIG_DIR is set`**, in red, and the more serious of the two.

### Two things the window does on its own

Opening the window runs two migrations without asking, then tells you. It
merges session history that a pre-1.0 version split per account, and it moves
a v1.0 `~/.claude-profiles/` store into `~/.shambles/<provider>/`. Both only
add. Nothing is deleted, and the old copies stay on disk until you remove
them.

Refreshing is not quite read-only either. It re-saves the live credential for
providers that rotate tokens, and records the active account's usage into its
profile. Nothing leaves your disk.

---

## Desktop shortcuts

Tkinter apps launched through `python.exe` drag a blank terminal along behind
the window. Each install route has a quiet path:

| Route | Quiet launcher |
|---|---|
| Release binary | `shamblesw.exe`, installed next to `shambles.exe` |
| pipx / pip | `shamblesw`, the `gui-scripts` entry, backed by `pythonw.exe` |
| From a checkout | `pythonw.exe` on Windows, `python3` on Linux |

Windows gets two binaries because one cannot do both jobs. A console program
can print but flashes a terminal when launched from a shortcut. A windowed one
never flashes, and cannot print at all: Windows gives it no console, so Python
sets its `stdout` and `stderr` to `None`. So `shambles.exe` is the console
build, and `shamblesw.exe` the windowed twin.

Version 2.1.0 shipped only the windowed build, under the console name.
`shambles --version` printed nothing and then died on its first write to
stderr. Fixed in 2.1.1.

**Windows shortcut, from a checkout.** Right-click → New → Shortcut:

```text
Target:      C:\Path\To\python\pythonw.exe C:\Path\To\Shambles\shambles.py
Start in:    C:\Path\To\Shambles
Run:         Normal window
```

`pythonw.exe` sits next to `python.exe` in the same install. Check with
`where pythonw`. Avoid `cmd /c` and `start`, which both bring the console
back.

**Windows shortcut, installed with the script:** target
`%LOCALAPPDATA%\Shambles\shamblesw.exe`.

**Windows shortcut, pipx install:** target
`%USERPROFILE%\.local\bin\shamblesw.exe`.

**Linux desktop entry**, at `~/.local/share/applications/shambles.desktop`:

```ini
[Desktop Entry]
Type=Application
Name=Shambles
Comment=Switch Claude Code accounts
Exec=/home/you/.local/bin/shambles
Terminal=false
Categories=Development;Utility;
```

Run `update-desktop-database ~/.local/share/applications` afterwards if it
does not show up.

**Building the binary.** These are the commands the release workflow runs.
PyInstaller writes a `shambles.spec` as it goes. That file is generated and
untracked, so build from the flags rather than from a spec:

```bash
pip install pyinstaller

# Windows: --windowed is what suppresses the console window
pyinstaller --onefile --windowed --name shambles shambles/__main__.py

# Linux: no --windowed, or it swallows --version and --help output
pyinstaller --onefile --name shambles shambles/__main__.py
```

The binary lands in `dist/`.
