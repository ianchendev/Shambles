# Changelog

Notable changes per release. Dates are the tag date.

## Unreleased

### Changed

- **Claude logins are now kept current, as Codex logins already were.**
  Claude Code replaces its refresh token every time it refreshes, which was
  not known when Shambles was written: a saved copy taken before a refresh
  holds a token that no longer works. The active Claude profile is now saved
  again after its login refreshes, but only when the login provably continues
  that profile's own, never because `~/.claude.json` names its address.
- **Shambles no longer decides by itself, from an address, whose login is
  live.** When you sign in outside Shambles as an account you have saved, the
  label no longer moves on its own: the interface says which saved account
  the login names, and switching to that account files the login there,
  keeping the one it replaces. The address comes from `~/.claude.json`, which
  a Claude Code session still running rewrites, and trusting it filed one
  account's login over another's. When the login itself proves it, the label
  still moves on its own.

### Added

- **A saved login is no longer replaced without a copy.** When Shambles
  saves the live login over a profile's saved one and the two are different
  logins, the old one is kept beside it as `credentials.json.previous`
  (owner-only, like the rest). Shambles works out whose a Claude login is
  partly from `~/.claude.json`, which a Claude Code session still running
  can rewrite, so it can file a login under the wrong profile; this makes
  that recoverable by renaming the file back. A routine token refresh of the
  same login does not replace the kept copy, and a login that has been
  signed out never replaces one that still works.
- **Sign a lapsed account back in from the window.** A card marked `needs
  login` or `signed out` now offers **Sign in** in place of Switch, the live
  card included. It runs the vendor's own login with the address filled in
  (Claude), saves the renewed login under the same profile and leaves it
  active. Until now the only way back was to remove the profile and add it
  again, which also threw away its name and usage history.

  A cancelled or failed sign-in puts you back on the account you were using.
  A sign-in that comes back as a different account, usually because the
  browser was still signed in as someone else, saves nothing over the profile
  and says which address the browser used.

- **Adding an account in the terminal UI signs it in.** `a` used to create
  an empty profile, switch to it and stop, which signed you out of the
  account you were on and left the new one with no login. It now runs the
  vendor's sign-in straight away, as the window does, and puts you back on
  your previous account if the sign-in is cancelled or fails. The profile is
  kept so you can retry without naming it again.

- **A new window, in preview: `shambles gui --new`.** Rebuilt in Qt on the
  same service the terminal UI uses. One resizable column: each provider's
  live account on top with its usage, everyone else as rows beneath. What is
  different from the classic window:

  - Nothing opens a separate dialog. Adding, signing in, renaming, removing
    and ejecting happen in a sheet inside the window, and results are said in
    words at the bottom instead of in a message box.
  - Signing in shows steps and who to sign in as, not the vendor's raw
    output. **Open sign-in page** and **Copy link** appear when the vendor
    prints a link.
  - A row opens to show the exact date its saved login is good until, which
    used to live only in a tooltip.
  - Keyboard: `1` to `9` switch to an account, `/` filters once there are
    seven or more, `Ctrl+N` adds, `Ctrl+R` refreshes, `Esc` closes.
  - Light and dark, under the `...` menu. It follows the system where Qt can
    tell and remembers your choice where it cannot, which includes WSL.
  - While you are signed in as an account that is not saved, switching is
    held back until you save it. The classic window let the click through
    and relied on the core to refuse.

  It needs PySide6, which is an optional extra: `pip install 'shambles[gui]'`.
  The release binaries do not carry it yet, and plain `shambles gui` still
  opens the classic window.

- **`shambles list --json` says more about each account.** Every group now
  carries `can_sign_in` and `cli` (whether the vendor's command is there to
  run, and its name). Every account carries `expires_at_ms` and
  `status_label`, and every usage window carries `severity` and a filled-in
  `resets_at_ms`. All additions; nothing existing changed, and the contract
  version stays at 1.

### Fixed

- **`CLAUDE_CONFIG_DIR` is followed for the account details too, not only
  the login.** With the variable set, Claude Code keeps its config, including
  which account is signed in, in that directory. Shambles still read and
  updated `~/.claude.json`, so it showed whoever last used the default
  location, refused switches as "signed in as someone else", and wrote the
  switched-to account into a file Claude Code was not reading. It now uses
  the same file Claude Code does.
