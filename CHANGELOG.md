# Changelog

Notable changes per release. Dates are the tag date.

## Unreleased

### Added

- **A switch says what it did not reach.** After a switch Shambles looks
  for the usual reasons "I switched but nothing changed", and says what to
  do. A Codex process that was already running, including the background
  service VS Code starts (`codex app-server`), stays on the account it
  started with until it is restarted; Codex's own code only re-reads its
  login after a sign-in it made itself. `ANTHROPIC_API_KEY`,
  `ANTHROPIC_AUTH_TOKEN` or `CLAUDE_CODE_OAUTH_TOKEN` in the environment
  outranks any saved Claude login. A shell start-up file (`~/.zshrc`,
  `~/.bashrc` and the like) that sets one of those, or moves
  `CLAUDE_CONFIG_DIR` or `CODEX_HOME`, gives every terminal its own login.
  Nothing is stopped or changed for you; `shambles doctor` reports the same
  things. Running processes are listed on Linux, WSL and macOS, not yet on
  native Windows.
- **Paste the code from Claude's sign-in page.** Opened on another device
  or browser profile, or from Copy link, Claude's sign-in page ends by
  showing a code instead of signing you in. There was nowhere to put it,
  so those sign-ins could never finish. The sign-in sheet now has a field
  for it. The code goes straight to Claude Code; the window does not keep
  or show it. Paste the page's address or a verification code by mistake
  and the sheet says which it was, as Claude Code 2.1.330 would. This works
  on Windows too.
- **Codex: sign in on another device.** The Codex sign-in sheet offers
  This browser or Another device. Another device shows a one-time code and
  its link, with Copy code, Copy link and how long the code lasts, to enter
  from a phone or any other browser. The ChatGPT account has to allow
  sign-in with a code (device code login, in its security settings or its
  workspace's permissions). If it does not, the sheet says so and where to
  turn it on, and its button signs in with this browser instead.

### Changed

- **Renewing a parked account keeps you where you were.** Signing in an
  account you are not using, before its login runs out, has to make it live
  while Claude Code writes the new login. Shambles then left you on it. Now,
  once the new login is saved, it switches you back to the account you were
  on and says so: "Admin renewed until 18 Dec. You're still on Personal."
  Signing in an account whose login has lapsed, to use it, still leaves you
  on it.
- **A shorter sign-in sheet.** Four sentence-long steps are now one line,
  Saved, Ready, Your browser, Save, each explained on hover. The advice
  about which browser profile to use sits behind the ⓘ beside the link.
- **A limit that has reset says so.** A saved reading carries its reset
  time. Once that time has passed the window shows the limit as reset
  instead of an old 100%, with the old figure on hover. Reset times under
  a day read as a countdown ("Resets in 1h 52m"), with the exact date on
  hover. An hour-old reading is marked by the bar's look and its tooltip
  instead of an "as of 7h ago" line. The window redraws every 30 seconds
  so a countdown stays true while it sits open; that redraw reads nothing.
- **The window keeps itself current.** It re-reads Claude Code's and
  Codex's files when you come back to it, when those files change (a stat
  every 2 seconds), and every minute, and the header says "Updated just
  now". Refresh stays as the manual way to read everything. These
  automatic reads never touch the macOS Keychain or Windows Credential
  Manager, which would raise password prompts: a login kept there is
  answered from the last Refresh, switch or sign-in.
- **No more "running sessions keep their login".** The window, the
  terminal UI, the classic window and the README said a session already
  running keeps the login it started with, and to start a new one after a
  switch or sign-in. Claude Code 2.1.300 re-reads a changed login at its
  next request, so for current Claude Code that was wrong. Shambles now
  says nothing either way until the behaviour is confirmed for older
  versions and for Codex.
  The terminal UI's switch result and help screen still said it in other
  words ("Existing sessions keep their loaded login"); they no longer do,
  and the switch result lists what the switch did not reach instead.
