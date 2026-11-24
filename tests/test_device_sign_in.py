"""Codex's sign-in with a one-time code, for a browser on another device.

``codex login --device-auth`` prints a link and a short code, then polls
OpenAI until someone enters that code at the link, from any device, for up to
15 minutes. Nothing has to reach back to this machine, which is what makes it
work where the browser sign-in cannot.

The output below is ``device_code_prompt`` from openai/codex at rust-v0.169.0
(``codex-rs/login/src/device_code_auth.rs``), byte for byte. Codex colours it
with ANSI codes whether or not it is writing to a terminal, so the link and
the code each arrive wrapped in escapes. The failure lines are
``finish_login`` in ``codex-rs/cli/src/login.rs``.
"""

import json
import sys
import textwrap

import pytest

from conftest import posix_only
from helpers import healthy_ms, make_live_codex_login, make_profile
from shambles import login, providers, state
from shambles.app.service import HIDDEN_LINE, DeviceSignIn, ShamblesService

NOW = 1_800_000_000_000
LINK = "https://auth.openai.com/codex/device"
USER_CODE = "CODE-12345"

BLUE, GRAY, RESET = "\x1b[94m", "\x1b[90m", "\x1b[0m"

#: What ``println!("{prompt}")`` writes, split into the lines Shambles reads.
CODEX_DEVICE_OUTPUT = (
    f"\nWelcome to Codex [v{GRAY}0.169.0{RESET}]\n"
    f"{GRAY}OpenAI's command-line coding agent{RESET}\n"
    "\nFollow these steps to sign in with ChatGPT using device code "
    "authorization:\n"
    "\n1. Open this link in your browser and sign in to your account\n"
    f"   {BLUE}{LINK}{RESET}\n"
    f"\n2. Enter this one-time code {GRAY}(expires in 15 minutes){RESET}\n"
    f"   {BLUE}{USER_CODE}{RESET}\n"
    f"\n{GRAY}Continue only if you started this login in Codex. If a website "
    f"or another person gave you this code, cancel.{RESET}\n"
    "\n"
).split("\n")

NOT_ENABLED = ("Error logging in: device code login is not enabled for this "
               "Codex server. Use the browser login or verify the server URL.")
TIMED_OUT = "Error logging in: device auth timed out after 15 minutes"
OTHER_FAILURE = ("Error logging in: device auth failed with status 500 "
                 "Internal Server Error")


@pytest.fixture
def codex():
    return providers.load("codex")


@pytest.fixture
def claude():
    return providers.load("claude")


# -- what the spec says -----------------------------------------------------


def test_only_codex_offers_a_code_for_another_device(codex, claude):
    assert login.accepts_device_auth(codex) is True
    assert login.accepts_device_auth(claude) is False


def test_the_device_command_adds_codex_s_own_flag(codex):
    assert login.command(codex, device=True) == ["codex", "login",
                                                 "--device-auth"]
    assert login.command(codex) == ["codex", "login"]


def test_asking_claude_for_a_device_command_is_refused(claude):
    with pytest.raises(login.LoginUnavailableError) as caught:
        login.command(claude, device=True)
    assert str(caught.value).endswith(".")


# -- reading the code out of Codex's output ---------------------------------


def test_escape_sequences_are_stripped():
    assert login.plain(f"   {BLUE}{LINK}{RESET}") == f"   {LINK}"
    hyperlink = f"\x1b]8;;{LINK}\x07{LINK}\x1b]8;;\x07"
    assert login.plain(hyperlink) == LINK


def test_the_link_and_code_are_read_from_codex_s_real_output(codex):
    reader = login.DeviceCodeReader(codex)
    found = [reader.feed(line) for line in CODEX_DEVICE_OUTPUT]
    offers = [item for item in found if item is not None]

    assert offers == [login.DeviceCode(user_code=USER_CODE,
                                       verification_url=LINK,
                                       expires_in_s=900)]


def test_the_same_output_without_colour_reads_the_same(codex):
    reader = login.DeviceCodeReader(codex)
    offers = [reader.feed(login.plain(line)) for line in CODEX_DEVICE_OUTPUT]
    assert [o for o in offers if o] == [
        login.DeviceCode(USER_CODE, LINK, 900)]


