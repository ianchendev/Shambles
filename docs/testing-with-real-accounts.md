# Testing with real accounts

A checklist for a person with two real accounts on one machine. It covers what
no CI runner can: signing in through Shambles with a real account, then
switching, switching back, re-signing in and removing, on macOS and on native
Windows.

It takes about 20 minutes per vendor. Do Claude Code, Codex, or both.

## Before you start

**What you are risking.** Nothing on the vendor's side: your conversations,
settings and subscription are not stored by Shambles. The worst case is that
an account needs a fresh sign-in, with its verification email.

**Rules for the whole test:**

- **Do not sign out or sign in by hand.** No `claude auth logout`, no
  `/logout`, no `codex login`, no `codex logout`. Each one revokes the login
  that is currently stored, and the copy Shambles saved dies with it. Every
  sign-in in this checklist goes through Shambles.
- **Quit Claude Code and Codex before each switch**, including the VS Code
  extension (run *Developer: Reload Window* afterwards). A running session
  keeps the account it started with.
- **Write down only what the steps ask for.** See [What to send
  back](#what-to-send-back). Never send a token, the contents of
  `.credentials.json`, `auth.json` or `~/.shambles`, an email address, or a
  screenshot that shows one. Call your accounts **A** and **B**.

**Set up.** Install Shambles with the install script from the README, then
note:

| | macOS (Terminal) | Windows (PowerShell, not WSL) |
|---|---|---|
| System and version | `sw_vers -productVersion` and `uname -m` | `[Environment]::OSVersion.Version` and `$env:PROCESSOR_ARCHITECTURE` |
| Shambles | `shambles --version` | `shambles --version` |
| Vendor versions | `claude --version`, `codex --version` | the same |
| Where the vendor is | `which claude codex` | `where.exe claude codex` |
| How you installed the vendor | npm, Homebrew, the vendor's installer | npm, WinGet, the vendor's installer |

In any path you send back, replace your user name with `<me>`.

Start signed in to the vendor as account **A**, the usual way.

## The steps

Use the window (`shambles gui`). If it does not open, write down what it said
and use the terminal dashboard (`shambles`) instead.

**After every step marked "Check"**, open a **new** terminal and look at
three things:

1. **Which account the vendor says is signed in.**
   Claude: `claude auth status`. Codex: start `codex`, type `/status`, quit.
   Write down **A**, **B**, **signed out** or **error**.
2. **Whether a request works.**
   Claude: `claude -p "Reply with the word ok"`.
   Codex: `codex exec "Reply with the word ok"`.
   Write down **ok**, **asked me to sign in**, or the error.
3. **Which card Shambles shows as live**, and any chip on it (`needs login`,
   `signed out`, `soon`).

| # | Do this | Expect |
|---|---|---|
| 1 | `shambles doctor` | No `PROBLEM` lines. Keep the output |
| 2 | In the window, press **Save** on the card for your current login and name it `A`. If Shambles already has it saved, use that card as A. **Check** | A, ok, card A live. Nothing else changes |
| 3 | **＋ Add Account**, pick the vendor, name it `B`. When the browser opens, close the tab without signing in, then press **Cancel** in Shambles. **Check** | You are back on A: A, ok, card A live. Card B is listed with `needs login` |
| 4 | Press **Sign in** on card B and sign in to account **B** in the browser. **Check** | B, ok, card B live. This is the re-sign-in path |
| 5 | Press **Switch** on card A. **Check** | A, ok, with no sign-in asked for |
| 6 | Press **Switch** on card B. **Check** | B, ok, with no sign-in asked for |
| 7 | Switch to A again. Then press **✕** on card B and confirm. **Check** | A, ok. Card B is gone |
| 8 | **＋ Add Account**, name it `B` again, and this time sign in to account **B**. **Check** | B, ok, card B live. This is the plain sign-in path |
| 9 | Switch to A. `shambles doctor` again | A, ok. Same `doctor` output as step 1 |

If anything is not as expected, stop there and send what you have. Do not try
to repair it by signing out.

## What to look for on each system

**macOS.** Any Keychain dialog: when it appeared (which step), the program it
named, the exact wording, and which button you pressed. Whether `doctor` says
the login is in the Keychain or in `~/.claude/.credentials.json`.

**Windows.** Whether SmartScreen warned on first run. Whether `doctor` says
Claude Code keeps its login in `.credentials.json` or in Windows Credential
Manager: that depends on a setting Anthropic is rolling out per account, and
nobody outside Anthropic knows which you have until you look.

## What to send back

Copy this, fill it in, and send it to Ian. Replace every address with A or B
and your user name with `<me>`.

```text
System:            (for example macOS 26.1 arm64, or Windows 11 24H2 x64)
Shambles:          (shambles --version)
Installed with:    (install script / pipx / other)
Vendor:            (Claude Code or Codex, version, how installed, where)
Window or dashboard:

Step | vendor says | request | live card and chip | as expected?
1    | -           | -       | -                  |
2    |             |         |                    |
3    |             |         |                    |
4    |             |         |                    |
5    |             |         |                    |
6    |             |         |                    |
7    |             |         |                    |
8    |             |         |                    |
9    |             |         |                    |

Messages Shambles showed (exact text, addresses replaced):

Keychain dialogs or SmartScreen warnings (step, wording, what you pressed):

shambles doctor, step 1 (user name replaced):

shambles doctor, step 9 (user name replaced):
```