- **Claude accounts show their plan, not an internal code.** Rows read
  "Default ai" and "Default raven", which are Claude's rate-limit tiers.
  They now read Pro, Max 5x, Max 20x, Team, Team Premium or Enterprise,
  named the way Claude Code names them, from the organisation type and the
  Team seat it stores. The window, the terminal UI and `shambles list` all
  show the new names. A plan Shambles does not recognise still shows what
  it showed before.

- **Move the window by its own header, and resize it from the corner.**
  Under WSL on a 4K screen the title bar Windows draws is tiny. Drag
  anywhere in the window's header that is not a button to move it,
  double-click it to maximise, and drag the grip in the bottom-right
  corner to resize. The window opens where it was left last time, at the
  same size; if that place is on a monitor that is no longer there, it
  opens in the centre. The smallest size goes from 520x420 to 420x360,
  and at narrow widths rows leave out the address line.
- **Messages no longer cover the list.** What an action did, and the line
  shown while a switch waits, now slide in under the header and push the
  list down instead of sitting over its last row. An error stays until you
  close it with its ×. The wait for Claude Code is one line, "Waiting for
  Claude Code to finish renewing", with the reason behind its ⓘ.
- **Calmer rows: one line, one button, one badge.** Each account reads
  across the same way: name and plan, its address once, its usage, one
  badge, one button, and the ⋯ menu, always last. The ▾ button is gone;
  click a row, or choose Details in its menu, to open it. Badges replace
  the second button and the sentences: a clock and the days left for a
  login due a sign-in (click it to sign in), "Signed out", and "Most
  room". Dates, ages, reasons and what a switch reaches moved into
  tooltips and ⓘ icons; a reason every row shares is said once above them.
- **Small usage bars on every account.** Parked accounts show their
  5-hour and weekly use as two thin bars, with the details on hover. Once
  the account in use passes 80% of either limit, the parked account with
  the most room left is marked "Most room". It is a hint; Shambles never
  switches by itself.
- **A sign-in deadline is one line.** In its last three days a deadline
  reads "Admin stops working Sat 21 Nov" with Sign in beside it and the
  explanation behind ⓘ. Its × hides it until tomorrow.
- **A tool that is not installed takes one line.** "Codex · Not installed"
  in the section heading, with the details behind ⓘ, instead of a card.
- **Switching by number needs Ctrl** (⌘ on macOS). Ctrl+1 to Ctrl+9 press
  the Nth account's button, numbered by its place, so the numbers no
  longer move when a switch or a lapsed login changes the rows. A bare
  digit used to switch accounts at a stray key press. Hold Ctrl to see
  every account's number; the Switch tooltip says it too.