def test_a_code_shaped_line_before_the_link_is_not_the_code(codex):
    reader = login.DeviceCodeReader(codex)
    assert reader.feed("ABCD-EFGH") is None
    assert reader.feed(f"   {LINK}") is None
    assert reader.feed("   WXYZ-1234") == login.DeviceCode(
        "WXYZ-1234", LINK, 900)


@pytest.mark.parametrize("link", [
    "https://auth.openai.com.example.test/codex/device",
    "https://example.test/codex/device",
    "http://auth.openai.com/codex/device",
    f"{LINK}?next=https://example.test",
    f"{LINK} and more",
])
def test_only_codex_s_own_link_starts_the_search(codex, link):
    """The link is offered as something to open, so it must be the one."""
    reader = login.DeviceCodeReader(codex)
    assert reader.feed(link) is None
    assert reader.feed(USER_CODE) is None


@pytest.mark.parametrize("line", [
    "CODE-12345 extra",
    "code: CODE-12345",
    "CODE_12345",
    "CODE-12345-ABCD-EFGH-IJKL",
    "A" * 40,
    "CODE-1234\x00",
    "",
])
def test_anything_but_a_bare_code_after_the_link_is_skipped(codex, line):
    reader = login.DeviceCodeReader(codex)
    reader.feed(LINK)
    assert reader.feed(line) is None
    # The real code can still follow.
    assert reader.feed(USER_CODE) == login.DeviceCode(USER_CODE, LINK, 900)


def test_the_code_is_reported_once(codex):
    reader = login.DeviceCodeReader(codex)
    reader.feed(LINK)
    assert reader.feed(USER_CODE) is not None
    assert reader.feed("WXYZ-1234") is None


def test_a_provider_without_device_codes_has_no_reader(claude):
    with pytest.raises(login.LoginUnavailableError):
        login.DeviceCodeReader(claude)


@pytest.mark.parametrize("line, key", [
    (NOT_ENABLED, "unavailable"),
    (f"{GRAY}{NOT_ENABLED}{RESET}", "unavailable"),
    (TIMED_OUT, "expired"),
    ("ChatGPT login is disabled. Use API key login instead.",
     "chatgpt_disabled"),
    (OTHER_FAILURE, None),
    ("Successfully logged in", None),
    ("", None),
])
def test_codex_s_fixed_failure_messages_are_recognised(codex, line, key):
    assert login.known_message(codex, line) == key


# -- through the service ----------------------------------------------------