- **One address in two organisations is no longer treated as one account.**
  With a personal subscription and a Team or Console seat under the same
  address, or two ChatGPT workspaces, Shambles saw one account: the "signed in
  as someone else" warning never appeared between them, and a switch could
  file one login's token over the other's saved one. The organisation (Claude)
  and the ChatGPT account (Codex) now count too, the warning names them when
  the addresses match, and usage figures from the other organisation are no
  longer filed under this one.
- **Claude accounts no longer claim that using them renews their login.** A
  Claude login lasts about 30 days from when you signed in, and using the
  account does not push that date back: Claude Code refreshes the token, but
  the deadline stays where it was. The tooltip said "Using the account renews
  it", and the documentation said an account in daily use never needs signing
  in again. Both are corrected, and a Claude card now turns `soon` with fewer
  than four days left instead of one, a day before Claude Code's own warning.
- **A switch no longer waits and tries again when a file is busy.** It did
  that only for the `~/.claude.json` backup, and doing it for the login
  itself would have been worse: a write that waits out whatever is holding
  the file then overwrites what that program wrote, which could be a token
  Codex or Claude Code had just replaced. A switch that meets a busy file now
  stops before anything has moved and says so; try it again.
- **A cancelled or failed sign-in in the terminal UI puts you back where you
  were.** Pressing `l` and then Esc, or a sign-in that wrote nothing, left the
  expired account live and the working one signed out, with "The vendor
  login command failed. Review the output and retry." on screen. Each outcome
  now has its own message and says which account you are on.
- **Enter on an account that needs a login signs it in** in the terminal UI,
  instead of switching to it and installing its dead token. The details pane
  said it could not be switched to; now it says "Enter or l to sign in".
- A missing `claude` or `codex` CLI is reported before anything moves. The
  terminal UI used to switch to the account first and then say the CLI was
  missing.
- **Adding an account that is already saved is refused**, in the window and
  the terminal UI. With the browser still signed in to a saved account,
  adding a new one reported success and kept a second copy of the same
  account under the new name. It now saves nothing, puts you on the account
  that login belongs to, and says to use a private window.
- A sign-in in the terminal UI that comes back as somebody else's account
  says whose it was, instead of "The vendor did not write a usable login".
- The terminal UI no longer tells you to "Run 'claude auth login' in a
  terminal" for a parked account. Run that way it signs in whichever account
  is live, not the one you were looking at.
- **The window opens when the live login cannot be read.** A credential
  file with the wrong permissions, or a locked Keychain, made the window exit
  with a traceback before it appeared. It now opens and says which login it
  cannot read.
- **A first run while already signed in can save that login from the
  terminal UI.** The welcome said "Press a to add your first account", `a`
  refused with "Save your current account first", and nothing on screen could
  do that. The welcome now names the login and `s` saves it, from any screen.
- **The terminal UI and `shambles list` say what is true about each
  provider:** a login nobody saved, the marked profile missing from disk, a
  saved account signed in under the wrong marker, a credential store that
  cannot be read, or `CLAUDE_CONFIG_DIR` / `CODEX_HOME` pointing elsewhere.
  Each comes with the key or command that deals with it. Before, signed in as
  an unsaved account, both showed the marked profile as active under the
  stranger's address.
- **Signed in under a stale marker, switching to the right account works.**
  If you signed in again through the browser as another saved account, the
  CLI and terminal UI refused to switch to it, with a message telling you to
  switch to it. They now correct the marker first, as the window always has.
- `shambles switch` and the terminal UI's switch result warn when
  `CLAUDE_CONFIG_DIR` or `CODEX_HOME` means a terminal started from here will
  not see the switch.
- `shambles switch claud Work` names the providers that exist instead of
  printing "claud".
- The window's heading no longer says "Not signed in" or "Not sure which
  account is live" while a login it can name is live, and offers to save it
  when the marked profile has been deleted.