- **Shorter sheets.** The eject sheet says, a line each, which account
  every tool stays signed in as, and puts the folder that keeps the other
  logins on a line of its own, with why behind ⓘ: about 35 words where it
  was 90. The notice after a storage move does the same. A failed sign-in
  no longer repeats its title in its text, or says "Sign in to try again"
  right above the Try again button. It names the tool ("Claude Code did
  not save a usable login") where it said "the vendor", and writes account
  names without quotes, as the rest of the window does.
- **Every icon button says what it does** on hover and on keyboard focus,
  using the name a screen reader already reads. One word for each thing:
  "In use" for the account a tool is on (was "Live"), "signed out" for a
  login that has ended (was "needs sign-in" and "Expired"), and "sign in
  by" for a deadline. One look per action and one warning design; buttons
  are 36 px in the header and on sheets, 32 px on rows. The Refresh
  tooltip no longer claims it reads local files only, which is not true
  on macOS, where it reads the Keychain.
- **Easier to see where the keyboard is.** The focus ring is violet with a
  gap inside it, apart from the blue of buttons, the live card and
  selections. Card, button and field outlines are darker, at least 3:1
  against what they sit on. An old reading on an account not in use is
  drawn as a striped bar instead of a pale grey that barely showed.

### Fixed

- **Narrow windows kept what matters in view.** At 420 px the deadline
  line cut off its date ("Administrator account stops …"); it now cuts the
  name instead and keeps "stops Fri 27 Nov". The add-account sheet opened
  scrolled past its own title to reach its name field; a sheet now opens
  at its top and follows focus only where Tab takes it. An ⓘ after a
  sentence that wraps sits after its last line, not beside its first, on
  every sheet, the sign-in sheet's included.
- **The unsaved-login card reads as a card.** It said "Signed in as
  newhire@example.test, which is not saved yet. 'work' is
  work@example.test." as its title. It now says "Signed in as
  newhire@example.test", then "Not saved yet", with why saving matters
  behind ⓘ. Notices and the settle card write account names without
  quotes, as the rest of the window does.
- **The sign-in link shows with Claude Code 2.1.330.** That version prints
  a shortened sign-in link (`claude.ai/oauth/authorize?` followed by one
  code) on a line of its own, and Shambles did not recognise it as a
  sign-in link, so the sheet showed no link to open or copy.
- **Premium Team seats on Labs and nonprofit plans read Team Premium.**
  They read plain Team. Claude Code 2.1.330 names which seats are premium,
  and Shambles now follows it.
- **A sheet with room to spare could still scroll.** A sheet whose text
  was still being laid out when it opened could decide it scrolled, and
  the rule it then drew above its buttons took away exactly the room that
  would have shown the rest, so it kept a scroll bar it did not need.
- **Parked Codex accounts keep their last usage.** Claude accounts showed
  their last figures after you switched away; Codex accounts said "No
  usage recorded yet" forever. Codex keeps no usage file per account, only
  session logs that every account shares, so at each switch Shambles now
  keeps the newest reading taken while the outgoing account was in use.
  The account in use no longer shows the previous account's figures as
  its own either: until it has run a session it shows its own last
  reading, or nothing.
- **A row due a sign-in lost its menu.** With Sign in beside Switch, the
  row's ▾ was pushed off the card and its ⋯ menu, which holds Rename and
  Remove, went out of reach, from 640 px wide down or with a name longer
  than about 15 characters. The row now has one button, and the sign-in
  rides on its badge.
- **Cards no longer close their menu when the window updates.** The window
  made every card again each time it worked the view out, which now
  happens on its own every half minute. An open menu closed and keyboard
  focus went. Cards are now kept by account and only change in place.
- **The sign-in link shows again when the browser does not open.** Shambles
  offers a link from the vendor's output only when it is a real sign-in
  request, so the window never offers an arbitrary address. Its list was
  out of date. Every link current Claude Code prints was thrown away: they
  come from `claude.com` or `platform.claude.com`, carry `code=true` and
  return to `platform.claude.com/oauth/code/callback`. Codex links for a
  fixed workspace were thrown away too. Claude Code also wraps its link in
  a terminal hyperlink when it runs inside Windows Terminal, VS Code or
  JetBrains, even when its output goes to Shambles rather than a terminal,
  and that link was lost as well. The sign-in sheet now shows Open sign-in
  page and Copy link for both vendors.
- **Cancelling a sign-in on Windows stops Claude Code or Codex.** An npm
  install starts them through a `.cmd` file, so what Shambles ran was
  `cmd.exe` and the vendor was its child. Cancel ended `cmd.exe` only: the
  vendor kept running, holding its sign-in port, and the window waited on
  "Cancelling" until it gave up by itself. Cancel now ends the vendor too,
  with Windows' own `taskkill`. Nothing else is touched.
- **After a sign-in outside Shambles, the account marked in use no longer
  shows the other account's usage.** Its row showed the usage, plan and
  sign-in date of whoever was really signed in. Those figures now go to
  the account the login is proven to be, by the same rule Shambles uses
  before saving a login, and to no account when nothing proves whose it is.
  A usage figure that names a different account is no longer shown for the
  account in use either.
- **A login that is already saved is no longer offered for saving again as
  "Work 2".** When the account marked in use had been removed, or no
  account was marked, Shambles offered to save the current login under a
  new name even when it was already saved. When the login is provably the
  saved account's own, it now offers "Use Work" instead. A login that only
  shares the account's address is still offered for saving, since it may
  belong to another organisation.

- **Small windows kept buttons out of reach.** At the smallest size the
  sign-in sheet hid Cancel and the eject sheet hid both its buttons, with
  nothing to say there was more. A sheet's buttons now stay at its bottom
  and its text scrolls above them, with a scroll bar on show. Opening an
  account near the bottom of the list scrolls its details into view.
## 2.2.2 - 2026-11-15

### Fixed

- **pipx installs now get the new window.** The README, the release notes
  and the install script's advice all said
  `pipx install git+https://github.com/ianchendev/Shambles`, which leaves out
  PySide6, so `shambles gui` quietly opened the classic window for everyone
  who installed that way. They now say
  `pipx install 'shambles[gui] @ git+https://github.com/ianchendev/Shambles'`,
  and name the system libraries Qt needs on a bare Linux or WSL install.
- **`shambles gui` no longer dumps core where Qt cannot start.** With
  PySide6 installed but a system library missing, Qt aborts the whole
  process the moment it looks for a display ("no Qt platform plugin could
  be initialized ... Aborted (core dumped)"), and no Python code can catch
  that. Shambles now asks a short-lived child process first, about a tenth
  of a second on Linux. If Qt cannot start, `shambles gui` opens the
  classic window and says why, naming the missing libraries, and
  `shambles gui --new` prints the fix and exits.
- **Three system libraries were not enough.** Qt's X11 plugin and the Qt
  modules the window uses link against libraries from 26 Debian/Ubuntu
  packages. On a WSL Ubuntu with the three that were listed,
  `libxcb-icccm4` and `libxcb-keysyms1` were still missing. The full list
  is in the README, the release notes and `shambles gui --new`. CI installs exactly that list in bare Ubuntu 22.04
  and 24.04 containers and opens the window.
- **The advice for installing Qt names a command that works.** It said
  `pip install 'shambles[gui]'`, but Shambles is not on PyPI, so that
  command finds nothing, or a stranger's package if anyone claims the name.
  In a pipx install it now says
  `pipx install --force 'shambles[gui] @ git+https://github.com/ianchendev/Shambles'`,
  and anywhere else it gives this Python's own
  `-m pip install 'PySide6-Essentials>=6.8,<6.10'`.

## 2.2.1 - 2026-11-15

### Fixed

- **The classic window no longer switches accounts by itself.** A card fades
  in a moment after the list is drawn. When the list was redrawn within that
  moment, the fade's timer outlived its card, and tkinter could give a
  button on the new card the same internal name as that timer. The timer
  then pressed the button: Switch, Remove or Sign in, on an account nobody
  clicked. Every delayed action in the window is now cancelled with the
  widget it belongs to. Only `shambles gui --classic` was affected; the
  default window is a different program.
- **The classic window's sign-in dialog no longer touches the window from
  the thread that reads the vendor's output.** That thread now only hands
  each line over, and the window collects it on its own thread. Tk is not
  safe to call from another thread, and doing so could freeze the dialog.
- **Card animations in the classic window on Python 3.10 and 3.11.** When
  one animation on a card finished, it removed the other animations' watch
  for the card being closed, so their timers could outlive it (and so press
  a button, as above). This affected installs that run on those Python
  versions, such as pipx; the downloaded programs use a newer Python.

### Changed

- **Tests are no longer retried on Windows.** The retries hid the first bug
  above. Each test now waits for what it checks, and any test job stops
  after 30 minutes instead of six hours.

## 2.2.0 - 2026-11-14

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

- **Sign in again before a Claude login runs out, from any interface.**
  Claude ends a login about 30 days after it was signed in, however much it
  is used, and only a new sign-in moves that date. In its last days an
  account now says so: `shambles list` marks it `expires soon` and names the
  date, the terminal UI shows a notice at the top with the key that renews
  it, and the window offers **Sign in** beside Switch. A sign-in that is
  cancelled or does not finish leaves the account exactly as it was. Codex
  accounts are marked `expires soon` too, but using one renews it, so they
  get no notice.
- **A switch that has to wait says why.** While Claude Code is renewing a
  login, a switch waits for it to finish (up to 15 seconds) so the new token
  is the one saved. The terminal UI and `shambles switch` now say that it is
  waiting and on what, instead of sitting silent until the result.
- **One key for what the notice says.** In the terminal UI, `f` does what
  the notice at the top says: sign that account in again, or switch to the
  saved account a login belongs to when the label names another. Both took
  finding the account in the list first.

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

- **`shambles gui` opens the new window.** It is the default wherever it is
  installed: from the release installers, or with the `gui` extra from pip.
  Where it is not, `shambles gui` opens the classic Tk window and says so in
  one line. `shambles gui --classic` asks for the Tk window outright, and
  `shambles gui --new` asks for the new one and explains what is missing
  instead of falling back. The Tk window will be removed in a later release.

- **A new window: `shambles gui --new`.** Rebuilt in Qt on the
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

- **The window has an icon and a place in your applications menu.** The
  title bar and taskbar show a Shambles icon instead of a blank one.
  `install.sh` adds a launcher entry on Linux
  (`~/.local/share/applications/shambles.desktop`) and `install.ps1` adds a
  Start menu shortcut on Windows, both pointing at the installed window.
  On macOS, where the window is not yet an app Launchpad can list, it says
  to open it with `shambles gui` instead. Set `SHAMBLES_NO_DESKTOP=1` to
  skip either.

- **The installers fetch the new window as its own download.** It carries
  Qt (a 36 to 82 MB download, depending on the platform), so it ships beside
  the `shambles` binary instead of inside it: every other command stays as
  fast as it was. `install.sh` unpacks it to `~/.local/share/shambles/window`
  and `install.ps1` to `%LOCALAPPDATA%\Shambles\window`, and
  `shambles gui` opens it from there. There is a build for every
  platform the binary ships for, Windows on Arm included.

  It is checked against the release's `SHA256SUMS` like the binary, and
  swapped in only once it has arrived whole. A download that fails or does
  not match leaves the window you had, and never undoes the binary, which is
  installed first. Set `SHAMBLES_NO_WINDOW=1` to skip it. From pip or pipx it
  is an optional extra instead: `pip install 'shambles[gui]'`.

  The archive has a `licenses` folder: Qt and PySide6 are LGPL-3.0, so it
  carries that text, the GPL-3.0 it incorporates, and a notice saying where
  Qt's source is. Qt stays as separate, unmodified shared libraries that you
  can replace.

  The Linux window needs glibc 2.35, the same as the binary. It brings its
  own copy of the few system libraries Qt needs, so it starts on a bare
  Linux or WSL install with nothing to `apt install`.

- **`shambles list --json` says more about each account.** Every group now
  carries `can_sign_in` and `cli` (whether the vendor's command is there to
  run, and its name). Every account carries `expires_at_ms` and
  `status_label`, and every usage window carries `severity` and a filled-in
  `resets_at_ms`. All additions; nothing existing changed, and the contract
  version stays at 1.

- **`shambles doctor`.** Checks whether switching can work on this machine
  and says why not, without changing anything. It reports an environment
  variable that makes the vendor ignore its stored login (`ANTHROPIC_API_KEY`
  and friends, `CODEX_ACCESS_TOKEN`), a `claude` inside WSL that is really
  the Windows install, Codex not keeping its login in `auth.json`, a
  relocated config directory, a missing vendor program, and where each login
  is kept. On Windows it also lists the Credential Manager entries that
  Shambles 2.1.2 or older left behind, without touching them. Exits 1 on a
  problem; `--json` for scripts.

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

- **The terminal UI no longer loses the account list after a resize.**
  Making the window narrower could leave the header as tall as the wide
  banner it had just replaced, around the one-line header, with the account
  list pushed off the screen until the window was resized again. The header now takes
  its size from the window it is drawn in. In ASCII mode the details pane no
  longer draws a block-glyph scrollbar when it overflows.

- The record of which account is active, the copies of `~/.claude.json` kept
  before each switch, and the session history merged by the old-layout
  conversion are now written the way logins are: whole, owner-only from the
  first byte, and never seen half written. Two windows writing the active
  record at once could leave it empty, which reads as no account marked.
- An early Claude sign-in that comes to nothing no longer reports a renewal
  when Claude Code has refreshed the login in the meantime. The live copy had
  moved on from the saved one, so it looked new, although its deadline had
  not moved.
- **The new window no longer says using a Claude account renews its login.**
  Claude's login lasts a fixed time from sign-in, about thirty days, and no
  amount of use moves it. An opened row now says "Using the account does
  not move this date. Sign in again before then to keep it." for Claude, and
  keeps "Using the account renews it." for Codex, where it is true. The
  snapshot carries `renewed_by_use` per account so no frontend has to know
  which provider is which.
- **Switching no longer freezes the new window.** A switch can wait up to
  15 seconds for Claude Code to finish renewing its login. The new window
  now says so at the bottom while it waits, instead of drawing nothing and
  ignoring clicks, and holds every other action until the switch is done.
  Closing it mid-switch closes it once the switch has finished, never in
  the middle of one.
- **The new window offers a sign-in before a Claude login's fixed date.**
  An account near its deadline shows Sign in beside Switch, the account in
  use shows Sign in, and the notice that says the date is coming has a
  "Sign in to X" button.
- **Signed in as a saved account that is not the one marked, the new window
  offers to switch to it, not to save it again.** It shows a card naming the
  account, with one button, "Switch to Home", that files the live login
  there and keeps the one it replaces. Every other Switch waits until then,
  with the reason, because Shambles would refuse it anyway. Saving would
  only have made a second account for the same login. This matches the
  classic window.
- **Two Shambles windows saving the same login at once could corrupt it.**
  Every write shared one temp file name, so when the window and the terminal
  UI re-saved a login at the same moment, one could fail or install a file
  that mixed both writes. Measured with two processes writing one file: 449
  of 1200 writes failed and 1618 of 18,259 reads saw a file that was neither
  write. Each write now has a temp file of its own, private from its first
  byte, written in full and flushed to disk before it is renamed into place;
  the same measurement shows no failures and no bad reads. A temp file left
  by a failed or interrupted write is removed, and one left by a killed
  process is removed by the next write once it is five minutes old. The
  migration from the old `~/.claude-profiles` store now copies each saved
  login the same way: a copy cut short by a full disk was left at its final
  name, and every later run skipped it as already there.

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
- **A switch no longer loses a Claude login that was being renewed at that
  moment.** Claude Code replaces its login token every time it renews it,
  and the old token stops working the instant it is sent. A switch that
  landed while a renewal was on its way back saved the old token, and Claude
  Code then threw the new one away because the file had changed under it:
  the account needed signing in again. Shambles now waits for a renewal in
  progress to finish, using Claude Code's own lock, before it switches. A
  switch held up for most of a minute (a Keychain prompt left open, say)
  stops before it replaces the login and asks you to try again, since Claude
  Code may have started a renewal of its own by then.
- **The terminal interface and `shambles list` / `shambles switch` now bring
  an old setup up to date themselves**, as the windows always did. Upgrading
  from 1.0 and using only the terminal used to show no accounts at all, and on
  the layout from before 1.0 every Claude switch was refused with "run the
  migration", which no command could do. What was moved is said once, in the
  terminal interface's status line or on stderr.
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

- **Switching Claude accounts on native Windows did nothing.** Shambles read
  and wrote the Credential Manager there, always, in a layout Claude Code
  does not use. Claude Code keeps its login in
  `%USERPROFILE%\.claude\.credentials.json` unless Credential Manager has
  been switched on for the account. So the live login read as absent, and a
  switch put the incoming credential where nothing looked, wrote the
  incoming account's name into `.claude.json` and reported success: the old
  login under the new name. Shambles now uses the file, and Credential
  Manager only when Claude Code itself does, in Claude Code's own layout.

  Those versions also left entries in Windows Credential Manager, named like
  `Claude Code-credentials/claude-code-user#0` and `...#m`. Claude Code does
  not read them, but they can hold a copy of an old login. `shambles doctor`
  lists them and says how to remove them. Shambles does not delete them.

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
