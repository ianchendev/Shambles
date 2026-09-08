# Security Policy

## Reporting a vulnerability

Please report security issues through GitHub's **private vulnerability
reporting**: open the [Security tab](../../security/advisories) and choose
*Report a vulnerability*. That opens a private thread visible only to the
maintainers.

**Do not open a public issue for a security problem.** Shambles handles OAuth
credentials, so a public report exposes users before a fix exists.

You should get an initial response within a week. If a fix is warranted it will
ship in a patch release, and you will be credited in the advisory unless you
would rather not be.

## Supported versions

| Version | Supported |
|---|---|
| 1.0.x | Yes |
| < 1.0 | No — the pre-1.0 layout is superseded; the app migrates it automatically on startup |

## What Shambles touches

Useful context for judging impact. Fuller detail in
[TECH_SPEC.md](TECH_SPEC.md) §3.

- **Reads and writes OAuth credentials.** `~/.claude/.credentials.json` and
  per-profile copies under `~/.claude-profiles/`. Files are written `0600`,
  directories `0700`, applied to a temp file before an atomic rename so a
  credential is never briefly world-readable. Tokens are copied byte-for-byte
  and never parsed beyond reading an expiry timestamp.
- **Transmits nothing unless you turn on update checks.** One module in the
  package, `shambles/update_check.py`, may open a socket, and only when
  `update.check` is explicitly enabled (`shambles config set update.check
  true`; the default is off). Enabled, it makes at most one unauthenticated
  `GET` per day to the public GitHub Releases endpoint — no token, no account,
  no machine ID, no query string — and keeps a release tag and a timestamp in
  `~/.shambles/update-cache.json`. It never downloads a release and never
  replaces the running program. Nothing else in the codebase makes a network
  call of any kind, and no credential or config path is ever part of a
  request.
- **That boundary is mechanically enforced.**
  `tests/test_login.py::test_the_package_imports_no_networking_module`
  AST-scans every module in the package and permits a networking import in
  exactly one file, the one named above. Widening it means editing an
  allowlist that a second test asserts the contents of.
- **Never logs a token.** Not truncated, not masked. No token reaches stdout,
  a log file, or a dialog.
- **Rewrites two keys in `~/.claude.json`** — `oauthAccount` and
  `cachedUsageUtilization` — preserving every other key, after taking a backup.

## Threat model

Shambles assumes a single-user machine and defends against accidental exposure,
not a hostile local administrator. Specifically **out of scope**:

- Another user with root, or with your account's privileges, reading the token
  files. POSIX modes are the only barrier.
- **Windows**, where `chmod` cannot express these modes. Credentials there rely
  on the user profile's ACLs — the same protection Claude Code's own credentials
  file receives. Shambles neither strengthens nor weakens it.
- Malware already running as you. Nothing here can defend against that.

In scope, and worth reporting:

- Any path where a credential is written world-readable, even briefly.
- Any path where a token is logged, printed, or included in an error message.
- A profile name or config value that escapes `~/.claude-profiles/` and causes a
  read, write or delete elsewhere.
- Anything that destroys a credential or session history without the user
  confirming it.