- At 80 columns the terminal UI's footer shows `l login` instead of
  `x eject`. The narrow footer had dropped the one key that fixes an account
  that needs a login; eject is still under `?`.
- The terminal UI no longer offers Remove for the active account, which it
  then refused after you confirmed. Removing another account now says what
  it costs: signing that address back in needs a new verification email.
- The terminal UI's eject confirmation says what eject does before asking.
  It used to show only the after-the-fact summary, as if it had happened.
- **`shambles doctor`.** Checks whether switching can work on this machine
  and says why not, without changing anything. It reports an environment
  variable that makes the vendor ignore its stored login (`ANTHROPIC_API_KEY`
  and friends, `CODEX_ACCESS_TOKEN`), a `claude` inside WSL that is really
  the Windows install, Codex not keeping its login in `auth.json`, a
  relocated config directory, a missing vendor program, and where each login
  is kept. Exits 1 on a problem; `--json` for scripts.

- **A native Windows on Arm binary**, `shambles-windows-arm64.exe`, and an
  installer that picks it. On releases without one the installer falls back
  to the x64 build, which Windows 11 on Arm runs under emulation.

- **macOS and native Windows are now exercised on every pull request.** A
  `real-machine` workflow installs the current Claude Code and Codex on
  GitHub's macOS, Windows and Linux machines, drives Shambles against the
  real Keychain and Credential Manager with made-up credentials, and asks the
  vendors' own commands who is signed in after each switch. The README's
  support table now says what that established and what it did not.

### Fixed

- **Switching Claude accounts on native Windows did nothing.** Shambles read
  and wrote the Credential Manager there, always, in a layout Claude Code
  does not use. Claude Code keeps its login in
  `%USERPROFILE%\.claude\.credentials.json` unless Credential Manager has
  been switched on for the account. So the live login read as absent, and a
  switch put the incoming credential where nothing looked, wrote the
  incoming account's name into `.claude.json` and reported success: the old
  login under the new name. Shambles now uses the file, and Credential
  Manager only when Claude Code itself does, in Claude Code's own layout.

- **A Mac signed in over SSH read as signed out.** When the Keychain refuses
  a write, Claude Code keeps the login in `~/.claude/.credentials.json`.
  Shambles only looked in the Keychain. It now reads the file when the
  Keychain is empty, as Claude Code does, and a switch moves the login into
  the Keychain and clears the file, as Claude Code's own next write would.

- **A locked Keychain was read as "no login".** It is now reported as locked,
  with the command that unlocks it. The Keychain is also given 60 seconds to
  answer instead of being waited on indefinitely.

- **`--home` could reach the real Keychain.** `shambles --home <dir>` is the
  documented way to try Shambles without risking a real login, but the
  Keychain belongs to the user, not to a directory, so on macOS a switch
  made for a scratch home would have replaced the real login. For any home
  but the real one, only files are used now. The same applies to the
  Windows Credential Manager.

- **Codex told to keep its login in the system keyring.** With
  `cli_auth_credentials_store` set to `keyring` or `auto`, Codex does not
  read `auth.json`, and Shambles swapped it anyway. It now refuses, names
  the setting and the file that set it, and touches nothing.

- **`CLAUDE_CONFIG_DIR` with a trailing slash, or Windows-style separators,
  on macOS.** Claude Code names its Keychain item after a hash of the
  variable exactly as typed. Shambles hashed a tidied copy and looked in an
  item that did not exist. The credentials file also now follows
  `CLAUDE_SECURESTORAGE_CONFIG_DIR`.

- **A process with no `USER` variable used the wrong Keychain item.** Started
  from a desktop launcher or launchd, Shambles fell back to a fixed account
  name where Claude Code asks the system for the real one.

- **A small login was visible in the process list during a Keychain write.**
  The write now goes through standard input when it fits, as Claude Code's
  does.

- **`install.sh` could leave a binary that cannot start.** On a glibc older
  than 2.35 it installed the file, then printed "Done". Both installers now
  run the download before replacing anything, refuse a download that fails
  its checksum, and say what to do instead. `install.sh` also recognises
  musl, Rosetta shells and Git Bash.