def service(paths):
    return ShamblesService(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux", clock_ms=lambda: NOW)


@pytest.fixture
def scripted(monkeypatch):
    """The vendor replaced by a process that replays given output."""
    runs = []

    class ScriptedLoginProcess:
        running = False

        def __init__(self, argv, **kwargs):
            self.argv = list(argv)
            runs.append(self)

        def start(self, *, on_line, on_exit):
            self.running = True
            self.on_line, self.on_exit = on_line, on_exit

        def replay(self, lines, code):
            for line in lines:
                self.on_line(line)
            self.running = False
            self.on_exit(code)

        def cancel(self):
            if self.running:
                self.running = False
                self.on_exit(-15)

    monkeypatch.setattr("shambles.app.service.login.LoginProcess",
                        ScriptedLoginProcess)
    monkeypatch.setattr("shambles.app.service.login.available",
                        lambda provider: True)
    return runs


def _sign_in(paths, provider_id="codex", **kwargs):
    make_profile(paths, provider_id, "Personal", token=False)
    lines, offers, done = [], [], []
    handle = service(paths).start_login(
        provider_id, "Personal", lines.append, done.append,
        on_device_code=offers.append, **kwargs)
    return handle, lines, offers, done


def test_the_service_says_which_providers_offer_it(paths):
    assert service(paths).offers_device_sign_in("codex") is True
    assert service(paths).offers_device_sign_in("claude") is False


def test_a_device_sign_in_runs_codex_with_its_flag(paths, scripted):
    _sign_in(paths, device=True)
    assert scripted[-1].argv == ["codex", "login", "--device-auth"]


def test_a_browser_sign_in_is_unchanged(paths, scripted):
    _, lines, offers, _ = _sign_in(paths)
    assert scripted[-1].argv == ["codex", "login"]
    scripted[-1].replay(CODEX_DEVICE_OUTPUT, 1)
    # Not asked for, so not looked for.
    assert offers == []


def test_the_code_and_link_arrive_once_with_their_deadline(paths, scripted):
    _, lines, offers, _ = _sign_in(paths, device=True)

    scripted[-1].replay(CODEX_DEVICE_OUTPUT, 1)

    assert offers == [DeviceSignIn(user_code=USER_CODE,
                                   verification_url=LINK,
                                   expires_at_ms=NOW + 900_000)]
    # As progress, the same lines stay hidden: the code is shown where it
    # is meant to be, not echoed as output.
    assert set(lines) == {HIDDEN_LINE}


def test_a_failing_device_callback_does_not_stop_the_sign_in(paths, scripted):
    make_profile(paths, "codex", "Personal", token=False)
    done = []

    def broken(_offer):
        raise RuntimeError("window closed")

    handle = service(paths).start_login("codex", "Personal", lambda line: None,
                                        done.append, device=True,
                                        on_device_code=broken)
    scripted[-1].replay(CODEX_DEVICE_OUTPUT, 1)
    assert handle.wait(timeout=5)
    assert done and done[0].ok is False


def test_codex_saying_device_codes_are_off_is_shown_with_the_setting(
        paths, scripted):
    _, _, _, done = _sign_in(paths, device=True)

    scripted[-1].replay(CODEX_DEVICE_OUTPUT + [NOT_ENABLED], 1)

    error = done[0].error
    assert error.code == "login_failed"
    assert "device code login is not enabled" in error.message
    assert "ChatGPT security settings" in error.recovery
    # The account is still put back, as for any failed sign-in.
    assert "Personal" in error.recovery


def test_an_expired_code_says_so_without_blaming_the_setting(paths, scripted):
    _, _, _, done = _sign_in(paths, device=True)

    scripted[-1].replay(CODEX_DEVICE_OUTPUT + [TIMED_OUT], 1)

    error = done[0].error
    assert error.code == "login_failed"
    assert "expired" in error.message
    assert "security settings" not in error.recovery


def test_an_unknown_failure_points_to_the_setting_and_forwards_nothing(
        paths, scripted):
    _, _, _, done = _sign_in(paths, device=True)

    scripted[-1].replay(CODEX_DEVICE_OUTPUT + [OTHER_FAILURE], 1)

    error = done[0].error
    assert error.code == "login_failed"
    assert "ChatGPT security settings" in error.recovery
    wire = repr(done[0].to_dict())
    assert "status 500" not in wire
    assert USER_CODE not in wire


def test_a_cancelled_device_sign_in_is_an_ordinary_cancel(paths, scripted):
    handle, _, _, done = _sign_in(paths, device=True)
    handle.cancel()
    assert handle.wait(timeout=5)
    assert done[0].error.code == "login_cancelled"
    assert "security settings" not in done[0].error.recovery


def test_adding_an_account_can_use_a_device_code(paths, scripted):
    make_profile(paths, "codex", "Main", token=False)
    offers = []
    service(paths).start_add("codex", "Spare", lambda line: None,
                             lambda result: None, device=True,
                             on_device_code=offers.append)
    assert scripted[-1].argv == ["codex", "login", "--device-auth"]
    scripted[-1].replay(CODEX_DEVICE_OUTPUT, 1)
    assert [o.user_code for o in offers] == [USER_CODE]


def test_claude_refuses_a_device_sign_in_before_anything_moves(
        paths, scripted):
    make_profile(paths, "claude", "Personal", token=False)
    make_profile(paths, "claude", "Work", token=False, active=True)
    done = []

    handle = service(paths).start_login("claude", "Personal",
                                        lambda line: None, done.append,
                                        device=True)

    assert handle.wait(timeout=5)
    assert done[0].ok is False
    assert done[0].error.code == "device_sign_in_unavailable"
    assert scripted == [], "no vendor process may start"
    assert state.read_active(paths, "claude") == "Work"


@posix_only
def test_end_to_end_with_a_codex_stand_in_on_path(paths, fake_vendor,
                                                  tmp_path):
    """A real process named ``codex`` that prints exactly what Codex does."""
    script = fake_vendor("codex")
    script.write_text(textwrap.dedent(f"""\
        #!{sys.executable}
        import sys
        if sys.argv[1:] != ["login", "--device-auth"]:
            sys.exit(9)
        sys.stdout.write({chr(10).join(CODEX_DEVICE_OUTPUT)!r})
        sys.stdout.flush()
        sys.stderr.write({NOT_ENABLED!r} + "\\n")
        sys.exit(1)
    """), encoding="utf-8")
    make_profile(paths, "codex", "Personal", token=False)
    lines, offers, done = [], [], []

    handle = service(paths).start_login("codex", "Personal", lines.append,
                                        done.append, device=True,
                                        on_device_code=offers.append)

    assert handle.wait(timeout=10)
    assert [o.user_code for o in offers] == [USER_CODE]
    assert [o.verification_url for o in offers] == [LINK]
    assert set(lines) == {HIDDEN_LINE}
    assert "device code login is not enabled" in done[0].error.message


# -- with D11: switching method keeps a renewal a renewal ----------------------


@pytest.fixture
def deferred(monkeypatch):
    """The vendor, finished or cancelled by the test. Disk stays real."""
    runs = []

    class Deferred:
        running = False

        def __init__(self, argv, **kwargs):
            self.argv = list(argv)
            runs.append(self)

        def start(self, *, on_line, on_exit):
            self.running = True
            self.on_exit = on_exit

        def finish(self, code=0):
            self.running = False
            self.on_exit(code)

        def cancel(self):
            if self.running:
                self.finish(-15)

    monkeypatch.setattr("shambles.app.service.login.LoginProcess", Deferred)
    monkeypatch.setattr("shambles.app.service.login.available",
                        lambda provider: True)
    return runs


def _real_clock_service(paths):
    # Liveness is judged against the real clock (see helpers.healthy_ms).
    return ShamblesService(paths=paths,
                           providers=providers.all_providers(env={}),
                           platform="linux")


def _cancelled_then_device(paths, deferred, name, *, adding):
    """What the window does on "Another device": cancel, settle, restart."""
    app = _real_clock_service(paths)
    first = []
    start = app.start_add if adding else app.start_login
    handle = start("codex", name, lambda line: None, first.append)
    handle.cancel()
    assert handle.wait(timeout=10)
    assert first[0].error.code == "login_cancelled"
    assert state.read_active(paths, "codex") == "Main"

    done = []
    handle = app.start_login("codex", name, lambda line: None, done.append,
                             device=True)
    assert deferred[-1].argv[-1] == "--device-auth"
    live = make_live_codex_login(paths, email=f"{name.lower()}@example.test",
                                 exp_ms=healthy_ms(30))
    # A new sign-in, not the old login refreshed: a refresh token of its own
    # (as in test_switch's test_a_codex_sign_in_again_to_the_same_account).
    fresh = json.loads(live.read_text())
    fresh["tokens"]["refresh_token"] = "r-signed-in-on-another-device"
    live.write_text(json.dumps(fresh))
    deferred[-1].finish(0)
    assert handle.wait(timeout=10)
    return done[0]


def _main_live(paths):
    make_profile(paths, "codex", "Main", email="main@example.test",
                 active=True)
    make_live_codex_login(paths, email="main@example.test")


def test_a_renewal_restarted_on_another_device_still_puts_you_back(
        paths, deferred):
    _main_live(paths)
    make_profile(paths, "codex", "Spare", email="spare@example.test")

    result = _cancelled_then_device(paths, deferred, "Spare", adding=False)

    assert result.ok, result.error
    assert state.read_active(paths, "codex") == "Main"
    assert "You're still on Main" in result.summary


def test_an_add_restarted_on_another_device_ends_on_the_new_account(
        paths, deferred):
    """Its account has no login yet, so the restart is no renewal."""
    _main_live(paths)

    result = _cancelled_then_device(paths, deferred, "Third", adding=True)

    assert result.ok, result.error
    assert state.read_active(paths, "codex") == "Third"
