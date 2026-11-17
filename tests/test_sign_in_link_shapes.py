"""The sign-in links the vendors really print, and what the window shows.

The filter in ``login.authorization_url`` lets through only vendor sign-in
requests, so the window never offers an arbitrary address from a vendor's
output. Its earlier tests used simplified links, and every link Claude Code
actually prints was being thrown away: the sheet waited for a link forever.

The links below are built the way the vendors build them, with dummy ids,
challenges and states:

- Claude Code 2.1.300 (the same in 2.1.270 and 2.1.289), read from the
  installed binary, never by running its login: ``LPr()`` appends
  ``code=true``, ``client_id``, ``response_type``, ``redirect_uri``,
  ``scope``, ``code_challenge``, ``code_challenge_method``, ``state``, then
  ``orgUUID``, ``login_hint`` and ``login_method`` when set, to
  ``https://claude.com/cai/oauth/authorize`` (Claude account) or
  ``https://platform.claude.com/oauth/authorize`` (Console), serialised by
  ``URLSearchParams``. ``claude auth login`` prints the one whose redirect is
  ``https://platform.claude.com/oauth/code/callback`` (the page that shows a
  code to paste back) as "If the browser didn't open, visit: <link>".
- Codex, from its source (``codex-rs/login/src/server.rs``,
  ``build_authorize_url``): ``https://auth.openai.com/oauth/authorize`` with
  a ``http://127.0.0.1:<port>/auth/callback`` redirect, the connectors
  scopes, ``originator=codex_cli_rs`` and, for a forced workspace,
  ``allowed_workspace_id``. ``codex login`` prints it alone on a line.
"""

import shlex

import pytest

from conftest import posix_only
from helpers import make_profile
from shambles import login, providers
from shambles.app.service import (HIDDEN_LINE, ShamblesService,
                                  _safe_login_line)


SCOPES = ("org%3Acreate_api_key+user%3Aprofile+user%3Ainference"
          "+user%3Asessions%3Aclaude_code+user%3Amcp_servers"
          "+user%3Afile_upload+user%3Aplugins")
PKCE = ("&code_challenge=Ch4llenge-Value_0123456789abcdefghijklmnopq"
        "&code_challenge_method=S256"
        "&state=St4te-Value_0123456789abcdefghijklmnopqrstu")
CLAUDE_QUERY = (
    "?code=true&client_id=00000000-0000-4000-8000-000000000000"
    "&response_type=code"
    "&redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback"
    f"&scope={SCOPES}{PKCE}")

CLAUDE_ACCOUNT = "https://claude.com/cai/oauth/authorize" + CLAUDE_QUERY
CLAUDE_CONSOLE = "https://platform.claude.com/oauth/authorize" + CLAUDE_QUERY
CLAUDE_SSO = (CLAUDE_ACCOUNT
              + "&orgUUID=11111111-2222-4333-8444-555555555555"
              + "&login_hint=someone%2Bwork%40example.test"
              + "&login_method=sso")
CLAUDE_AUTOMATIC = CLAUDE_ACCOUNT.replace(
    "https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode%2Fcallback",
    "http%3A%2F%2Flocalhost%3A54545%2Fcallback")

CODEX = (
    "https://auth.openai.com/oauth/authorize?response_type=code"
    "&client_id=app_EXAMPLEclientid0000"
    "&redirect_uri=http%3A%2F%2F127.0.0.1%3A1455%2Fauth%2Fcallback"
    f"{PKCE}"
    "&scope=openid+profile+email+offline_access"
    "+api.connectors.read+api.connectors.invoke"
    "&id_token_add_organizations=true&codex_cli_simplified_flow=true"
    "&originator=codex_cli_rs")
CODEX_WORKSPACE = CODEX + "&allowed_workspace_id=ws-0001%2Cws-0002"

#: What Claude Code prints around the link.
CLAUDE_LINE = "If the browser didn't open, visit: {}"

#: Claude Code wraps the link in a terminal hyperlink (OSC 8, ended by BEL)
#: whenever it thinks the terminal can show one, and it decides that from
#: the environment as well as from whether stdout is a terminal: Windows
#: Terminal's WT_SESSION, which WSL shells inherit, is enough, as are VS
#: Code's and JetBrains' terminals. The link then comes out twice, once as
#: the hyperlink's target and once as its text.
HYPERLINK = "\x1b]8;;{0}\x07{0}\x1b]8;;\x07"