- **`install.ps1` changed the PowerShell session that ran it** and could
  rewrite the user's PATH with its variables expanded. It also now works
  under Windows PowerShell 5.1's defaults (TLS 1.2, the Restricted policy),
  over a running Shambles, and from `cmd.exe`.

- The tooltip on an expired account no longer says that using the account
  renews it. A closed window cannot be renewed that way; it now says to sign
  in again.
- **A `~/.claude` you symlinked yourself is no longer mistaken for the old
  Shambles layout.** With `~/.claude` linked from a dotfiles checkout or
  another drive, every Claude switch was refused with "still a symlink from
  an older version of Shambles". If an old `~/.claude-profiles` folder was
  still on disk as well, opening the window removed your link and put one of
  that folder's profiles in its place. Only a link that points at a profile
  inside `~/.claude-profiles` is converted now. Any other link is left exactly
  as it is, and switching works through it.
- **Converting the old layout no longer signs you in as a different
  account.** `~/.claude` became the folder of whichever profile had the most
  history, with that profile's login inside it, while Shambles went on
  showing the profile you had been using as the active one. The next switch
  then saved that login over the wrong profile and its own token was gone.
  You now stay signed in as the account you were using.
- **Converting the old layout, where `~/.claude` was a link to one profile's
  folder, now finishes on the next start if it was cut short.** A full disk
  or a crash partway through used to leave `~/.claude` converted while the
  other accounts' logins were never copied into the new store. Nothing tried
  again, so those accounts came back as empty profiles and each one needed a
  new verification email. Every login is now saved before `~/.claude` is
  touched, so an attempt that fails leaves the old layout in place and the
  next start completes it. The failure is shown in a dialog instead of a
  traceback, and a login already saved in the new store is never replaced by
  the older copy from the old folder. Session and history files are copied
  in one step each, so a full disk can no longer leave a cut-off file or an
  emptied prompt history behind.
- **Accounts saved with 1.0 are no longer left behind when something else
  created `~/.shambles` first.** Running `shambles config set update.check
  true` before the window had opened once, or saving a Codex account, made
  Shambles believe the move out of `~/.claude-profiles` had already happened.
  The window then opened with no Claude accounts and never looked again. The
  move now counts as done only once the Claude accounts are in the new store.
- **Moving accounts saved with 1.0 into the new store now finishes on the
  next start if it was cut short.** A full disk or a crash partway through
  the copy left the new store looking complete with some accounts missing,
  and nothing tried again. The copy is now put in place in one step once all
  of it has succeeded, and a failure is shown in a dialog instead of a
  traceback. An old settings snapshot that cannot be copied no longer holds
  the accounts back.
- A prompt history file or an old active marker that is not valid text (the
  last line cut short by a crash, for instance) no longer stops either
  conversion, which used to fail the same way at every start. A history
  entry containing a Unicode line separator is no longer split in two when
  histories are merged.
- A sign-in that Shambles refuses to start now says why in the terminal
  interface (for instance, that you are signed in as a different account),
  instead of only "The login could not be completed."
- **Switching no longer replaces a login that is saved nowhere.** With
  profiles saved but none marked active (the state Eject leaves behind, or a
  profile folder removed by hand), Switch, Add Account and Sign in used to
  overwrite whatever login was live without keeping a copy of it. They now
  stop and ask you to save it first. When the live login is already one of
  your saved profiles there is nothing to lose, and they carry on.
- **A switch that fails halfway can be finished by running it again.** If
  the login was replaced but the active marker could not be written, the next
  switch filed the new account's token under the old profile and destroyed
  the old one. Shambles now recognises the live login by its bytes, so
  running the switch again finishes it. This holds until the vendor next
  refreshes that login, so retry straight away.
- **A login file that is empty for a moment no longer wipes the saved
  token.** Claude Code and Codex both rewrite their login file in place, and
  a read that landed between the two halves of that saw an empty file.
  Shambles saved those zero bytes over the profile's token: on a switch, and
  for Codex on every refresh of the window with no click at all. An empty
  file is now treated as no login.
