# Contributing

Thanks for looking. Shambles moves credential files around on one machine, so
the bar for changes is "obviously safe" rather than "clever".

## Reporting a bug

Open an issue and answer the template's first question honestly — which OS,
and whether you are inside WSL. It decides most of the answer:

| Platform | Claude Code | Codex | How we know |
|---|---|---|---|
| Linux x64, arm64 | Works | Works in CI | Daily use (Claude); `real-machine` workflow |
| WSL | Works, with the **Linux** build **inside** WSL | Works in CI, as Linux | Daily use (Claude) |
| macOS 15, 26; Apple Silicon and Intel | Works in CI | Works in CI | `real-machine` workflow |
| Windows (native) x64 and Arm | Works in CI | Works in CI | `real-machine` workflow |

Three levels of confidence are kept apart on purpose, here and in
[docs/token-storage.md](docs/token-storage.md):

- **Verified on a runner.** The `real-machine` workflow installs the current
  Claude Code and Codex on GitHub's macOS, Windows and Linux machines and
  drives Shambles against the real Keychain and Credential Manager with
  made-up credentials. After each switch the vendor's own command
  (`claude auth status`, `codex login status`) is asked who is signed in.
  "Works in CI" in the table means this and nothing more.
- **Verified from vendor source or documentation.** Read out of the shipping
  Claude Code binaries, the open Codex source, or the official docs, with
  versions and dates recorded.
- **Inferred.** Follows from reading code, ours or theirs, and has not been
  run.

What no runner can check: a sign-in with a real account. Nobody has reported
one through Shambles on macOS or native Windows, or with Codex anywhere. A
report of either, working or not, is the most useful thing a bug report can
contain right now.

Run `shambles doctor` and paste its output. It prints where each login is
kept and anything that would stop a switch taking effect, and no
credentials.

**Never paste a credential.** Not `.credentials.json`, not `auth.json`, not a
token, not the contents of `~/.shambles/`. Nothing in a bug report needs them.

Found a security problem? Do not open an issue — see [SECURITY.md](SECURITY.md).

## Working on the code

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest
```

The GUI tests need a display. On a headless Linux box, `xvfb-run -a
python -m pytest` runs them; without it they skip themselves.

## What a change needs

- **A test, written first.** Every behaviour here is pinned by one.
- **Green CI on Linux, macOS and Windows.** Windows retries flaky
  terminal-UI tests up to five times; Linux and macOS do not retry at all.
- **A green `real-machine` run for anything that touches where a login is
  kept**: `shambles/stores/`, the `store` blocks in
  `shambles/providers/*.json`, or the install scripts. Those tests skip on
  your own machine by design, because they write to the real Keychain and
  Credential Manager. They run on the pull request.
- **No new network calls.** `tests/test_login.py` scans every module for
  networking imports and fails the build on a new one. The single exemption
  is the opt-in update check, and widening it is a visible edit to a list.
- **No credentials in logs or output.** Vendor output is filtered to a
  known-safe sign-in URL and nothing else.

## Things worth knowing

- Where a vendor keeps its login is a fact that drifts. Two readings of
  Claude Code's binary three months apart gave different answers for
  Windows. When a `store` block in a provider spec changes, update the
  `provenance` block beside it and the evidence in `docs/token-storage.md`
  in the same change, and say which of the three levels above it rests on.
- `--home` must never reach the real Keychain or Credential Manager. The
  provider compares the home it is given with the real one and uses only
  files for anything else. A test that needs the layered store has to
  declare its temporary directory to be the real home.

- The terminal UI talks only to `ShamblesService`. Nothing under
  `shambles/app/tui/` may import `switcher`, `login` or `eject` directly, and
  a test enforces it.
- `shambles list --json` is a contract other programs read. Adding prose to
  it breaks them.
- Switch ordering is deliberate: it is what stops a failed switch destroying
  the account it switched away from. Read `TECH_SPEC.md` before changing it.