@pytest.mark.parametrize("url", [
    CLAUDE_ACCOUNT, CLAUDE_CONSOLE, CLAUDE_SSO, CLAUDE_AUTOMATIC,
], ids=["claude-account", "console", "sso-with-hint", "localhost-callback"])
def test_the_links_claude_code_prints_reach_the_window(url):
    assert _safe_login_line(CLAUDE_LINE.format(url)) == url


@pytest.mark.parametrize("url", [CODEX, CODEX_WORKSPACE],
                         ids=["codex", "forced-workspace"])
def test_the_links_codex_prints_reach_the_window(url):
    assert _safe_login_line(url) == url


def test_a_link_printed_as_a_terminal_hyperlink_reaches_the_window():
    line = CLAUDE_LINE.format(HYPERLINK.format(CLAUDE_ACCOUNT))

    assert _safe_login_line(line) == CLAUDE_ACCOUNT


def test_a_coloured_link_reaches_the_window():
    line = CLAUDE_LINE.format(
        HYPERLINK.format(f"\x1b[94m{CLAUDE_ACCOUNT}\x1b[39m"))

    assert _safe_login_line(line) == CLAUDE_ACCOUNT


def test_what_a_hyperlink_hides_is_never_offered():
    """Only the visible text is read. A hyperlink whose target is a sign-in
    link but whose text is something else offers nothing, and one whose
    text is a sign-in link offers that, never the target behind it."""
    hidden_target = "\x1b]8;;{}\x07{}\x1b]8;;\x07"

    assert _safe_login_line(hidden_target.format(
        CLAUDE_ACCOUNT, "https://example.test/elsewhere")) == HIDDEN_LINE
    assert _safe_login_line(hidden_target.format(
        "https://example.test/elsewhere", CLAUDE_ACCOUNT)) == CLAUDE_ACCOUNT


@pytest.mark.parametrize("query", [
    "?code=credential-sentinel&state=abc",
    "?code=true&code=true&state=abc",
    "?code=&state=abc",
    "?login_method=sso%26token%3Dcredential-sentinel",
    "?orgUUID=not-a-uuid%3Fcredential-sentinel",
    "?redirect_uri=https%3A%2F%2Fplatform.claude.com%2Foauth%2Fcode"
    "%2Fcallback%3Fcode%3Dcredential-sentinel",
    "?redirect_uri=https%3A%2F%2Fclaude.com.evil.test%2Foauth%2Fcode"
    "%2Fcallback",
])
def test_claudes_new_parameters_still_fail_closed(query):
    """``code`` carries an authorization code in every other OAuth message;
    here it is only ever the literal ``true``."""
    for endpoint in ("https://claude.com/cai/oauth/authorize",
                     "https://platform.claude.com/oauth/authorize"):
        assert _safe_login_line(f"Visit {endpoint}{query}") == HIDDEN_LINE


def test_find_url_stops_at_control_characters():
    """A stray control character is never part of an address."""
    assert login.find_url("https://claude.com/cai/oauth\x07rest") == \
        "https://claude.com/cai/oauth"


@posix_only
def test_the_window_gets_the_link_from_a_real_shaped_claude_login(
        paths, fake_vendor):
    """End to end through the vendor process: a stand-in ``claude`` prints
    what Claude Code 2.1.300 prints with WT_SESSION set, hyperlink and
    unfinished paste prompt included, and the service hands the link on."""
    make_profile(paths, "claude", "Personal", token=False)
    script = fake_vendor("claude")
    visit = CLAUDE_LINE.format(HYPERLINK.format(CLAUDE_ACCOUNT))
    as_printf = visit.replace("\x1b", "\\033").replace("\x07", "\\007")
    script.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' 'Opening browser to sign in...'\n"
        f"printf '%b\\n' {shlex.quote(as_printf)}\n"
        "printf '%s' 'Paste code here if prompted > '\n"
        "exit 1\n", encoding="utf-8")
    service = ShamblesService(paths=paths,
                              providers=providers.all_providers(env={}),
                              platform="linux")
    lines = []

    handle = service.start_login("claude", "Personal", on_line=lines.append,
                                 on_done=lambda result: None)

    assert handle.wait(timeout=10)
    assert CLAUDE_ACCOUNT in [service.sign_in_url(line) for line in lines]