- **A Claude Code session left running no longer blocks switching.** A
  session still signed in as the previous account rewrites `~/.claude.json`,
  and Shambles then refused every switch with "Signed in as ..., but ...
  holds ...", about a login that was the right one all along. The stored
  login now settles which account is live, not the address in that file.
- A profile's saved address is no longer erased, or replaced with another
  account's, when `~/.claude.json` is briefly out of step with the login. An
  empty profile is no longer labelled with the previous account's address
  after a cancelled Add Account.
- Removing a profile is now refused when it is the only one holding the
  login that is live, even if the active marker names a different profile.
- A switch is no longer refused as "signed in as someone else" when nobody
  is signed in at all and only an old address is left in `~/.claude.json`.
- A refused Add Account no longer leaves an empty profile behind.
- Cancelling Add Account in one window no longer switches you back when you
  had already moved to another profile in a second window.
- Saving a login that one of your profiles already holds now marks that
  profile as the active one, instead of making a second copy under a new
  name.
- **A login file that cannot be read no longer stops Shambles opening.** When
  the vendor's credential store was locked or unreadable (a locked Keychain,
  a file held by another program), the window failed to start and the
  terminal UI could not refresh. Both now show what they can from the saved
  profiles. Switching is still refused until the store can be read, because
  the outgoing login could not be copied out first.
  A store that is busy for one read and free for the next can no longer get
  a login filed under the wrong profile: whose login it is gets decided from
  the same bytes that are about to be saved.
- A `~/.claude.json` caught halfway through being written, a damaged active
  marker, or a value in a vendor file that is not a real number (an expiry of
  `NaN`, a reset time no calendar reaches) no longer crashes the account
  list. The affected field is shown as unknown instead.

## 2.1.2 - 2026-09-11

### Fixed

- **The window could undo the account label of a switch you had just made.**
  Switching from the window installed the new token correctly, then its
  refresh moved the active marker straight back to the account you had left.
  The VS Code panel showed the old address and organisation while the usage
  bars showed the new account, because the token really had switched and only
  the label had not.

  Shambles decided which account was live by reading the address out of
  `~/.claude.json`. Claude Code owns that file and rewrites it from memory
  whenever a session is running, so a VS Code session doing that seconds after
  a switch fed Shambles the previous account's address as fact. The terminal
  interface never showed this because it does not correct the marker at all.

  Ownership is now settled by the credential: a stashed copy that matches the
  live one byte for byte is proof no other process can forge. The address
  check remains the fallback, which is what Codex's rotating token and a
  never-stashed browser login both need. The same evidence now protects
  `belongs_to`, so a rewritten config can no longer make Shambles refuse to
  re-stash a login it installed itself.

  Reloading the VS Code window is still what makes the extension re-read the
  file. Nothing here can stop another process writing its own config; this
  stops Shambles being misled by it.

## 2.1.1 - 2026-09-11

Both bugs below shipped in 2.1.0, built green, and passed their own smoke
tests. Each one only failed on a machine other than the one that built it.

### Fixed

- **The Linux binaries would not start on Ubuntu 22.04, Debian 12 or RHEL 9.**
  PyInstaller bundles the build machine's shared libraries, and 2.1.0 was
  built on Ubuntu 24.04, so `libpython`, `libcrypto` and `libX11` all carried
  a `GLIBC_2.38` requirement. Anything older reported
  `libc.so.6: version 'GLIBC_2.38' not found`. The Linux builds now run on
  Ubuntu 22.04, which targets glibc 2.35, and `scripts/check_glibc.py` unpacks
  the finished archive and fails the release if the floor ever creeps up
  again. Nothing about the binary advertises this from the outside: the
  executable itself reports `GLIBC_2.14` and says nothing about what is packed
  inside it.
- **`shambles --version` crashed on Windows.** The Windows binary was built
  with PyInstaller's `--windowed`, which allocates no console, so Python set
  `sys.stdout` and `sys.stderr` to `None`. `print` tolerates that; a bare
  `sys.stderr.write` does not, and the update-notice line raised
  `AttributeError: 'NoneType' object has no attribute 'write'`. Windows showed
  a crash dialog at the end of every install. Writes on that path now skip a
  missing handle.

### Changed

