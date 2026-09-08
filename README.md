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

**Switch between Claude Code accounts — and Codex accounts — without waiting
for a verification email.** Three ways to drive it: a desktop window, a
terminal dashboard, and a plain CLI. All local, no account of yours is ever
contacted.

```bash
curl -fsSL https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.sh | bash
shambles
```

---

## Contents

**Getting started** · [Install](#install) · [Does it work on your setup?](#does-it-work-on-your-setup) · [Your first five minutes](#your-first-five-minutes)

**Using it** · [Command reference](#command-reference) · [The window](#the-window) · [The terminal dashboard](#the-terminal-dashboard) · [Update checks](#update-checks)

**Understanding it** · [What a switch actually does](#what-a-switch-actually-does) · [What it touches](#what-it-touches) · [Token health](#token-health) · [Is this safe?](#is-this-safe)

**Getting out** · [Leaving cleanly](#leaving-cleanly) · [Troubleshooting](#troubleshooting)

**Extras** · [Desktop shortcuts](#desktop-shortcuts-without-a-console-window) · [Development](#development) · [Platform notes](#platform-notes) · [Documentation](#documentation)

---

## The problem it solves

Claude Code hardcodes its config path to `~/.claude` and the VS Code extension
host ignores environment variables, so there is no supported way to run more
than one account. Codex has the same problem: `~/.codex/auth.json` is a single
file holding a single account.

Shambles keeps each account's login in its own folder and swaps exactly one
file into place:

```text
   ~/.shambles/                                    what the vendor reads
   │
   ├── claude/
   │   ├── Work/     credentials.json ─────┐
   │   │             account.json          ├──► ~/.claude/.credentials.json
   │   ├── Personal/ credentials.json ─────┘     ~/.claude.json  (identity key
   │   │             account.json                                 only, spliced)
   │   └── active  → "Work"
   │
   └── codex/
       ├── Personal/ credentials.json ─────────► ~/.codex/auth.json
       └── active  → "Personal"

   Everything else in ~/.claude — projects/, plugins/, settings.json,
   file-history/ — is never touched. Every account shares it, which is
   how Claude Code behaves on its own.
```

Adding an account opens your browser to sign in. Shambles does not implement
that: it runs the vendor's own `claude auth login` or `codex login`, which
opens the browser and handles the OAuth itself. See
[Is this safe?](#is-this-safe).

### Why this skips the login wait

Email verification is the *initial* OAuth grant only. What keeps you signed in
afterwards is the **refresh token**, valid for a rolling window that is
re-minted on every use. Preserve that per account and every later switch is
instant — an account only returns to the email flow if it sits entirely unused
long enough for that window to lapse.

How wide is the window? **It varies, so Shambles reads it rather than assuming.**
Measurements differ by an order of magnitude: ~28 days across three credential
blobs on Linux/Team, ~4 days on a macOS/Max 5x sample
([evidence](docs/token-storage.md)). The state chip reflects whatever your own
token says. What holds in every sample is the rolling behaviour — an account
you use regularly never approaches its deadline.

Rate limits are still enforced server-side per account. Switching gives you the
target account's own bucket; it does not pool or extend any single account's
allowance.

---

## Install

**One command.** The script picks the binary for your OS and architecture out
of the latest [Release](https://github.com/ianchendev/Shambles/releases) and
puts it in `~/.local/bin` — no sudo, nothing to build:

```bash
curl -fsSL https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.sh | bash

# or pin a release
curl -fsSL https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.sh | bash -s v2.0.0
```

**Windows PowerShell**, which installs into `%LOCALAPPDATA%\Shambles` and adds
that directory to your user PATH:

```powershell
irm https://raw.githubusercontent.com/ianchendev/Shambles/main/scripts/install.ps1 | iex
```

Two things worth knowing before you paste either one. The binaries are
**unsigned**, so Windows SmartScreen warns on first run — that is what an
unsigned publisher looks like. And **a successful install is not a working
switch**: the script fetches whatever binary matches your machine, which says
nothing about whether Shambles can swap an account there. The
[support table](#does-it-work-on-your-setup) is the part that says.

`install.sh` also knows the macOS and arm64-Linux asset names, but those
binaries are built for the first time by the *next* tagged release; against the
current latest release it gets a 404 there. Use pipx on those platforms until
then.

**Or pipx**, which involves no unsigned binary and works identically on Linux
and inside WSL:

```bash
sudo apt install python3-tk                              # only for the Tk window
pipx install git+https://github.com/ianchendev/Shambles
shambles
```

**Or download a binary** from [Releases](https://github.com/ianchendev/Shambles/releases)
yourself — a single file, nothing to install. Same unsigned caveat as above.

**Or from a clone.** Textual is a real dependency, so a bare checkout is not
runnable until you install it:

```bash
git clone https://github.com/ianchendev/Shambles && cd Shambles
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/shambles
```

`python3` here has to be **3.10 or newer**. On distributions where it is still
3.8 — Ubuntu 20.04 among them — name the interpreter instead
(`python3.12 -m venv .venv`); running it on an older one stops with a message
saying so rather than a syntax error from somewhere in the package.

`python3 shambles.py` works too, but only once the dependency is on that
interpreter's path. Without it you get a message telling you exactly that,
not a traceback.

**Not npm, yet.** Shambles is not published to npm, so `npm install -g
shambles` fails today. A launcher package is designed and planned
([plan](docs/superpowers/plans/2026-09-06-npm-distribution.md)) but stays
unpublished until the macOS and Windows credential-store work below is
resolved — shipping a one-line install to platforms where switching does not
work is exactly the thing this README is trying not to do.

### Does it work on your setup?

| Where you run it | Claude Code | Codex |
|---|---|---|
| Linux desktop | **Supported** | **Unverified** — see below |
| WSL (Ubuntu etc.) | **Supported** — the **Linux** build, run **inside WSL** | **Unverified** |
| Windows natively | **Unverified, probably not working** — see below | **Unverified** |
| macOS | **Not supported** — see [Platform notes](#platform-notes) | **Unverified** |

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
has confirmed an account switch actually takes effect there. The evidence is in
[docs/token-storage.md](docs/token-storage.md).

**WSL is the sharp edge.** A Windows `.exe` manages
`C:\Users\<you>\.claude`, which is a *different* Claude Code installation from
the one in your WSL home directory. If you use Claude Code inside WSL, install
inside WSL.

**Windows needs Developer Mode** (Settings → System → For developers) only when
migrating from a pre-1.0 layout, which used symlinks. Ordinary switching needs
no special privileges.

### Try it without touching your real accounts

Every command takes `--home`, which points the whole program at a different
directory. Nothing outside it is read or written, which is also how the test
suite runs:

```bash
shambles list --home /tmp/scratch      # an empty synthetic home
shambles gui  --home /tmp/scratch      # the window, against nothing real
```

---

## Your first five minutes

**1. Save the account you are already signed in as.** Open the window
(`shambles gui`) or the dashboard (`shambles`). Your current login shows up
under its provider with a **Save …** button — the button is labelled with the
address it found, e.g. `Save work@example.com`. Click it, name the profile
`Work`, and Shambles copies that login into `~/.shambles/claude/Work/`.
Nothing moves, nothing is deleted.

**2. Add your second account.** Click **＋ Add Account**, pick the provider,
name it `Personal`. Shambles creates the empty profile, makes it active, then
runs the vendor's login command and shows you its output while your browser
opens. This is the one and only time you wait for that account's verification
email.

**3. Switch.** Every account that is not the live one has a **Switch** button.
Click it, then **start a new session** — a Claude Code process already running
keeps the token it loaded at startup. In VS Code, run *Developer: Reload
Window*.

That is the whole loop. From then on, switching is a single click or a single
keystroke, and no email is involved again.

---

## Command reference

`shambles` with no arguments opens the terminal dashboard when stdin *and*
stdout are both a real terminal. Piped, redirected, or run from a script, it
prints usage instead and changes nothing.

| Command | What it does |
|---|---|
| `shambles` | The terminal dashboard, on an interactive terminal |
| `shambles tui` | The terminal dashboard, explicitly |
| `shambles gui` | The desktop window |
| `shambles list` | Every account and its state, as text |
| `shambles list --json` | The same thing, machine-readable |
| `shambles switch <provider> <account>` | Switch without opening an interface |
| `shambles switch … --json` | The same, with a machine-readable result |
| `shambles config get update.check` | Prints `true` or `false` |
| `shambles config set update.check true` | Turn release notices on |
| `shambles config set update.check false` | Turn them off again |
| `shambles --version` | The version, one line on stdout |
| `shambles --help` | The usage message |

Flags accepted anywhere, before or after the subcommand:

| Flag | Effect |
|---|---|
| `--home <dir>` | Use `<dir>` instead of your home directory. Nothing outside it is read or written |
| `--no-motion` | Disable nonessential terminal motion (`SHAMBLES_NO_MOTION=1` does the same) |

Exit codes: **0** success, **1** the action was refused or failed (the reason
goes to stderr, or into the JSON when `--json` was asked for), **2** the
command line itself was wrong.

```console
$ shambles list
Claude Code  (Terminal, VS Code)
    Personal       personal@example.test  ·  claude_pro  ·  needs login
  * Work           work@example.test  ·  claude_max  ·  session 22%  ·  week 58%

Codex  (Terminal, VS Code, ChatGPT)
  * Personal       alex@example.test  ·  plus

$ shambles switch claude Personal
Switched claude to Personal.
  Run 'claude auth login' in a terminal.
```

The `*` marks the live account. `--json` prints the same snapshot the window
and the dashboard render from, so a display bug and a logic bug can be told
apart without a debugger.

---

## The window

`shambles gui` opens a fixed-width 860 px window titled **Shambles**. It is not
resizable; its height grows with your accounts up to 80% of the screen, and a
scrollbar appears only if it needs to.

```text
┌──────────────────────────────────────────────────────────────────┐
│ CLAUDE CODE                                    [ Save … ]        │  ← group heading:
│ Work                                                             │       provider, live profile,
│ work@example.com                                                 │       and what it found
│                                                                  │
│ ┃ Work                                                           │  ← the live account: blue
│ ┃ work@example.com                                               │       spine and tint, and
│ ┃ session ▓▓▓▓▓▓░░░░░░░░░░░░░░░░░  22% ⓘ                         │       no buttons at all
│ ┃ week    ▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░  58% ⓘ                         │
│                                                                  │
│ │ Personal                    [ Switch ]   ✕                     │  ← every other card
│ │ personal@example.com   needs login                             │
│                                                                  │
│ CODEX                                                            │
│ Personal                                                         │
│ alex@example.com                                                 │
│                                                                  │
│ ┃ Personal                                                       │
│                                                                  │
├──────────────────────────────────────────────────────────────────┤
│ ⟳                            [ Eject ]   [ + Add Account ]       │  ← footer, always there
└──────────────────────────────────────────────────────────────────┘
```

There is no menu bar, no toolbar and no right-click menu. Everything is on
screen.

### Every control

| Control | Where | What it does |
|---|---|---|
| **Switch** | On each card that is not live | Makes that account the one every surface uses |
| **✕** | On each card that is not live | Deletes that profile, after a confirmation naming it |
| Double-click the name | Any card | Rename the profile |
| **Save …** | Group heading, when a live login is unsaved | Files the current login as a new profile |
| **Forget that profile** | Group heading, if the active marker points at a profile that is gone | Clears the stale marker |
| **＋ Add Account** | Footer | Create a profile and sign into it |
| **Eject** | Footer | Hand every account back as a stock install |
| **⟳** | Footer, far left | Re-read what is on disk. Local files only, no network |
| **Details** / **Hide** | On a banner | Expand or collapse the explanation |

The active card deliberately has **no buttons at all** — the login you are
currently using cannot be deleted by a misclick, and that rule is enforced in
the code, not just in the layout.

The glyphs above (`＋`, `⟳`, `✕`, `⚠`, `ⓘ`) are chosen at runtime from what
your font can actually draw, falling back to `+`, `R`, `x`, `!` and `i`. Do not
be surprised if yours look plainer.

### What a card tells you

A card carries the profile name, the email, and a state chip **only when
something needs your attention**:

| Chip | Meaning |
|---|---|
| *(nothing)* | Healthy, or an expiry that cannot be read. Nothing to do |
| `soon` (amber) | The refresh window closes within a day (Claude) or two (Codex) |
| `needs login` (red) | The window has closed, or this profile has no credential yet |
| `signed out` (red) | The login was cleared — the profile and its details are intact, the token is empty |

**Dates are deliberately off the card face.** A countdown on every row is noise
on the days it is not urgent, so the state stays on the card and the numbers
stay one hover away: point at the name for the exact expiry date, and at the
chip for what to do about it. Hovering anything with something to say gives you
a tooltip immediately — the name, the chip, the ✕, the ⓘ beside a usage bar,
and both footer buttons.

Usage bars are read from the figures the vendor caches for that account, not
fetched. They turn red at 80%, and a figure older than an hour is dimmed and
labelled `as of 20m ago` so a stale number is never mistaken for a live one.

### Adding an account, in detail

Your existing login **cannot** be lost by this. It is copied into its profile
before anything is replaced, so the account you are leaving is always
recoverable by switching back.

1. **Close any running Claude Code sessions**, in VS Code and in terminals.
2. **＋ Add Account** → pick the provider, type a name → **Create**. A provider
   whose CLI is not on your PATH appears greyed out rather than hidden, because
   a missing row reads as a bug while a greyed one reads as an instruction.
3. Shambles creates the profile and **makes it active immediately** — empty,
   with no token. It has to: the vendor writes to one fixed location, so that
   slot must be free first.
4. A sign-in window opens and runs `claude auth login` (or `codex login`),
   streaming its output as it goes. Your browser should open on its own. If it
   does not, **Open sign-in page** and **Copy link** light up as soon as the
   URL appears — under WSL and over SSH the link is copied to your clipboard
   regardless, because the openers there report success while doing nothing.
5. On success you are told the account is signed in and active. **Start a new
   session** to pick it up.

If the sign-in does not complete, Shambles switches you back to the account you
were on and says so — and it **keeps** the empty profile, so you can retry
without renaming anything.

### Banners

Two warnings can appear, both collapsed to one line with a **Details** button:

- **`codex not on PATH — can't add accounts`** — switching between accounts you
  already saved still works; you just cannot create new ones until the vendor
  CLI is installed.
- **`⚠ CLAUDE_CONFIG_DIR is set — /some/path`** — red, and the more important
  of the two. See [If CLAUDE_CONFIG_DIR is set](#if-claude_config_dir-is-set).

### Two things the window does on its own

Opening the window runs two migrations without asking, and tells you
afterwards: it merges session history that a pre-1.0 version had split per
account, and it moves a v1.0 `~/.claude-profiles/` store into
`~/.shambles/<provider>/`. Both are additive — nothing is deleted, and the old
copies stay on disk until you remove them.

Refreshing is also not quite read-only: it re-stashes the live credential for
providers that rotate tokens, and captures the active account's usage figures
into its profile. Nothing leaves your disk.

---

## The terminal dashboard

`shambles` opens a keyboard-driven dashboard instead of the window whenever
it is run on an actual interactive terminal. No `DISPLAY`, no Tk, works the
same over SSH.

It is a second front end on the same core, not a separate tool. Switching here
has the identical effect, and the identical restart requirement, as switching
anywhere else.

### Keys

| Key | Action |
|---|---|
| `j` / `↓` | Next account |
| `k` / `↑` | Previous account |
| `Enter` | Switch to the selected account |
| `a` | Add — pick a provider and name in an overlay |
| `l` | Log in the selected account (runs the vendor's own login command) |
| `m` | Account menu — save the current login, rename, remove |
| `x` | Eject — see [Leaving cleanly](#leaving-cleanly) |
| `r` | Refresh |
| `u` | Dismiss the update notice, if one is showing |
| `?` | Help |
| `Esc` | Close whatever is open |
| `q` | Quit |

Inside the account menu: `s` save current, `n` rename, `d` remove, `Esc`
cancel. Every confirmation, result and login-progress screen takes `Enter` to
continue and `Esc` to cancel. The footer lists the first-class keys, and the
same reference is one keystroke away in the app: press `?`.

### Straight back into the vendor CLI

After a successful switch, the result screen offers **Launch** next to Escape.
Choosing it closes the dashboard — Textual restores the terminal first — and
replaces the Shambles process in place with `claude` or `codex` (`execvp`, not
a child process), inheriting the environment unchanged. There is no second
window: the terminal `shambles` was running in becomes the vendor CLI's
terminal, immediately signed in as the account you just switched to.

### Colour and motion

`NO_COLOR` — the [convention](https://no-color.org), detected automatically —
makes the whole interface monochrome. `--no-motion` and `SHAMBLES_NO_MOTION=1`
disable nonessential animation. For the window, `SHAMBLES_MOTION=0` does the
same and `SHAMBLES_SCALE` (between 1.0 and 4.0) overrides display scaling.

---

## Update checks

**Off by default**, and off means off: with the setting unset, no interface —
terminal, window, or `shambles switch` — makes a network call of any kind.
Nothing here reports usage or phones home under any setting.

```bash
shambles config set update.check true     # turn it on
shambles config get update.check          # prints true or false
shambles config set update.check false    # turn it off again
```

What that signs you up for, in full: at most one unauthenticated `GET` per day
to the public GitHub Releases endpoint for this repository, from which Shambles
reads one field — the tag of the latest release. No token, no account, no
machine ID and no query string go with it, so nothing in the request says who
you are. The only thing kept is `~/.shambles/update-cache.json`, holding that
tag and the time of the lookup. A failed lookup still counts as the day's
attempt, so an offline machine is not made to sit through a connection timeout
on every start, and a lookup that fails for any reason produces silence rather
than an error.

**It never downloads or replaces anything.** The entire feature is one sentence
saying a newer version exists; fetching it stays your decision.

Where that sentence appears:

- **In the terminal dashboard** — one line at the bottom, and `u` dismisses it
  for the session. The lookup runs on a background thread after the first frame
  is drawn, so a slow network cannot hold up the interface, and quitting does
  not wait for it.
- **On `shambles --version`** — printed to stderr, and only from the cache an
  earlier run already filled. `--version` itself never makes a request, which
  keeps its stdout exactly one line for the scripts that read it.

The window shows no notice and performs no lookup, whatever the setting says.

---

## What a switch actually does

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

   4  splice identity into ~/.claude.json — oauthAccount only, every other
      key and its original order preserved

   5  record it:  ~/.shambles/claude/active  ←  "Personal"
```

A **running** session is unaffected: it holds the token it loaded at startup.
Start a new `claude` session, or run *Developer: Reload Window* in VS Code.

### CLI or VS Code extension — both

The `claude` CLI and the VS Code extension are the same product reading the
same two paths, so swapping the login swaps it for both at once:

```text
~/.claude/.credentials.json      the login
~/.claude.json                   oauthAccount, projects, MCP servers
```

Verified by running the standalone CLI and watching it read and write the same
`~/.claude` the extension uses.

### Why not just use `CLAUDE_CONFIG_DIR`?

Claude Code honours `CLAUDE_CONFIG_DIR`, and pointing it somewhere per account
looks like it would do the same job without any of this. It does not: it moves
the **entire** config tree, so each account gets its own `projects/` directory
and your session history splits per account. That is precisely the bug this
tool used to have and no longer does.

It also does not help inside VS Code, where the extension host does not see
shell environment variables.

### If CLAUDE_CONFIG_DIR is set

Shambles swaps the login inside `~/.claude`, so a shell with that variable set
reads a tree Shambles never touches and every switch appears to do nothing
there. Shambles detects this on startup and shows a warning naming the
directory. To use Shambles from the terminal, remove the variable from your
shell profile. The VS Code extension is unaffected either way — the extension
host does not inherit shell environment variables, which is the reason this
tool exists.

---

## What it touches

Only your **login** is account-scoped. Everything else in `~/.claude` is
machine-scoped and stays shared.

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

### Where the tokens live

```text
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

Directory permissions: `~/.shambles/` and each directory inside it are created
`700`, and every credentials file is written `600`. On Windows `chmod` cannot
express either, so there the files rely on the user profile's own ACLs — the
same protection Claude Code's own `.credentials.json` gets.

---

## Token health

"Closing" means one day or fewer for Claude Code, two for Codex — not the week
you might expect. The windows differ by an order of magnitude across platforms
and plans (see [docs/token-storage.md](docs/token-storage.md)), and against a
measured window of roughly four days a seven-day threshold would leave every
profile permanently amber. Each provider sets its own figure in its spec.

Two things worth understanding:

- **Ignore the access token.** It expires within hours and is refreshed
  automatically. Only `refreshTokenExpiresAt` decides whether you face the
  email flow again.
- **The clock resets on use, not on the calendar.** Every refresh mints a
  replacement with a fresh window. Rotating between accounts normally keeps all
  of them alive indefinitely; an account parked and untouched for 30+ days is
  the only one that needs a new login.

### Why an expired token is left in place

Shambles never deletes a `.credentials.json`, even a long-dead one. That is
deliberate:

- **Clock drift makes deletion dangerous.** WSL2's clock can jump when Windows
  resumes from sleep. A drifted clock would mark a perfectly good token dead,
  and an automatic delete would then cost you a real verification email — the
  exact thing this tool exists to avoid. A wrong label is recoverable; a
  deleted refresh token is not.
- **It is diagnostic.** The lapsed file is what lets the UI distinguish "this
  account expired twelve days ago" from "never logged in here".
- **It is never in the way.** Switching to a lapsed profile is not an error.
  Shambles does not validate tokens; it copies a file. Claude Code then fails
  its refresh and prompts `/login`, which overwrites it anyway.

<details>
<summary>A countdown for every profile, without opening the app</summary>

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

</details>

---

## Is this safe?

**It is entirely local and cannot touch your Claude or OpenAI account.**

**No network, with one exception you have to switch on yourself.** Shambles
cannot reach Anthropic's or OpenAI's servers at all, so it cannot affect your
login, billing, rate limits or organisation membership; it only moves bytes
between directories on your own disk. The single module that may open a socket
is `shambles/update_check.py`, which asks GitHub for the latest release tag and
runs only once you have enabled [update checks](#update-checks). That division
is not a promise: `tests/test_login.py` walks the AST of every module in the
package, fails on any networking import, and permits `urllib` in that one file
and nowhere else.

**It executes exactly one kind of external program:** the vendor's own login
command — `claude auth login` or `codex login` — and only when you add an
account. **Shambles implements no part of signing in.** That command opens your
browser and runs its own callback server; Shambles waits for it to finish and
then files the credential it wrote. No password, no token in flight, and
nothing held that was not already on your disk.

What protects your data:

- Every write to `~/.claude.json` is preceded by a backup and performed
  atomically (temp file + `os.replace`), preserving all other keys and their
  original order.
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
  in. Removing a profile is possible but never automatic.
- `~/.claude` is never moved, replaced or deleted.

### Your session history is shared

Session transcripts live in `~/.claude/projects/`, keyed by project path rather
than by account, and Shambles leaves that directory alone. Every account sees
every session, exactly as it does without Shambles installed.

**Versions before 1.0 got this wrong.** They swapped the whole `~/.claude`
directory, so each account had its own `projects/` folder and switching
appeared to erase weeks of history. If you used one of those, Shambles repairs
it the next time you open the window — automatically, with nothing to click.
The merge is additive: nothing is deleted, and the old profile folders stay on
disk for you to remove once you are satisfied. Open Shambles with **no Claude
Code sessions running** when that happens; the repair briefly replaces
`~/.claude`, and a live session writes there continuously.

Unrelated but worth knowing: Claude Code prunes sessions older than 30 days on
its own. Raise `cleanupPeriodDays` in `~/.claude/settings.json` to keep them
longer.

### The one real caveat

**Do not switch while a Claude Code session is running.** A live session holds
its token in memory and rewrites `~/.claude.json` periodically. If it writes
after Shambles does, last-writer-wins and the spliced identity is clobbered.
The backups cover you, but the clean habit is: finish or close your sessions,
switch, then start fresh.

This is a race with another process, not a flaw the tool can fully close from
the outside — Claude Code holds no lock Shambles could wait on.

---

## Leaving cleanly

Do **not** uninstall by deleting `~/.shambles/`. That folder holds the refresh
tokens for every account you saved, and each one is only recoverable through a
fresh verification email.

Use **Eject** instead — the footer button in the window, or `x` in the
dashboard. It leaves `~/.claude` exactly as a stock install expects, still
signed in as the current account, with history, plugins and settings untouched,
and removes only Shambles' own bookkeeping. It tells you what it did and where
your saved logins still are, so removing them stays a decision you make
deliberately rather than a side effect of uninstalling.

Eject never deletes a credentials file. Afterwards, remove the program itself:

```bash
# installed with the script
rm ~/.local/bin/shambles

# installed with pipx
pipx uninstall shambles

# and, once you are sure you want the saved logins gone for good
rm -rf ~/.shambles
```

### Removing a single account

Each inactive profile carries a **✕** beside its Switch button; the active one
has none. Confirming deletes that profile's directory and the refresh token in
it, so that account needs a fresh login and its verification email to come
back. Nothing else is affected: session history, plugins and settings are
shared and live elsewhere.

---

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `No module named 'textual'` | A clone whose dependencies were never installed. `pip install -e .` in the checkout, or use pipx |
| `Shambles needs Tkinter` | Only the window needs it. `sudo apt install python3-tk`, or use `shambles` / `shambles tui` instead |
| `shambles: command not found` after the install script | `~/.local/bin` is not on your PATH. The script prints the line to add |
| Switching seems to do nothing | A session that was already running keeps its old token. Start a new one, or *Developer: Reload Window* in VS Code |
| Switching does nothing, in every new session too | `CLAUDE_CONFIG_DIR` is set, or you are on Windows/macOS — see [the support table](#does-it-work-on-your-setup) |
| The window will not close | `Ctrl+C` in the launching terminal works, and so does `kill <pid>`. If it is stopped rather than frozen: `pkill -CONT -f shambles && pkill -f shambles` — a stopped process cannot act on `SIGTERM` until it is resumed |
| A provider is greyed out in Add Account | Its CLI is not on your PATH. Shambles runs the vendor's own login command, so it needs `claude` or `codex` installed |
| Windows SmartScreen warns | The binaries are unsigned. Use pipx if you would rather not click through it |

The window's `Ctrl+C` handling is worth a note, because Tk does not give it to
you for free: `mainloop()` blocks inside C, while Python only dispatches signal
handlers between bytecode instructions, so by default `Ctrl+C` is recorded and
never delivered. Shambles keeps a 150 ms no-op timer running purely so signals
land. Covered by `tests/test_shutdown.py`.

---

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

```text
Target:      C:\Path\To\python\pythonw.exe C:\Path\To\Shambles\shambles.py
Start in:    C:\Path\To\Shambles
Run:         Normal window
```

`pythonw.exe` sits next to `python.exe` in the same install. Confirm with
`where pythonw`. Nothing else is required — no `cmd /c`, no `start`, both of
which reintroduce the console.

**Windows shortcut, pipx install:** target `%USERPROFILE%\.local\bin\shamblesw.exe`.

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

Run `update-desktop-database ~/.local/share/applications` afterwards if it does
not appear.

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

The binary lands in `dist/`.

---

## Development

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

970+ tests. Every one runs against a synthetic home in `tmp_path`. None reads
or writes your real `~/.claude`.

CI runs the suite on Linux and Windows across Python 3.10 and 3.12, under
`xvfb` so the GUI render and shutdown tests actually execute rather than skip.
Tagging `v*` builds unsigned single-file binaries for Linux (x86_64 and arm64),
macOS (Intel and Apple Silicon) and Windows x64, and attaches them to a GitHub
Release — but each binary is built only after the suite passes on that
platform, and none is published unless all five build.

The load-bearing test is
`tests/test_switch.py::test_credentials_survive_a_round_trip_unmodified` — it
asserts that `Work → Personal → Work` leaves the credential byte-identical,
refresh token and expiry included. It is parametrized over every provider, so
adding a third means passing a suite that already exists. If it regresses, the
tool stops solving the problem it exists for.

Nothing here runs a real `claude` or `codex`. The login tests drive a `/bin/sh`
stand-in placed on `PATH`, so no browser opens and nothing authenticates.

---

## Platform notes

Developed and verified on WSL2 Ubuntu with WSLg, Python 3.12, Tk 8.6. A
`Switch` click was confirmed to swap the token and the displayed email
together. The Windows code paths (`target_is_directory=True`, the WinError 1314
Developer Mode message) are written to spec but **have not been exercised** —
there was no Windows-side Claude Code install to test against.

**macOS is not supported.** Claude Code stores credentials in the system
Keychain there rather than in `.credentials.json`, so there is no file for
Shambles to swap.

Run Shambles inside whichever environment you actually use Claude Code in. A
Windows build manages `C:\Users\<you>\.claude`, which is a different
installation from the one in a WSL home directory.

---

## Documentation

| Document | What it is |
|---|---|
| [docs/superpowers/specs/2026-08-07-multi-provider-design.md](docs/superpowers/specs/2026-08-07-multi-provider-design.md) | **Current** design: the provider/store layering, Codex as a peer, and the browser login handoff |
| [TECH_SPEC.md](TECH_SPEC.md) | Architecture reference. Its §-numbered mechanism is authoritative; its single-provider paths describe v1.0 and are superseded — the banner says which |
| [docs/token-storage.md](docs/token-storage.md) | Field research into how Claude and Codex store credentials across macOS, Windows and Linux. Covers platforms this tool does not yet support |
| [docs/design-decisions.md](docs/design-decisions.md) | Recorded decisions and rationale. DD-4 is implemented; DD-2 is amended — the tool now starts the vendor's login rather than printing it |
| [SECURITY.md](SECURITY.md) | The security posture, and the one opt-in network call |

Where two documents disagree about what the tool does today, the multi-provider
design wins on anything provider-shaped — paths, layering, login, the store
layout — and TECH_SPEC wins on mechanism: switch ordering, atomic writes,
permissions, the state machine, concurrency.

The tests win over both.
