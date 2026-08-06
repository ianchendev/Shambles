# Token storage across Claude and Codex surfaces

Research for [#3](https://github.com/ianchendev/Shambles/issues/3). Prerequisite
for the cross-platform switcher UI in [#2](https://github.com/ianchendev/Shambles/issues/2).

## How to read the evidence grades

| Grade | Meaning |
|---|---|
| **[OBS]** | Observed first-hand on the test machine — Keychain metadata, file contents, live command output |
| **[SRC]** | Read out of shipping source: `openai/codex` is open source; Claude Code's logic was read out of the bundled JS in the shipping binary |
| **[EXP]** | Established by a controlled experiment |
| **[DOC]** | Official Anthropic or OpenAI documentation |
| **[INF]** | Inference — flagged as such, not established |

Test machine: macOS 15.5 (Darwin 25.5.0), arm64, 2026-08-06, with all five
surfaces installed. Claude Code CLI 2.1.220, VS Code `anthropic.claude-code`
2.1.222, Desktop-bundled Claude Code 2.1.221, `codex` 0.147.0-alpha.1.2.
**Linux and Windows behaviour below is from source reading, not execution** — no
such host was available.

No live credential value was ever decrypted or printed during this research.
Only paths, key names, types, lengths and non-secret plan metadata were read.

## The headline: five surfaces, three credential stores

The five surfaces in the issue are not five stores. Both VS Code extensions ship
and execute the *same native CLI binary* as the standalone CLI, and both desktop
apps bundle a copy too [OBS]:

```
~/.vscode/extensions/anthropic.claude-code-2.1.222-darwin-arm64/resources/native-binary/claude
~/Library/Application Support/Claude/claude-code/2.1.221/claude.app/Contents/MacOS/claude
~/.vscode/extensions/openai.chatgpt-26.5730.61639-darwin-arm64/bin/macos-aarch64/codex
/Applications/ChatGPT.app/Contents/Resources/codex
```

What actually exists:

| Store | Fed by |
|---|---|
| **Claude agent credentials** | Claude Code CLI · VS Code `anthropic.claude-code` |
| **Codex agent credentials** | Codex CLI · VS Code `openai.chatgpt` · Codex Desktop (ChatGPT.app) |
| **Claude Desktop** | Desktop chat · **and** its embedded `claude-code`, which receives a token by environment variable rather than reading the CLI store |

Plus ChatGPT.app's own chat cookie jar, which is incidental to agent auth.

Both VS Code extensions delegate entirely to the CLI store. For Codex this is
documented — "The CLI and extension share the same cached login details"
([learn.chatgpt.com/docs/auth](https://learn.chatgpt.com/docs/auth)) [DOC]. For
Claude it is settled by symbol counts over the extension's `extension.js` [SRC]:
`SecretStorage` 0, `context.secrets` 0, `secrets.store` 0, `onDidChangeSecrets` 0,
against `Bun.secrets` 22. Corroborated locally: neither extension has a
`secret://` row in VS Code's own SecretStorage DB, only ordinary UI-state rows,
while `vscode.github-authentication` does have one [OBS].

**Consequence for Shambles: supporting the two CLIs gets both VS Code extensions
for free.**

Two naming traps worth writing down:

- There is no separately-branded "Codex Desktop" binary. Codex ships **inside
  `/Applications/ChatGPT.app`**, as a Chromium fork called `Codex Framework.framework`.
- The Codex VS Code extension's directory is `openai.chatgpt-*`, **not** `*codex*`.
  A glob for "codex" misses it.

## Claude agent credentials

### Three backends, one per platform

The binary defines exactly three named backends [SRC]:

| Platform | Backend | Store |
|---|---|---|
| macOS | `keychain` | Keychain generic password, via `/usr/bin/security` |
| Windows | `windows-credman` | Credential Manager via `Bun.secrets`, **chunked** |
| Linux / fallback | `plaintext` | `$CLAUDE_CONFIG_DIR/.credentials.json`, mode 0600 |

The file backend emits `Warning: Storing credentials in plaintext.` [SRC].

On macOS `~/.claude/` exists at mode 700 and contains **no** `.credentials.json`
at all [OBS] — the Keychain is the sole store there.

### The macOS Keychain service name is COMPUTED — do not hardcode it

This is the single most important implementation fact in this document.

```js
// CLI 2.1.220, and byte-identical in the VS Code extension bundle   [SRC]
function oG(e = "") {
  let t = process.env.CLAUDE_SECURESTORAGE_CONFIG_DIR,
      r = t !== undefined ? !t : !process.env.CLAUDE_CONFIG_DIR,
      n = t !== undefined ? t.normalize("NFC") : <resolvedConfigDir>,
      o = r ? "" : `-${sha256(n).hex.substring(0, 8)}`;
  return `Claude Code${OAUTH_FILE_SUFFIX}${e}${o}`;
}
// called as oG("-credentials")
```

So the service name is `` `Claude Code${suffix}-credentials${dirHash}` ``, where
`dirHash` is `-` plus the first 8 hex of SHA-256 of the NFC-normalized config dir,
present **iff** `CLAUDE_CONFIG_DIR` is set and `CLAUDE_SECURESTORAGE_CONFIG_DIR`
is not the empty string.

`OAUTH_FILE_SUFFIX` is `""` in production, `"-custom-oauth"` under a custom
`CLAUDE_CODE_OAUTH_CLIENT_ID`, `"-local-oauth"` for local dev [SRC].

**Independently verified** [OBS]: computing the algorithm by hand gives
`sha256(NFC("/Users/<user>/.claude"))[:8] = 7f69f673`, matching exactly the
service name observed when the CLI was actually run with
`CLAUDE_CONFIG_DIR=$HOME/.claude`. Two independent derivations, same eight hex
characters.

The **account** name is not constant either [SRC]:

```js
let e = process.env.USER || os.userInfo().username;
if (!/^[a-zA-Z0-9._-]+$/.test(e)) return "claude-code-user";
return e;
// the extension's copy adds: if (process.platform === "win32") return "claude-code-user";
```

So: `$USER` on macOS and Linux, the literal `claude-code-user` on Windows, and
`claude-code-user` as the fallback for any username with unusual characters.

Confirmed on the test machine [OBS]: class `genp` (generic password, **not**
internet password), service `Claude Code-credentials`, account = the macOS
username, in `login.keychain-db`.

### The exact commands Claude Code runs

```
security find-generic-password   -a "$ACCT" -w -s "$SVC"
security add-generic-password -U -a "$ACCT"    -s "$SVC" -X "$HEX"
security delete-generic-password -a "$ACCT"    -s "$SVC"
```

[SRC]. Note `-X`: the payload is written **hex-encoded**, and `-U` updates in
place. There is a 30-second in-process read cache.

Claude Code therefore reaches the Keychain by **shelling out to `/usr/bin/security`,
not through Security.framework**. That answers one of the open design questions in
[#2](https://github.com/ianchendev/Shambles/issues/2) directly: do the same.

The item is created with **no `-T` / `-A` access-control arguments**, so any
process running as the user can read it without a prompt — the substance of
[Silverfort's published finding](https://www.silverfort.com/blog/skipping-the-lock-a-claude-code-cli-weakness-lets-any-macos-process-read-stored-credentials/).
This is why reading it during this research returned instantly with no
authorization dialog [OBS]. Convenient for a switcher; worth stating plainly in
the UI that this is the existing posture and Shambles does not worsen it.

### Windows: Credential Manager, chunked

Via `Bun.secrets`, not a shelled-out command [SRC]. Blobs exceed the per-entry
size cap, so values are split:

```js
const CHUNK = 2000;
function On(e, t) { return { service: e.service, name: `${e.name}#${t}` }; }
```

Entries are `{service: "Claude Code-credentials", name: "claude-code-user#<k>"}`
with markers `#p` / `#m` plus numeric chunks `#0…#n-1` [SRC]. **Any reader must
reassemble the chunks** — do not assume a single entry.

### Shape

Verified locally by reading the Keychain item (980 bytes, with the user's
explicit authorization) and printing structure only [OBS]:

```
claudeAiOauth.accessToken            str  len 108     opaque, NOT a JWT
claudeAiOauth.refreshToken           str  len 108     opaque, NOT a JWT
claudeAiOauth.expiresAt              int  epoch ms
claudeAiOauth.refreshTokenExpiresAt  int  epoch ms
claudeAiOauth.scopes                 list of 5 str
claudeAiOauth.subscriptionType       str
claudeAiOauth.rateLimitTier          str

organizationUuid                     str  len 36      top level, outside claudeAiOauth

mcpOAuth."<serverId>|<hash>".serverName                             str
mcpOAuth."<serverId>|<hash>".serverUrl                              str
mcpOAuth."<serverId>|<hash>".accessToken                            str
mcpOAuth."<serverId>|<hash>".clientId                               str
mcpOAuth."<serverId>|<hash>".redirectUri                            str
mcpOAuth."<serverId>|<hash>".discoveryState.authorizationServerUrl  str
mcpOAuth."<serverId>|<hash>".discoveryState.resourceMetadataUrl     str
mcpOAuth."<serverId>|<hash>".discoveryState.oauthMetadataFound      bool
```

The observed `mcpOAuth` key was `plugin:vercel:vercel|511b08192b045b3d`.

The container is read-modify-written (`r = store.read() || {}; r.claudeAiOauth = {…}`)
[SRC], so **treat the top level as open** — parse `claudeAiOauth` and `mcpOAuth`
non-exclusively rather than assuming a closed schema.

Two portability caveats [SRC]:

- `refreshTokenExpiresAt` appears 5 times in the CLI binary but **0 times in the
  extension bundle**, whose `saveOAuthTokens` writes only the other six fields.
  **Treat it as optional when parsing.**
- `mcpOAuth` appears 7 times in the CLI binary, **0 times in the extension**.

Complete scope set in the binary [SRC]: `user:inference`, `user:profile`,
`user:sessions:claude_code`, `user:mcp_servers`, `org:create_api_key`.

**Two things Shambles' current model does not account for:**

1. **`mcpOAuth` puts every MCP server's OAuth token in the same blob.** The
   README says MCP servers are shared across accounts. That is true of the
   *server list*, which lives in `~/.claude.json` — but their *access tokens* are
   account-scoped and travel with the credential store. Swapping credentials
   swaps MCP logins too.
2. **`organizationUuid` sits at the top level**, outside `claudeAiOauth`,
   duplicating `~/.claude.json`'s `oauthAccount.organizationUuid`.

### Identity lives somewhere else

The email is not in the credential store. It is in `~/.claude.json` under
`oauthAccount`, which on the test machine had nineteen keys [OBS]:

```
accountCreatedAt  accountUuid  billingType  ccOnboardingFlags
claudeCodeTrialDurationDays  claudeCodeTrialEndsAt  displayName
emailAddress  hasExtraUsageEnabled  organizationName
organizationRateLimitTier  organizationRole  organizationType
organizationUuid  profileFetchedAt  seatTier  subscriptionCreatedAt
userRateLimitTier  workspaceRole
```

This split is the reason Shambles has to splice `~/.claude.json` on every switch.
Note that `userID` also sits at `~/.claude.json` top level and looks
account-scoped, but is not currently in
[`configjson.ACCOUNT_KEYS`](../shambles/configjson.py).

**There is a cleaner probe than reading files.** `claude auth status` emits JSON
on stdout [OBS]:

```json
{"loggedIn": true, "authMethod": "claude.ai", "apiProvider": "firstParty",
 "email": "…", "orgId": "…", "orgName": "…", "subscriptionType": "team"}
```

Read-only, no Keychain prompt, no parsing of undocumented files. Worth using for
the "who is live right now" check in [`state.inspect`](../shambles/state.py).

### `CLAUDE_CONFIG_DIR` on macOS: the docs are wrong

Anthropic's documentation states that on macOS "credentials are in the Keychain
and carry over to the clean session"
([debug-your-config](https://code.claude.com/docs/en/debug-your-config)) [DOC].
**That is false as of 2.1.220**, because setting the variable changes the Keychain
service name and the item is no longer found.

Controlled experiment [EXP]:

| Environment | `loggedIn` |
|---|---|
| default | `true` |
| `CLAUDE_CONFIG_DIR=<fresh scratch dir>` | `false` |
| **`CLAUDE_CONFIG_DIR=$HOME/.claude`** — i.e. the default path, explicitly set | **`false`** |
| `CLAUDE_CONFIG_DIR=<scratch>` **plus `CLAUDE_SECURESTORAGE_CONFIG_DIR=""`** | **`true`** |

The third row is the smoking gun: pointing the variable at the *correct,
populated, default* directory still logs you out, because merely *setting* it
appends the hash. The fourth row gives the undocumented escape hatch —
`CLAUDE_SECURESTORAGE_CONFIG_DIR=""` suppresses the suffix.

This also explains the community-reported `Claude Code-credentials-<8hex>` items
that accumulate and trigger repeated Keychain prompts
([#72862](https://github.com/anthropics/claude-code/issues/72862)): each distinct
config dir mints its own item.

**What this means for Shambles.** `CLAUDE_CONFIG_DIR` *does* partition credentials
on macOS, contrary to both the docs and this repo's README. But it still relocates
the whole tree including `projects/`, so the README's core argument against using
it for account switching stands unchanged — it splits session history. The
correction is to the mechanism, not the conclusion.

Also found, undocumented [SRC]: `CLAUDE_CODE_HOST_CREDS_FILE`, and a
host-managed credential family — `CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST`,
`CLAUDE_CODE_OAUTH_TOKEN`, `CLAUDE_CODE_OAUTH_SCOPES`,
`CLAUDE_CODE_ORGANIZATION_UUID`, `CLAUDE_CODE_SUBSCRIPTION_TYPE`,
`CLAUDE_CODE_RATE_LIMIT_TIER`.

### Still logged in?

Two epoch-millisecond fields. `expiresAt` governs the access token and is
refreshed silently; `refreshTokenExpiresAt` is the one that decides whether you
face the verification email again.

**The observed refresh window was about 4 days, not 30** [OBS]:

```
expiresAt              1785997239903    2026-08-06 16:20:39.903
refreshTokenExpiresAt  1786304390903    2026-08-10 05:39:50.903
```

Both values end in the same millisecond (`903`), so both were computed from one
server response — the window is re-minted on every refresh, exactly as the README
describes, but it is not 30 days wide.

The gap between the two is fixed at 307151000 ms = 3.55 days. Since they share a
mint instant, the full window is `access-token lifetime + 3.55 days`. For any
plausible access-token lifetime the answer lands in a narrow band, so the
conclusion does not depend on knowing that lifetime:

| assumed access-token life | implied refresh window |
|---|---|
| 8 h (the figure the README uses) | 3.89 days |
| 10 h | 3.97 days |
| 12 h | 4.05 days |
| 24 h | 4.55 days |

So the window is bounded at roughly **3.9 to 4.6 days**, which excludes 30 days by
a wide margin.

### The window rolls, so an account in daily use never expires

This is why a short window goes unnoticed. Both timestamps are re-minted on every
refresh, and a refresh happens automatically whenever the access token lapses —
roughly every ten hours of use. Each day of use therefore pushes the deadline
another four days out; you can never catch up to it while you are using the
account.

The account's own history is the proof [OBS]: `accountCreatedAt` is
2024-10-31, 644 days before the measurement, and the holder reports never having
re-verified. On a non-rolling four-day window that would have required about 161
re-verifications.

**So the finding is not "your login breaks in four days."** It is:

- An account you use at least every few days behaves identically whether the
  window is 4 days or 30. No user-visible difference.
- An account **parked** — switched away from and left alone — dies after about
  four days rather than a month.

The second case is precisely Shambles' scenario. The entire premise of a
multi-account switcher is that while you use one account, the others sit idle.
Two consequences:

- [`profiles.EXPIRY_WARN_DAYS = 7`](../shambles/profiles.py) is larger than the
  whole window, so every profile renders amber permanently. A threshold near 1–1.5
  days, or wording like "touch this account within N days", would carry real
  information.
- Rotating three accounts on a weekly cadence means two of them lapse between
  uses. The countdown chip is therefore *more* load-bearing than the README
  assumes, not less — it is the only warning that a parked account is about to
  need an email round-trip.

This is a single sample, on client 2.1.220–2.1.222, from an account that is
**Max 5x** — see the plan-label warning below for why the credential blob's own
`subscriptionType` field says otherwise. A Free, Pro or Team account may well be
issued a different window. **Sample several plan tiers before changing anything.**

### The credential blob's `subscriptionType` is not a reliable plan label

On the test machine the two stores disagree about what plan the user is on [OBS]:

| Source | Field | Value |
|---|---|---|
| `~/.claude.json` `oauthAccount` | `organizationRateLimitTier` | **`default_claude_max_5x`** ← correct |
| `~/.claude.json` `oauthAccount` | `organizationType` | `claude_max` |
| credential store | `claudeAiOauth.subscriptionType` | **`team`** ← misleading |
| credential store | `claudeAiOauth.rateLimitTier` | `default_raven` |

The account holder confirmed the plan is Max 5x, matching
`organizationRateLimitTier`. `claude auth status` reports the credential store's
value and therefore also says `"team"`.

**Implication for the UI**: a switcher that shows a plan badge must read
`oauthAccount.organizationRateLimitTier` from `~/.claude.json`, **not**
`subscriptionType` from the credential store — the latter would label a Max 5x
user as "team". Whether `subscriptionType` is stale, an internal seat label, or
something else is unresolved.

## Codex agent credentials

Verified from source against `openai/codex` [SRC], and independently confirmed
against the local install [OBS] — `auth_mode`, the always-present null API-key
field, the JWT `exp` claims and the 0600 mode all matched.

### Where

`$CODEX_HOME/auth.json`, default `~/.codex/auth.json`, on **all three platforms** —
there is no XDG path on Linux and no `%APPDATA%` on Windows
(`codex-rs/utils/home-dir/src/lib.rs`, `find_codex_home()`) [SRC].

`CODEX_HOME` is the relocation variable, the analogue of `CLAUDE_CONFIG_DIR`.
Unlike Claude's it is strict: if set, the directory must already exist or Codex
errors out. It does **not** hash into a service name — it is a plain path swap.

A keyring backend exists but is **off by default**. `cli_auth_credentials_store`
in `config.toml` takes `file` (the default), `keyring`, `auto`, or `ephemeral`. In
keyring mode the service is `Codex Auth` and the account is
`cli|<first 16 hex of SHA-256 of the canonicalized CODEX_HOME path>`, with the
entire JSON blob as the value. On Windows the default backend is instead
`secrets`: the blob goes to an age-encrypted `$CODEX_HOME/secrets/codex_auth.age`
and only the passphrase reaches Credential Manager, presumably because of its
per-entry size limit [INF on the reason].

On the test machine `cli_auth_credentials_store` was unset and no `Codex Auth`
Keychain item existed [OBS] — consistent with plaintext-file being the
out-of-box behaviour.

### Shape

```
auth_mode        str        "apikey" | "chatgpt" | "chatgptAuthTokens" |
                            "headers" | "agentIdentity" |
                            "personalAccessToken" | "bedrockApiKey"
OPENAI_API_KEY   str|null   always serialized; null under OAuth
tokens.id_token       str   raw JWT
tokens.access_token   str   raw JWT
tokens.refresh_token  str   opaque
tokens.account_id     str   UUID
last_refresh     str        RFC 3339 / ISO 8601 UTC
```

Optional siblings: `agent_identity`, `personal_access_token`, `bedrock_api_key`.

API-key and subscription auth share one file, discriminated by `auth_mode` — they
are not separate stores.

**Parser trap:** `id_token` is a struct in the Rust source but is a **bare JWT
string on disk**. Its fields (`email`, `chatgpt_plan_type`, `chatgpt_account_id`, …)
are decoded from JWT claims at load time and never appear in the file.

### Still logged in?

**There is no expiry field.** Liveness is computed from the JWT [SRC]:

1. Decode the `exp` claim (epoch seconds) out of `tokens.access_token`; refresh
   when it is within 5 minutes.
2. Only if that claim cannot be parsed, fall back to `last_refresh` older than
   8 days.

Observed lifetimes [OBS]: `id_token` **1 hour**, `access_token` **10 days**. The
refresh token is opaque and its own expiry is recorded nowhere — the server
decides, returning `refresh_token_expired`, `refresh_token_reused` or
`refresh_token_invalidated` when re-login is required. Refresh tokens **rotate**:
a successful refresh overwrites `tokens.refresh_token` and stamps `last_refresh`.

### Identity and entitlements — all inside the JWT

There is no equivalent of Claude's `~/.claude.json` identity splice. `auth.json`
is self-contained, and `~/.codex/.codex-global-state.json` holds only UI state
[OBS]. Everything a switcher needs to render a profile row is in the `id_token`
payload, reachable by base64-decoding — no server call, no second file.

Claims observed under `https://api.openai.com/auth` [OBS]:

```
chatgpt_plan_type                    "pro"
chatgpt_account_id                   uuid
chatgpt_user_id                      "user-…"
chatgpt_subscription_active_start    2026-03-16T10:23:50+00:00
chatgpt_subscription_active_until    2026-09-01T01:41:11+00:00
chatgpt_subscription_last_checked    2026-08-04T04:40:53+00:00
organizations                        [{id, is_default, role, title}, …]
groups                               [...]
```

Plus `email`, `name`, `email_verified` under `.../profile`, and `auth_provider`
(`"google"` on the test machine) at the top level.

Note `chatgpt_subscription_active_until` — Codex records the **subscription's**
end date separately from any token expiry. Claude has no local equivalent.

**A switcher must base64-decode a JWT to show who a Codex profile belongs to** —
but having done so, it gets the plan, the org list and the subscription end date
for free.

### MCP OAuth

Separate from user auth [SRC]: keyring service `Codex MCP Credentials`, falling
back to `$CODEX_HOME/.credentials.json` — confusingly the same *filename* Claude
uses for user credentials, for a different purpose. Default mode here is `auto`
(keyring first), unlike user auth's `file`.

### Permissions

`0o600` on Unix, but applied **only at creation**
(`OpenOptions::mode` in `codex-rs/login/src/auth/storage.rs`) [SRC]. An existing
`auth.json` with looser permissions is truncated and rewritten without being
re-chmod'd. No Windows ACL hardening. The parent `~/.codex` inherits the umask and
was world-readable (`drwxr-xr-x`) on the test machine [OBS].

## Claude Desktop

**Fully separate from the CLI credential store.** The official docs list what
Desktop shares with Claude Code — `CLAUDE.md`, MCP servers, hooks, skills,
settings — and credentials are deliberately not on that list
([desktop docs](https://code.claude.com/docs/en/desktop)) [DOC]. An open feature
request to share sessions has no Anthropic reply
([#62206](https://github.com/anthropics/claude-code/issues/62206)).

A full Keychain sweep of the test machine found exactly two Claude services [OBS]:

| Service | Account | Class | Role |
|---|---|---|---|
| `Claude Code-credentials` | `$USER` | `genp` | CLI + VS Code extension |
| `Claude Safe Storage` | **`Claude`** | `genp` | Electron `safeStorage` key |
| `Claude Safe Storage` | **`Claude Key`** | `genp` | Chromium OSCrypt key (cookies) |

Note there are **two** items under `Claude Safe Storage` with different accounts.
Community tools that hardcode `-a "Claude Key"` miss the older one, and a bare
`-s "Claude Safe Storage"` lookup returns whichever matches first. **Always
specify `-a`.**

### Token storage

`~/Library/Application Support/Claude/config.json` holds [OBS]:

```
oauth:tokenCache      str len 1500   base64, does NOT parse as JSON
oauth:tokenCacheV2    str len 1968   base64, does NOT parse as JSON
lastKnownAccountUuid
dxt:allowlistCache:<orgUuid> / dxt:allowlistEnabled:<orgUuid>
```

The base64/not-JSON shape identifies these as Electron `safeStorage` `v10`
ciphertext, decryptable only with the Keychain key. They were not decrypted. The
Windows equivalent is a DPAPI-unwrap of `os_crypt.encrypted_key` from `Local State`.

### Session cookies

`~/Library/Application Support/Claude/Cookies` (SQLite) holds `.claude.ai`
cookies. Names only, values untouched [OBS]:

| host_key | name | secure | httpOnly | `encrypted_value` len | `value` len |
|---|---|---|---|---|---|
| `.claude.ai` | **`sessionKey`** | 1 | 1 | 179 | **0** |
| `.claude.ai` | `sessionKeyLC` | 1 | 1 | 51 | 0 |
| `.claude.ai` | `lastActiveOrg` | 1 | 0 | 83 | 0 |
| `.claude.ai` | `cf_clearance` | 1 | 1 | 467 | 0 |
| `.claude.ai` | `routingHint` | 1 | 1 | 499 | 0 |
| `claude.ai` | `anthropic-device-id` | 1 | 0 | 83 | 0 |

Every `value` is empty and every `encrypted_value` populated — nothing is stored
in plaintext. `sessionKey` expired roughly four weeks out from the observation
date.

So Desktop's answer is *both*: an encrypted OAuth token cache **and** a Chromium
cookie jar, under one OS-backed key.

### Same human, different store — measured

Desktop and the CLI on the test machine were signed in as the **same account**,
yet through completely separate stores [OBS]:

```
~/.claude.json       oauthAccount.accountUuid  = becfa8ab-…
Desktop config.json  lastKnownAccountUuid      = becfa8ab-…   ← byte-identical
```

(UUIDs truncated here; the two were compared in full and matched exactly.)

Desktop's `dxt:allowlistCache:<orgUuid>` keys also show it has seen two
organizations, one of which is the CLI's `organizationUuid`.

This is the useful demonstration: **being the same person in both places does not
make them one store.** Signing out of one leaves the other signed in, and a
switcher that swaps the CLI credential leaves Desktop untouched. Desktop's own
plan could not be read without decrypting `oauth:tokenCacheV2`, which was not
done.

### How Desktop's embedded Claude Code authenticates

Not through the Keychain at all. Desktop passes its child `claude` process
[OBS, from `~/Library/Logs/Claude/`]:

```
CLAUDE_CONFIG_DIR: /var/folders/…/T/claude-hostloop-plugins/<hash>   ← ephemeral temp dir
CLAUDE_CODE_OAUTH_TOKEN, CLAUDE_CODE_OAUTH_SCOPES,
CLAUDE_CODE_ORGANIZATION_UUID, CLAUDE_CODE_SUBSCRIPTION_TYPE,
CLAUDE_CODE_RATE_LIMIT_TIER, CLAUDE_CODE_PROVIDER_MANAGED_BY_HOST
```

All six variables and the `claude-hostloop-plugins/<hash>` path were confirmed
present in the Desktop logs on the test machine [OBS].

So Desktop **injects its own OAuth access token by environment variable** and
points the child at a throwaway config dir. `CLAUDE_CODE_OAUTH_TOKEN` outranks
subscription OAuth in the documented precedence chain, so the child never reads
the Keychain — and the ephemeral `CLAUDE_CONFIG_DIR` additionally forces a hashed
service name, isolating it from `Claude Code-credentials` belt-and-braces.

This is the correct explanation for
[#78838](https://github.com/anthropics/claude-code/issues/78838): Desktop sessions
bill to the Desktop login while `~/.claude.json` names a different account,
because the app never touches `oauthAccount`.

## Codex Desktop (ChatGPT.app)

Chromium profile at `~/Library/Application Support/Codex/Default/` with `Cookies`,
`Login Data`, `Account Web Data`, `Local State`. Cookies observed for
`.chatgpt.com` / `.chat.openai.com`: `oai-sc`, `_puid`, `_devicecheck`, `__cf_bm`,
`__oailb`, `__cflb`, `_cfuvid`, encrypted with the `Codex Safe Storage` Keychain
key [OBS].

But unlike Claude Desktop, the *agent* auth is plain `~/.codex/auth.json`, shared
with the CLI [INF, strong]. ChatGPT.app bundles the identical `codex` binary,
stores its non-credential state in `~/.codex` (`ipc/`, `logs_2.sqlite`,
`computer-use/`, `.codex-global-state.json` with 20+ `electron-*` keys), and keeps
no credentials of its own [OBS]. OpenAI's auth doc names only the CLI and the
extension, so desktop sharing is high-confidence inference rather than documented
fact.

## The tokens themselves — what each one is for

Seven distinct credential types appear across these products. They are not
interchangeable and they fail in different ways.

| Token | Product | Form | Life | What it does |
|---|---|---|---|---|
| `claudeAiOauth.accessToken` | Claude agent | opaque, 108 ch | hours | Sent on every API call. Refreshed silently; you never notice it expire. |
| `claudeAiOauth.refreshToken` | Claude agent | opaque, 108 ch | **~4 days** | Mints new access tokens. **This is the one that saves you the verification email.** |
| `mcpOAuth.*.accessToken` | Claude agent | opaque | per server | Logs you into an individual MCP server. Nothing to do with your Claude login, but lives in the same blob. |
| `tokens.access_token` | Codex | **JWT**, 1753 ch | **10 days** | The API credential. Carries plan and org claims. |
| `tokens.id_token` | Codex | **JWT**, 2296 ch | **1 hour** | An *identity document*, not an API credential. Who you are, what plan, which orgs. |
| `tokens.refresh_token` | Codex | opaque, 196 ch | server-decided | Mints new access and id tokens. **Rotates on every use** — the old value stops working. |
| `sessionKey` cookie | Claude Desktop | encrypted cookie | ~4 weeks | An ordinary web session, the same kind claude.ai issues a browser. Not OAuth at all. |

Plus `oauth:tokenCacheV2` in Desktop's `config.json` — safeStorage ciphertext
wrapping Desktop's own OAuth material, and `CLAUDE_CODE_OAUTH_TOKEN`, the access
token Desktop injects into its child `claude` by environment variable.

### The structural difference that matters most

**Claude's tokens are opaque; Codex's are JWTs.** That single fact drives most of
the design divergence:

- A Claude token tells you nothing. Identity has to come from a *separate* file
  (`~/.claude.json`), which is exactly why Shambles must splice that file on every
  switch, and why an interrupted switch can leave the token and the displayed
  email disagreeing.
- A Codex token describes itself. Email, plan, org list, expiry and subscription
  end date all come out of one base64 decode, with no second file and no server
  call — so a Codex switcher has no splice step and no way to desynchronize.

Second difference: **where expiry lives.** Claude writes two explicit
epoch-millisecond fields next to the tokens. Codex writes none and expects you to
read the JWT `exp` claim, keeping `last_refresh` only as a fallback for when the
JWT cannot be parsed.

Third: **refresh-token rotation.** Codex replaces the refresh token on every use,
so a stale copy of `auth.json` restored over a newer one is actively harmful — the
old refresh token has already been invalidated. Claude's refresh token appears
stable across a refresh, with only its expiry window moving. **A Codex profile
store must therefore never restore a stale snapshot**, which is a sharper
constraint than anything Shambles handles today.

## What this means for Shambles

1. **Codex is the easier target than Claude, on every OS.** One plaintext
   600-mode file at a fixed path, shared by all three surfaces, identity inside it.
   No Keychain, no second file to splice, no per-OS divergence, no computed
   service name.
2. **Never hardcode the Claude Keychain service name.** Reimplement
   `` `Claude Code${suffix}-credentials${dirHash}` ``. Hardcoding
   `Claude Code-credentials` breaks for any user who has ever set
   `CLAUDE_CONFIG_DIR`.
3. **Shell out to `/usr/bin/security`, not PyObjC.** It is what Claude Code
   itself does, and the item carries no ACL restricting readers. This settles one
   of #2's open design questions.
4. **Windows is a third backend, not a Linux clone** — Credential Manager, chunked
   at 2000 chars across `#p` / `#m` / `#0…#n-1` entries, account always the literal
   `claude-code-user`. Any Windows support must reassemble chunks.
5. **Both VS Code extensions come free.** No extension-specific work.
6. **Claude Desktop needs a completely different code path** and is a much harder
   target: `Claude Safe Storage` Keychain key → OSCrypt decrypt → `config.json`
   `oauth:tokenCacheV2` or the cookie jar, on a database a running app holds open.
   Recommend explicitly out of scope for v1, and say so in the UI rather than
   silently doing nothing.
7. **Prefer `claude auth status`** over parsing `~/.claude.json` for the "who is
   live" check — it is read-only, JSON, and documented-ish.
8. **Two corrections to the current README**: the refresh window is ~4 days, not
   30; and MCP OAuth tokens are account-scoped, not shared.
9. **Codex refresh tokens rotate — never restore a stale `auth.json`.** Shambles'
   current model copies a credential file in and out and assumes the copy stays
   valid. That holds for Claude but not for Codex: once a newer refresh has run,
   the snapshot in the profile store is dead. A Codex profile must be re-stashed
   after every use, not just on switch-away.
10. **Do not render `subscriptionType` as the plan.** It read `team` for a Max 5x
    account. Use `oauthAccount.organizationRateLimitTier` instead.

## Open questions

- Is the ~4-day refresh window plan-specific? Needs sampling across Free / Pro /
  Max / Team. The one sample was Team.
- Does Linux's `~/.claude/.credentials.json` carry `mcpOAuth` and
  `organizationUuid`, or is the macOS Keychain blob a superset? Source reading
  suggests the same container is used, but this was not executed on Linux.
- Does `security add-generic-password -U` re-prompt when Shambles is the writer
  rather than Claude Code? Needs testing on a real switch.
- [#30538](https://github.com/anthropics/claude-code/issues/30538) reports the VS
  Code extension **ignores** `CLAUDE_CONFIG_DIR` on macOS. If true, the extension
  and CLI would resolve to different Keychain items whenever that variable is set
  — worth reproducing, since it directly affects whether "support the CLI and the
  extension follows" holds in that configuration.
- Codex Desktop sharing `~/.codex/auth.json` is strong inference, not documented.
  Confirmable by logging out in ChatGPT.app and watching the file.