- **Windows ships two binaries.** `shambles.exe` is console-subsystem, so
  `--version`, `--help` and `list --json` print. `shamblesw.exe` is the
  windowed twin, for a desktop shortcut that should not flash a terminal.
  2.1.0 shipped only the windowed build, under the console name. The
  PowerShell installer fetches both; a release without the second asset still
  installs.
- **The release smoke tests read the output.** They checked exit status
  before, which is precisely why a binary that printed nothing passed. They
  now assert that `--version` prints a version and `--help` prints usage, on
  every platform.

## 2.1.0 - 2026-09-09

### Added

- **A terminal interface.** Running `shambles` on an interactive terminal now
  opens a keyboard-driven dashboard (`j`/`k` or the arrow keys to move,
  `Enter` to switch, `a` to add, `m` for the account menu, `l` to log in,
  `x` to eject, `?` for help) instead of requiring the Tk window. `shambles
  tui` opens it explicitly; `shambles gui` still opens the window; `shambles
  list` and `shambles switch` are unchanged and remain the scriptable,
  non-interactive path. See the README's "Terminal interface" section for the
  full shortcut list.
- **Same-terminal launch after switching.** From the terminal interface's
  result screen, choosing Launch hands the current terminal to the vendor CLI
  (`claude` or `codex`) in place — Textual exits and tears down first, then
  the vendor process replaces Shambles rather than running alongside it.
- **`--no-motion` and `NO_COLOR`.** `NO_COLOR` is detected automatically, the
  same convention respected by most other terminal tools, and makes the whole
  terminal interface monochrome. `--no-motion` remains accepted (before or
  after the subcommand) so existing flags do not break.
- **`SHAMBLES_NO_MOTION=1`** does the same as `--no-motion`, for scripts and
  session managers that set environment variables more easily than flags.
- **The sign-in link is now offered by the terminal interface.** Both vendors
  print a URL to open when they cannot launch a browser themselves — the
  normal case under WSL and over SSH — and the terminal login screen now
  gives that address a panel of its own with `o` to open it and `c` to copy
  it. Copying uses OSC 52, so the link reaches the clipboard of the machine
  you are sitting at even across SSH, and it is copied whenever you press `o`
  as well: the WSL browser openers report success while doing nothing, so the
  clipboard is what makes "did it open?" a question nobody has to answer. The
  Tk window has had these buttons since 1.x; this brings the frontend that is
  now the default up to the same standard.

### Changed

- **A first run says what to press.** The empty terminal welcome now reads
  "No saved accounts yet. Press a to add your first account." rather than
  only naming the state, and `shambles list` with nothing configured ends
  with a line pointing at `shambles` and `shambles --help`. The hint appears
  only when no provider has any account, and `shambles list --json` is
  unchanged — it is the contract the macOS panel parses.
- **Quieter login progress.** The terminal login screen no longer repeats
  `[vendor output hidden]` for every suppressed line; it shows one steady
  "Waiting for the vendor CLI..." instead. Three of those placeholders in a
  row is the normal shape of a working login, and echoing the text back read
  as concealment rather than progress. What is suppressed has not changed.
- **TUI visual refresh.** The terminal dashboard now uses the README lockup
  as its wide header, a grouped account list with a terracotta selection
  spine, a hero inspector (USAGE / SWITCHES), and a footer that exposes Add
  (`a`) and Eject (`x`) as first-class keys.

### Known limitations

- Bare `shambles` only opens the terminal interface when both stdin and
  stdout are attached to a real terminal. Anything else (a pipe, a script, a
  non-interactive shell) falls through to the usage message the same as
  before — this release adds no new implicit behaviour for non-interactive
  callers.
- The terminal interface goes through the same `ShamblesService` core as
  `shambles list`/`shambles switch`, and reads and writes exactly the same
  files the Tk window does — see "What it touches" in the README. The
  restart requirement is unchanged too: a Claude Code session already running
  keeps the login it loaded at startup, in a terminal or in VS Code, no
  matter which interface performed the switch.

## 2.0.0 — 2026-08-07

A redesign. Everything below happens automatically on first launch; there is
nothing to run and nothing to move.

