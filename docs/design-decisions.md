# Design decisions

Recorded decisions and their rationale, for the cross-platform, multi-provider
switcher scoped in [#2](https://github.com/ianchendev/Shambles/issues/2).
Evidence for the claims below is in [token-storage.md](token-storage.md).

Status values: **Decided** · **Leaning** (a direction, not yet committed) ·
**Open**.

---

## DD-1 — Token lifetime is system state, not a user-facing number

**Status: Decided**

### Context

Research measured the Claude refresh window at roughly four days, rolling forward
on every refresh. Two facts follow that pull in opposite directions:

- For an account in regular use the number is meaningless — the deadline moves
  faster than the calendar, and the account never lapses.
- For a **parked** account the number is the only warning that a re-login is
  coming. Parked accounts are the entire premise of a switcher.

So the countdown has to be computed, but "3.7 days remaining" is the wrong thing
to put in front of someone. It answers a question they did not ask.

### Decision

Compute idle time and remaining window internally. Surface them **as a state, not
a duration**. The user-facing vocabulary is about whether the switch will work:

| Internal state | What the user sees |
|---|---|
| window healthy | the account is simply switchable, no annotation |
| window closing soon | a nudge to use this account before it lapses |
| window closed | **"needs login — can't switch to this one"** |

The raw timestamps stay available in tooltips or a details view for anyone who
wants them, but they are never the primary reading.

### Consequences

- [`profiles.EXPIRY_WARN_DAYS = 7`](../shambles/profiles.py) is wrong twice over:
  it is longer than the entire window, so everything renders amber permanently,
  and it is expressed in the units this decision moves away from. It becomes an
  internal threshold feeding a state label, and its value needs to drop to
  roughly 1–1.5 days.
- The "window closed" state must be a **first-class UI state**, not an error.
  At a four-day window it will be common, not exceptional — a user rotating three
  accounts weekly will meet it constantly.
- Per-provider thresholds are required. Codex access tokens last ten days against
  Claude's four, so one shared constant cannot serve both.

---

## DD-2 — Do not implement login inside the tool

**Status: Leaning (not committed)**

### Context

When a profile's window has closed, something has to re-authenticate it. The
tempting move is to run the OAuth flow in-app so the user never leaves the
switcher.

### Decision

Do not. Detect the lapsed state and hand off to the vendor's own flow — `claude`
then `/login`, or `codex login` — the way the current README already instructs.

### Rationale

The stated reason is user trust: a third-party tool that asks for your Claude or
OpenAI login is asking for exactly the thing a phishing tool would ask for, and no
amount of open source fixes that instinct.

**There is a second, structural reason that may matter more.** The README's
security argument is that the tool is inert:

> It is entirely local and cannot touch your Claude account. The complete import
> list across the application is `json`, `os`, `shutil`, `sys`, `time`,
> `pathlib`, `dataclasses`, `tkinter`. There is no `socket`, no `urllib`, no
> `requests`, no `subprocess`.

Implementing login requires network access and OAuth handling, which destroys that
property outright. The claim "cannot reach Anthropic's servers, so it cannot
affect your login, billing, rate limits or organisation membership" stops being
true. That is a large amount of earned trust to spend on saving one terminal
command.

### Consequences

- The lapsed-profile UI must be genuinely helpful, since it is the handoff point:
  name the account, give the exact command, explain that this is the one and only
  time an email is involved.
- The tool never sees a password, never opens a browser, never holds a token it
  did not find already on disk.

### Connected item: subprocess is permitted; one README sentence goes stale

**Using `subprocess` is approved** — it is not a constraint on this project. The
macOS build will shell out to `/usr/bin/security`, the same system utility Claude
Code itself uses (see DD-3 and the Keychain section of
[token-storage.md](token-storage.md)). PyObjC bindings to Security.framework were
considered and rejected: a native extension is a larger surface, not a smaller
one, and it would not match Claude Code's own access pattern.

What this leaves is a documentation task. README line 229 currently asserts, as a
statement of fact about the code:

> There is no `socket`, no `urllib`, no `requests`, no `subprocess`.

Once the macOS build ships, the last item stops being true.

Worth noting that the four terms in that list are not doing equal work. `socket`,
`urllib` and `requests` are all about **network reach**, and the sentence that
follows — "It cannot reach Anthropic's servers, so it cannot affect your login,
billing, rate limits or organisation membership" — rests entirely on them.
`subprocess` is in the list for a different property: executing nothing at all.
Dropping it costs the paragraph nothing structural, because the load-bearing
claim was never "executes nothing", it was "no network".

Replacement wording, to land **with** the macOS build and not before — the current
code genuinely does not spawn processes, so editing this early would make the
README wrong in the other direction:

> No network: no `socket`, no `urllib`, no `requests`. It cannot reach Anthropic's
> servers, so it cannot affect your login, billing, rate limits or organisation
> membership.
>
> On macOS it executes one external program: `/usr/bin/security`, the same system
> utility Claude Code itself uses to read and write the very credential item this
> tool swaps. Nothing else is ever executed.

---

## DD-3 — "Switch to account X" is the only user-facing action

**Status: Decided**

### Context

The research surfaced a lot of moving parts: a spliced `~/.claude.json`, MCP OAuth
tokens riding inside the credential blob, a JWT that must be base64-decoded to
learn who a Codex profile belongs to, a computed Keychain service name, chunked
Windows credentials.

None of that is the user's problem. What the user wants is to be on a different
account on a given platform, now.

### Decision

The interface is: pick a platform, pick an account, done. Every mechanism above
happens silently. Access tokens, refresh tokens, expiry timestamps and org UUIDs
are never presented as things to manage, and there is no "refresh", "repair" or
"manage tokens" affordance.

### Consequences

- **No token is ever displayed.** Not truncated, not masked, not in a details
  pane. There is no user need it serves.
- Identity resolution must be automatic per provider: read
  `oauthAccount.emailAddress` for Claude, base64-decode the `id_token` for Codex.
  The user sees an email either way and never learns the two came from different
  places.
- **Silent work must still be correct work.** Two research findings become
  background invariants rather than features:
  - Codex refresh tokens rotate on every use, so a stale `auth.json` snapshot is
    actively harmful. Codex profiles must be re-stashed after use, not only on
    switch-away. Invisible to the user, load-bearing for correctness.
  - MCP OAuth tokens travel inside the Claude credential blob, so switching
    accounts also switches MCP server logins. Whether that is desirable is
    undecided — see open items.
- If a switch cannot be performed silently and correctly, it must fail loudly
  rather than half-apply. The existing "refuse before anything moves if the config
  cannot be parsed" behaviour in
  [`switcher.switch`](../shambles/switcher.py) is the right instinct and should be
  the model everywhere.
- **Do not render `subscriptionType`.** It read `team` for a Max 5x account. If a
  plan badge is wanted, `oauthAccount.organizationRateLimitTier` is the accurate
  field.

---

## DD-4 — Provider facts are data; adapters are two thin orthogonal layers

**Status: Decided**

### Context

Supporting Claude and Codex across three operating systems looks like a
2 × 3 matrix of six implementations. It is not, and treating it as one would
produce five copies of the same bug.

The variation has two *independent* axes:

- **Where the bytes live** — file, macOS Keychain, Windows Credential Manager.
  This is a platform property. It knows nothing about who issued the token.
- **What the bytes mean** — JSON shape, where identity lives, how expiry is
  computed, what else has to move. This is a provider property. It is identical
  on every OS.

Claude picks a different store per platform; Codex picks the same store on all
three. Cross them and you get six combinations, but only three stores and two
providers need to be written.

### Decision

**Two layers, plus a data file per provider.**

```
CredentialStore     where bytes live — platform-shaped, provider-blind
  FileStore(path, mode)
  KeychainStore(service, account)        subprocess to /usr/bin/security
  CredmanStore(service, account, chunk)  reassembles chunked entries
  → read() -> bytes|None · write(bytes) · delete()

Provider            what bytes mean — provider-shaped, platform-blind
  store_for(platform) -> CredentialStore
  identity(blob)      -> Identity(email, display_name, plan, org)
  liveness(blob, now) -> Liveness(state, expires_at)
  stash / restore     may touch companion files
  login_hint()        -> the exact command to give a lapsed profile
  policy              rotation, restash-after-use
```

The declarative half of each Provider lives in
[`shambles/providers/<id>.json`](../shambles/providers/) — paths, service-name
templates, JSON pointers, expiry semantics, login commands. The code half is only
what cannot be data: JWT decoding, Windows chunk reassembly, the
`~/.claude.json` splice.

Those specs ship **inside the package**, not under `docs/`, because they are read
at runtime and there must be exactly one copy. A documentation copy would be a
second source of truth, which is the drift this design exists to prevent.

**The core never learns a provider's name.** `switcher`, `state` and `gui` talk
only to the `Provider` interface.

### Why this is cheaper than it looks

Most of the current codebase is already provider-agnostic and simply mis-labelled:

| Component | Status |
|---|---|
| [`state.py`](../shambles/state.py) state machine — MANAGED / DRIFTED / MISSING_PROFILE / UNKNOWN | **already generic**, keep as is |
| [`configjson.py`](../shambles/configjson.py) atomic write, backup, prune | **already generic** |
| [`switcher.switch`](../shambles/switcher.py) flow — verify, backup, stash outgoing, restore incoming, record active | **already generic**; only its steps are Claude-specific |
| profile-name validation | **already generic** |
| [`paths.py`](../shambles/paths.py) | hardcodes `.claude*`; the injectable-home *structure* survives, the constants move to the spec |
| `configjson.ACCOUNT_KEYS` | becomes `provider.companion_writes` |
| [`profiles.token_state`](../shambles/profiles.py) | becomes `provider.liveness()` |
| [`gui.py`](../shambles/gui.py) | profiles grouped by provider; otherwise unchanged |

The flow and the state machine — the parts that took the most thought — are
untouched. What moves is leaf facts.

### What makes it changeable rather than merely layered

A layer diagram does not make a system swappable. Two things do:

1. **One shared contract test suite, parametrized over providers.** The existing
   load-bearing test — `test_credentials_survive_a_round_trip_unmodified` — stops
   being a Claude test and becomes the first case every provider must pass, along
   with: switching to a never-logged-in profile clears rather than reuses; an
   unparseable config aborts before anything moves; stash-then-restore is
   idempotent. **Adding a provider means writing a spec, a thin adapter, and
   passing a suite that already exists.**
2. **The spec file is the same file the documentation renders from.** Facts cannot
   drift from docs because there is one copy. A JSON Schema in
   `tests/test_spec.py`, run in CI, catches a spec that is malformed or fails to
   ship as package data — the latter being invisible until runtime.

The research already proved these facts drift: the Keychain service name became
computed rather than constant, and `refreshTokenExpiresAt` is absent from the VS
Code extension's writes. A one-line data edit is the correct cost for that kind
of change.

### What NOT to abstract

The repo is 1745 readable lines. The failure mode here is a framework.

- **No transform DSL for `companion_writes`.** Claude has one splice; Codex has
  none. Two data points cannot justify a general engine — if a third provider
  needs something stranger, it writes code.
- **No plugin loader, no entry points.** Providers are a closed, in-tree set.
- **No per-provider GUI.** One list, grouped by provider.
- **Claude Desktop does not join this interface.** Its cookie jar and
  safeStorage blob are a different problem, out of scope per DD-3.

### Consequences

- The profile store layout becomes provider-scoped —
  `~/.shambles/<provider>/<name>/` — and the pre-1.0 migration in
  [`migrate.py`](../shambles/migrate.py) gains a second hop.
- `Profile` grows a `provider` field; `EXPIRY_WARN_DAYS` becomes per-provider
  (DD-1 already requires this: Claude ~4 days, Codex ~10).
- Codex's `restash_after_use` policy has no Claude equivalent, so the switch flow
  gains a post-use hook that is a no-op for Claude.

---

## Open items

- **DD-2 is a leaning, not a commitment.** Revisit if the lapsed state proves
  common enough to be genuinely painful — a four-day window makes that plausible.
- **Update README line 229 in the same change that ships macOS support** — not
  earlier, or it describes behaviour the code does not yet have. Wording drafted
  under DD-2.
- **Decide whether MCP OAuth tokens should follow the account.** They currently
  do, as a side effect of living in the same blob. Both answers are defensible;
  the decision should be deliberate rather than inherited.
- **Sample the refresh window across plan tiers.** Every number in DD-1 rests on
  one Max 5x account.
