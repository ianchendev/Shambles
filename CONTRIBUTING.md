# Contributing

Thanks for looking. Shambles moves credential files around on one machine, so
the bar for changes is "obviously safe" rather than "clever".

## Reporting a bug

Open an issue and answer the template's first question honestly — which OS,
and whether you are inside WSL. It decides most of the answer:

| Platform | Account switching |
|---|---|
| Linux | Supported |
| WSL | Supported — run the **Linux** build **inside** WSL |
| Windows (native) | Unverified, probably not working |
| macOS | Not supported — credentials live in the Keychain |

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
- **Green CI on Linux and Windows.** Windows retries flaky terminal-UI tests
  up to five times; Linux does not retry at all.
- **No new network calls.** `tests/test_login.py` scans every module for
  networking imports and fails the build on a new one. The single exemption
  is the opt-in update check, and widening it is a visible edit to a list.
- **No credentials in logs or output.** Vendor output is filtered to a
  known-safe sign-in URL and nothing else.

## Things worth knowing

- The terminal UI talks only to `ShamblesService`. Nothing under
  `shambles/app/tui/` may import `switcher`, `login` or `eject` directly, and
  a test enforces it.
- `shambles list --json` is a contract other programs read. Adding prose to
  it breaks them.
- Switch ordering is deliberate: it is what stops a failed switch destroying
  the account it switched away from. Read `TECH_SPEC.md` before changing it.