### Breaking

- **`~/.claude` is no longer a symlink.** It is an ordinary directory that
  Shambles never moves, replaces or deletes. A switch now copies one file —
  `~/.claude/.credentials.json` — and splices `oauthAccount` in
  `~/.claude.json`.
- **Session history is shared across accounts again.** 1.0.0 swapped the whole
  of `~/.claude`, so `projects/` went with it and every account had its own
  history. Transcripts were never deleted, but they became unreachable while
  another account was active, which reads as data loss. Claude Code keys history
  by project path, not by account, and now Shambles leaves it alone.
- **Profiles are ~500 bytes instead of 208 MB.** They hold a credentials file
  and an identity, nothing else.
- **First launch migrates the old layout**, merging every profile's `projects/`,
  `plugins/`, `file-history/`, `todos/`, `shell-snapshots/`, `session-env/`,
  `plans/` and `history.jsonl` into one shared directory. Nothing is
  overwritten and nothing is deleted; the old profile folders stay on disk for
  you to remove. Run it with no Claude Code sessions open.
- An older Shambles cannot read the new layout. Downgrading after upgrading is
  not supported.

### Added

- **Session and weekly usage** on every card, as bars. Red at 80%, matching the
  VS Code extension's own meter. The active account shows live figures; others
  show their last known values with an age attached, never anything newer.
- **Eject** — hands `~/.claude` back as a stock Claude Code install, still
  signed in, and removes only Shambles' own bookkeeping. Exists because the
  obvious way to uninstall — deleting `~/.claude-profiles/` — destroys every
  stored refresh token.
- **Remove profile** — a per-card control for inactive accounts only, with a
  confirmation naming the account and what it costs.
- **Refresh** — re-reads the figures on disk. Local files only; no network call
  and nothing a running Claude Code session can notice.
- **A warning when `CLAUDE_CONFIG_DIR` is set**, which silently points the CLI
  at a config tree Shambles never touches.
- `SECURITY.md`, and `SHAMBLES_SCALE` for overriding UI scaling.

### Fixed

- **A failed switch could destroy the account it switched away from.** If the
  identity splice failed after the login was installed, the active marker still
  named the outgoing profile, and the next refresh copied the incoming login
  over that profile's stored token.
- **Writing onto an unreadable `~/.claude.json` replaced the whole file.** A
  parse failure yielded `{}`, which was then spliced and written back, losing
  every project, MCP server and machine ID. The write path now refuses.
- **A stale usage cache was restored on every switch**, so the VS Code meter
  displayed hours-old figures as current.
- **The active account was the only one guaranteed to show no usage** — a
  profile learned its figures only when switched away from.
- **Refresh tokens rotate**, so a profile's stored login went stale within hours
  of becoming active. It is now re-synced while the account is in use.
- **A locked file escaped as a bare `OSError`**, which the window could not
  render, so a switch appeared to do nothing. Credential writes and the config
  backup are retried.
- **The profile store was created world-traversable** under the usual umask.
  Now `0700`, with credentials `0600`.
- Migration skipped `plugins/` and `history.jsonl`.
- Tooltips could stack on screen, fired from anywhere on a usage row, and ran
  off the display near the right edge.
- Icon glyphs missing from the system font rendered as boxes; they are now
  chosen at runtime from what the font can draw.
- Window layout: the footer claimed a column beside the cards, the card list
  had no scrollbar and grew past the screen, and long profile names stretched
  the window instead of eliding.
- Body text was below the 16px accessibility floor.

### Known limitations

- **Windows account switching is unverified.** Claude Code appears to use the
  Credential Manager there rather than a credentials file, in which case
  switching would quietly do nothing. The binary builds and runs; nobody has
  confirmed a switch takes effect. See `docs/token-storage.md`.
- **macOS is unsupported** — credentials live in the Keychain, so there is no
  file to swap.
- A session already running keeps the token it loaded at startup. Start a new
  one, or reload the VS Code window.

## 1.0.0 — 2026-08-05

First tagged release. Swapped `~/.claude` as a symlink between profile
directories — superseded by 2.0.0, which shares session history instead of
partitioning it.
