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

**First run** — `~/.claude` is still a real directory. Click
**Save Current Account**, name it (e.g. `Work`). Shambles moves the directory
into `~/.claude-profiles/Work` and leaves a symlink behind. Nothing is deleted.

**Adding a second account** — click **Add Empty Account**, name it, and leave
*Copy settings from …* checked so your plugins, permissions and model prefs
carry over. Then run `claude` in a terminal and `/login`. That is the one time
you wait for the email.

**Switching** — click **Switch**. Then start a **new** Claude Code session in
VS Code. If the extension does not pick it up, run *Developer: Reload Window*.
An already-running session keeps the token it loaded at startup.

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

## Safety

- Every write to `~/.claude.json` is preceded by a backup and performed
  atomically (temp file + rename), preserving all other keys and their order.
- The symlink swap is a rename over the top, so `~/.claude` never briefly
  ceases to exist.
- `Save Current Account` rolls the directory move back if the symlink cannot
  be created.
- Shambles refuses to touch a `~/.claude` symlink pointing outside
  `~/.claude-profiles/`.
- There is no delete-profile button. Remove folders by hand if you mean it.

## Tests

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

104 tests, plus 3 GUI smoke tests that require `python3-tk`. Every test runs
against a synthetic home in `tmp_path`. None reads or writes your real
`~/.claude`.

The load-bearing test is
`tests/test_switch.py::test_credentials_survive_a_round_trip_unmodified` — it
asserts that `Work → Personal → Work` leaves `.credentials.json` byte-identical,
`refreshToken` and `refreshTokenExpiresAt` included. If that regresses, the tool
stops solving the problem it exists for.

## Platform notes

Developed and verified on WSL2 Ubuntu with WSLg. The Windows code paths
(`target_is_directory=True`, the WinError 1314 Developer Mode message) are
written to spec but **have not been exercised** — there was no Windows-side
Claude Code install to test against.

Do not point a Windows `%USERPROFILE%\.claude` at a WSL path or vice versa.
Cross-boundary symlinks break Claude Code's file operations and produce 9p
permission problems on a `600` credentials file. Run Shambles inside whichever
environment you use Claude Code in.
