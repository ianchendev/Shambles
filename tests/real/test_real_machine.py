"""Shambles against a real Keychain, a real Credential Manager, and the
vendors' own programs.

Everything else in this suite runs against fakes, because it has to run on a
developer's machine without touching their logins. That leaves one question
the fakes cannot answer: is the place Shambles writes the place the vendor
reads? Getting it wrong is the worst failure this tool has -- a switch that
reports success, shows the new account's name, and leaves the old token live.

So this file runs **only on disposable CI runners**, with made-up credentials,
and lets the vendor be the judge. ``claude auth status`` and ``codex login
status`` are asked who is signed in after each switch; they read their own
stores with their own code.

Two switches keep it away from real machines:

* ``SHAMBLES_REAL_MACHINE=1`` must be set, and
* ``GITHUB_ACTIONS`` must be ``true``.

And one check inside: any test that uses the vendor's real location refuses
to start if a login is already there.

The vendors' programs are run with their network pointed at a dead local
port. Nothing here needs a server, the tokens are not real, and a result
that only holds offline is a result about local storage, which is the point.
"""

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

from shambles import providers
from shambles.paths import Paths
from shambles.stores import (CredmanStore, FallbackStore, FileStore,
                             KeychainStore)
from shambles.stores.base import StoreUnavailableError
from tests.contract.test_store_contract import PAYLOADS

REAL = (os.environ.get("SHAMBLES_REAL_MACHINE") == "1"
        and os.environ.get("GITHUB_ACTIONS") == "true")

pytestmark = pytest.mark.skipif(
    not REAL,
    reason="writes to the real Keychain / Credential Manager; runs only on "
           "disposable CI runners (SHAMBLES_REAL_MACHINE=1 under GitHub "
           "Actions)")

#: When set, a vendor CLI that is missing fails the run instead of skipping.
#: CI sets it, so a broken install step cannot quietly turn the vendor checks
#: into a row of skips that reads as a pass.
REQUIRE_VENDORS = os.environ.get("SHAMBLES_REQUIRE_VENDORS") == "1"

DEAD_PROXY = "http://127.0.0.1:9"

#: Anything that would make a vendor CLI authenticate from somewhere other
#: than its stored login. With one of these set, the status command reports
#: on the variable and says nothing about the store.
AUTH_OVERRIDES = (
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_PROFILE",
    "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
    "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
    "CODEX_ACCESS_TOKEN", "CODEX_API_KEY", "OPENAI_API_KEY",
    "OPENAI_FEDERATION_RULE_ID", "OPENAI_IDENTITY_TOKEN_FILE",
)

DAY_MS = 86_400_000


# -- running things ---------------------------------------------------------


def base_env(**extra) -> dict:
    env = {k: v for k, v in os.environ.items() if k not in AUTH_OVERRIDES}
    env.update(extra)
    return env


def vendor_env(**extra) -> dict:
    """An environment in which a vendor CLI can reach nothing but this box."""
    return base_env(
        HTTPS_PROXY=DEAD_PROXY, HTTP_PROXY=DEAD_PROXY,
        https_proxy=DEAD_PROXY, http_proxy=DEAD_PROXY,
        NO_PROXY="", no_proxy="",
        DISABLE_AUTOUPDATER="1", DISABLE_TELEMETRY="1",
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC="1",
        **extra)


def shambles(*args, env=None) -> subprocess.CompletedProcess:
    """Run Shambles the way a user would: the built binary when the job has
    one, the source tree otherwise."""
    binary = os.environ.get("SHAMBLES_BIN")
    argv = [binary] if binary else [sys.executable, "-m", "shambles"]
    done = subprocess.run([*argv, *args], capture_output=True, text=True,
                          encoding="utf-8", env=env or base_env(), timeout=180)
    print(f"$ shambles {' '.join(args)}  -> exit {done.returncode}")
    if done.stdout.strip():
        print(done.stdout.strip())
    if done.stderr.strip():
        print("stderr:", done.stderr.strip())
    return done


def vendor(name):
    path = shutil.which(name)
    if path is None:
        message = f"{name} is not installed on this runner"
        if REQUIRE_VENDORS:
            pytest.fail(message)
        pytest.skip(message)
    return path


def run_vendor(argv, *, env, stdin=None) -> subprocess.CompletedProcess:
    done = subprocess.run(argv, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=env,
                          input=stdin, timeout=180)
    print(f"$ {Path(argv[0]).name} {' '.join(argv[1:])}  -> exit {done.returncode}")
    if done.stdout.strip():
        print("stdout:", done.stdout.strip())
    if done.stderr.strip():
        print("stderr:", done.stderr.strip()[:2000])
    return done


def claude_status(env):
    """``(signed in, parsed JSON)`` as Claude Code itself reports it."""
    done = run_vendor([vendor("claude"), "auth", "status"], env=env)
    try:
        data = json.loads(done.stdout)
    except ValueError:
        data = {}
    return done.returncode == 0, data


def codex_status(env):
    """``(signed in, what it said)`` as Codex itself reports it."""
    done = run_vendor([vendor("codex"), "login", "status"], env=env)
    return done.returncode == 0, (done.stderr + done.stdout).strip()


# -- made-up logins -----------------------------------------------------------


def claude_blob(tag: str, *, padding: int = 0) -> bytes:
    """A Claude credential that is well-formed and obviously not real.

    ``padding`` adds an MCP entry of that many characters, which is how a
    real login grows past one Credential Manager entry and past what
    ``security -i`` reads from standard input.
    """
    now = int(time.time() * 1000)
    data = {
        "claudeAiOauth": {
            "accessToken": f"sk-ant-oat01-shambles-ci-{tag}-not-a-real-token",
            "refreshToken": f"sk-ant-ort01-shambles-ci-{tag}-not-a-real-token",
            "expiresAt": now + 300 * DAY_MS,
            "refreshTokenExpiresAt": now + 300 * DAY_MS,
            "scopes": ["user:inference", "user:profile",
                       "user:sessions:claude_code", "user:mcp_servers"],
            "subscriptionType": "max",
            "rateLimitTier": "default_claude_max_5x",
        },
    }
    if padding:
        data["mcpOAuth"] = {"ci-server|0000": {
            "serverName": "ci-server", "accessToken": "p" * padding}}
    return json.dumps(data, separators=(",", ":")).encode("utf-8")


def claude_account(tag: str) -> dict:
    return {
        "emailAddress": f"{tag}@example.test",
        "displayName": f"CI {tag}",
        "organizationName": f"Example {tag}",
        "accountUuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{tag}.example.test")),
        "organizationUuid": str(uuid.uuid5(uuid.NAMESPACE_DNS, f"org.{tag}.example.test")),
        "organizationRateLimitTier": "default_claude_max_5x",
    }


def _jwt(claims: dict) -> str:
    import base64

    def segment(payload):
        raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    return f'{segment({"alg": "none", "typ": "JWT"})}.{segment(claims)}.c2ln'


def codex_blob(tag: str) -> bytes:
    """A Codex ``auth.json`` under ChatGPT sign-in, obviously not real."""
    exp = int(time.time()) + 9 * 86_400
    profile = {"email": f"{tag}@example.test", "name": f"CI {tag}"}
    auth = {"chatgpt_plan_type": "plus",
            "chatgpt_account_id": f"acct-{tag}",
            "chatgpt_user_id": f"user-{tag}",
            "organizations": [{"id": f"org-{tag}", "title": f"Example {tag}",
                               "is_default": True, "role": "owner"}]}
    data = {
        "auth_mode": "chatgpt",
        "OPENAI_API_KEY": None,
        "tokens": {
            "id_token": _jwt({"exp": exp, "email": profile["email"],
                              "https://api.openai.com/profile": profile,
                              "https://api.openai.com/auth": auth}),
            "access_token": _jwt({"exp": exp,
                                  "https://api.openai.com/auth": auth}),
            "refresh_token": f"rt-shambles-ci-{tag}-not-a-real-token",
            "account_id": f"acct-{tag}",
        },
        "last_refresh": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return json.dumps(data, indent=2).encode("utf-8")


# -- the machine itself -------------------------------------------------------


def test_report_where_this_ran():
    """Not a check. A record, so a green run says what it was green *on*."""
    print("platform:", platform.platform())
    print("machine:", platform.machine(), "| python:", sys.version.split()[0])
    if sys.platform == "darwin":
        print("macOS:", platform.mac_ver()[0])
    if sys.platform == "win32":
        print("windows:", platform.win32_ver())
    print("home:", "ascii" if str(Path.home()).isascii() else "non-ascii",
          "| has spaces:", " " in str(Path.home()))
    print("shambles under test:", os.environ.get("SHAMBLES_BIN") or "source")
    print(shambles("--version").stdout.strip())
    for name in ("claude", "codex", "bun"):
        path = shutil.which(name)
        if path:
            done = subprocess.run([path, "--version"], capture_output=True,
                                  text=True, env=vendor_env(), timeout=120)
            print(f"{name}:", (done.stdout or done.stderr).strip().splitlines()[0])
        else:
            print(f"{name}: not installed")


# -- 1. the native store, under a name nothing else uses ----------------------


@pytest.fixture
def native_store(tmp_path):
    """This platform's real store, under a throwaway name."""
    tag = uuid.uuid4().hex[:12]
    if sys.platform == "darwin":
        store = KeychainStore(service=f"Shambles CI {tag}-credentials",
                              account=os.environ.get("USER", "runner"))
    elif sys.platform == "win32":
        store = CredmanStore(service=f"Shambles CI {tag}-credentials",
                             account="claude-code-user")
    else:
        store = FileStore(tmp_path / "näme with spaces" / ".credentials.json")
    yield store
    store.delete()


@pytest.mark.parametrize("payload", PAYLOADS.values(), ids=list(PAYLOADS))
def test_the_real_store_returns_exactly_what_it_was_given(native_store, payload):
    """Write, read back byte for byte, replace, remove."""
    assert native_store.read() is None
    native_store.write(payload)
    assert native_store.read() == payload
    native_store.write(b'{"replaced":true}')
    assert native_store.read() == b'{"replaced":true}'
    native_store.write(payload)
    assert native_store.read() == payload
    native_store.delete()
    assert native_store.read() is None
    native_store.delete()  # removing what is not there is not an error


# -- 2. the vendor's own storage calls, without the vendor --------------------

darwin_only = pytest.mark.skipif(sys.platform != "darwin",
                                 reason="the macOS Keychain")
windows_only = pytest.mark.skipif(sys.platform != "win32",
                                  reason="the Windows Credential Manager")


@darwin_only
@pytest.mark.parametrize("payload", [PAYLOADS["plain json"], PAYLOADS["unicode"],
                                     claude_blob("vendor-write")],
                         ids=["plain", "unicode", "login"])
def test_shambles_reads_what_claude_codes_keychain_command_writes(
        native_store, payload):
    """The exact command line in the 2.1.322 binary, fed on standard input."""
    line = (f'add-generic-password -U -a "{native_store.account}" '
            f'-s "{native_store.service}" -X "{payload.hex()}"\n')
    done = subprocess.run(["security", "-i"], input=line.encode(),
                          capture_output=True, timeout=60)
    print("security -i exit", done.returncode, done.stderr.decode()[:300])
    assert native_store.read() == payload


@darwin_only
def test_claude_codes_keychain_command_reads_what_shambles_writes(native_store):
    """Its reader is ``security find-generic-password -a .. -w -s ..``, the
    output trimmed and parsed as JSON."""
    payload = claude_blob("vendor-read")
    native_store.write(payload)
    done = subprocess.run(
        ["security", "find-generic-password", "-a", native_store.account,
         "-w", "-s", native_store.service], capture_output=True, timeout=60)
    assert done.returncode == 0
    assert json.loads(done.stdout.decode().strip()) == json.loads(payload)


@darwin_only
def test_what_security_does_when_a_command_on_stdin_fails(native_store):
    """A record of the tool's behaviour that the write path leans on.

    The write goes through ``security -i`` and is then read back, because
    this is not a tool to trust on its exit status alone. Printed so the
    run log says what the status actually was on this version of macOS.
    """
    done = subprocess.run(
        ["security", "-i"], capture_output=True, timeout=60,
        input=b'find-generic-password -a "nobody" -s "Shambles CI no such item"\n')
    print("failed command on stdin -> exit", done.returncode,
          "| stderr:", done.stderr.decode().strip()[:200])
    missing = subprocess.run(
        ["security", "find-generic-password", "-a", "nobody", "-w",
         "-s", "Shambles CI no such item"], capture_output=True, timeout=60)
    print("missing item by argument -> exit", missing.returncode,
          "| stderr:", missing.stderr.decode().strip()[:200])
    assert missing.returncode == 44


def _bun_script():
    bun = shutil.which("bun")
    if bun is None:
        if REQUIRE_VENDORS:
            pytest.fail("bun is not installed on this runner")
        pytest.skip("bun is not installed on this runner")
    return bun, str(Path(__file__).with_name("vendor_credman.mjs"))


@windows_only
@pytest.mark.parametrize("size", [0, 3000, 20000], ids=["small", "split", "large"])
def test_shambles_reads_what_claude_codes_credman_code_writes(
        native_store, tmp_path, size):
    """``Bun.secrets`` is the API Claude Code calls; the script restates its
    writer. One entry for a small login, base64 pieces for a large one.

    The vendor's writer stores its pieces concurrently. Whether every piece
    then exists is checked with the vendor's *own* reader first: if that
    cannot read the result back, the pieces were lost before Shambles was
    involved, and the honest outcome is "the vendor's writer failed", not a
    verdict on Shambles in either direction.
    """
    bun, script = _bun_script()
    payload = claude_blob("vendor-write", padding=size)
    source = tmp_path / "in.json"
    source.write_bytes(payload)
    done = run_vendor([bun, script, "set", native_store.service,
                       native_store.account, str(source)], env=base_env())
    assert done.returncode == 0

    echo = tmp_path / "echo.json"
    own = run_vendor([bun, script, "get", native_store.service,
                      native_store.account, str(echo)], env=base_env())
    if own.returncode != 0 or echo.read_bytes() != payload:
        api = native_store._api()
        present = [index for index in range(64)
                   if api.read(native_store._target(f"#{index}")) is not None]
        print("pieces present after the vendor's write:", present,
              "| count entry:", api.read(native_store._target("#m")))
        pytest.xfail(
            "Bun.secrets did not keep every piece its own writer stored, and "
            "its own reader cannot read the result. Not a Shambles result.")
    assert native_store.read() == payload


@windows_only
@pytest.mark.parametrize("size", [0, 3000, 20000], ids=["small", "split", "large"])
def test_claude_codes_credman_code_reads_what_shambles_writes(
        native_store, tmp_path, size):
    bun, script = _bun_script()
    payload = claude_blob("vendor-read", padding=size)
    native_store.write(payload)
    out = tmp_path / "out.json"
    done = run_vendor([bun, script, "get", native_store.service,
                       native_store.account, str(out)], env=base_env())
    assert done.returncode == 0
    assert out.read_bytes() == payload


@windows_only
def test_claude_codes_credman_code_finds_nothing_after_shambles_deletes(
        native_store, tmp_path):
    bun, script = _bun_script()
    native_store.write(claude_blob("vendor-delete", padding=6000))
    native_store.delete()
    done = run_vendor([bun, script, "get", native_store.service,
                       native_store.account, str(tmp_path / "out.json")],
                      env=base_env())
    assert done.returncode == 3


# -- 3. a whole switch, in the vendor's real location -------------------------


class Machine:
    """One provider on this runner, set up with two made-up accounts.

    Uses the runner's real home and the provider's real store. The runner is
    thrown away afterwards; the refusal in ``__init__`` is for the day
    somebody runs this somewhere that is not.
    """

    def __init__(self, provider_id, blobs, *, env=None, accounts=None,
                 home=None):
        self.env = dict(env or {})
        if home is not None:
            # What a relocated or oddly named home looks like to a program:
            # the variable its runtime asks for the home directory.
            self.env["USERPROFILE" if sys.platform == "win32" else "HOME"] = str(home)
        self.provider = providers.load(provider_id,
                                       env=base_env(**self.env))
        self.home = Path(home) if home is not None else Path.home()
        self.paths = Paths.for_home(self.home)
        self.blobs = blobs
        self.accounts = accounts or {}
        existing = self.store().read()
        if existing is not None:
            pytest.fail(
                f"{self.store().describe()} already holds a login. This "
                "suite only runs where there is none to lose.")
        if self.paths.provider_dir(provider_id).exists():
            pytest.fail(f"{self.paths.provider_dir(provider_id)} already exists.")

    def store(self):
        """A fresh store each time, so nothing read is a cached answer."""
        return self.provider.store(home=self.home, platform=sys.platform)

    def seed(self, active):
        """Save every account as a profile and sign ``active`` in."""
        for name, blob in self.blobs.items():
            self.paths.ensure_profile(self.provider.id, name)
            FileStore(self.paths.credentials(self.provider.id, name)).write(blob)
            if name in self.accounts:
                self.paths.account(self.provider.id, name).write_text(
                    json.dumps({"oauthAccount": self.accounts[name],
                                "stashed_at": int(time.time() * 1000)}),
                    encoding="utf-8")
        self.store().write(self.blobs[active])
        if active in self.accounts:
            self.paths.claude_json.write_text(json.dumps({
                "numStartups": 7, "hasCompletedOnboarding": True,
                "oauthAccount": self.accounts[active],
                "projects": {"/ci/kept": {"allowedTools": ["kept"]}},
            }, indent=2), encoding="utf-8")
        self.paths.active_marker(self.provider.id).write_text(
            active + "\n", encoding="utf-8")

    def stashed(self, name) -> bytes:
        return self.paths.credentials(self.provider.id, name).read_bytes()

    def run(self, *args, without=()):
        env = base_env(**self.env)
        for name in without:
            env.pop(name, None)
        return shambles(*args, env=env)

    def listed(self) -> dict:
        done = self.run("list", "--json")
        assert done.returncode == 0, done.stderr
        payload = json.loads(done.stdout)
        group = next(g for g in payload["groups"]
                     if g["provider"] == self.provider.id)
        return {a["name"]: a for a in group["accounts"]}

    def switch(self, name, **kwargs):
        done = self.run("switch", self.provider.id, name, "--json", **kwargs)
        assert done.returncode == 0, done.stdout + done.stderr
        assert json.loads(done.stdout)["ok"] is True

    def cleanup(self):
        for step in (self.store().delete,
                     lambda: shutil.rmtree(self.paths.library_dir,
                                           ignore_errors=True)):
            try:
                step()
            except StoreUnavailableError as exc:
                print("cleanup:", exc)
        if self.provider.id == "claude":
            self.paths.claude_json.unlink(missing_ok=True)


@pytest.fixture
def machine():
    made = []

    def build(*args, **kwargs):
        made.append(Machine(*args, **kwargs))
        return made[-1]

    yield build
    for one in made:
        one.cleanup()


CLAUDE_MODES = [pytest.param({}, id="default")]
if sys.platform == "win32":
    CLAUDE_MODES.append(pytest.param(
        {"CLAUDE_CODE_FORCE_WINDOWS_CREDMAN": "1"}, id="credman forced"))


@pytest.mark.parametrize("env", CLAUDE_MODES)
@pytest.mark.parametrize("padding", [0, 6000], ids=["plain login", "large login"])
def test_switching_claude_changes_who_claude_code_says_is_signed_in(
        machine, env, padding):
    """The whole point, judged by the vendor.

    Two accounts. Switch to the second, ask Claude Code who is signed in;
    switch back, ask again; clear the login, ask a third time. At each step
    the live store must hold the incoming account's bytes exactly and the
    outgoing account's saved copy must be untouched.
    """
    blobs = {"CI-A": claude_blob("a", padding=padding),
             "CI-B": claude_blob("b", padding=padding)}
    accounts = {"CI-A": claude_account("a"), "CI-B": claude_account("b")}
    box = machine("claude", blobs, env=env, accounts=accounts)
    status_env = vendor_env(**env)
    print("store:", box.store().describe())

    signed_in, _ = claude_status(status_env)
    assert not signed_in, "a clean runner must start signed out"

    box.seed("CI-A")
    assert box.store().read() == blobs["CI-A"]
    listed = box.listed()
    assert listed["CI-A"]["active"] and not listed["CI-B"]["active"]
    assert listed["CI-A"]["email"] == "a@example.test"

    signed_in, said = claude_status(status_env)
    assert signed_in, "Claude Code does not see the login Shambles wrote"
    assert said.get("email") == "a@example.test"

    box.switch("CI-B")
    assert box.store().read() == blobs["CI-B"]
    assert box.stashed("CI-A") == blobs["CI-A"]
    assert box.stashed("CI-B") == blobs["CI-B"]
    config = json.loads(box.paths.claude_json.read_text(encoding="utf-8"))
    assert config["oauthAccount"]["emailAddress"] == "b@example.test"
    assert config["projects"] == {"/ci/kept": {"allowedTools": ["kept"]}}
    signed_in, said = claude_status(status_env)
    assert signed_in and said.get("email") == "b@example.test"

    box.switch("CI-A")
    assert box.store().read() == blobs["CI-A"]
    assert box.stashed("CI-A") == blobs["CI-A"]
    assert box.stashed("CI-B") == blobs["CI-B"]
    signed_in, said = claude_status(status_env)
    assert signed_in and said.get("email") == "a@example.test"

    box.store().delete()
    assert box.store().read() is None
    signed_in, _ = claude_status(status_env)
    assert not signed_in, "Claude Code still sees a login Shambles removed"


@windows_only
def test_claude_code_ignores_credential_manager_unless_it_is_switched_on(machine):
    """Why Windows was broken, shown rather than argued.

    A login placed in Credential Manager and nowhere else: on a default
    install Claude Code reports signed out. That is where Shambles used to
    write on Windows, unconditionally.
    """
    blob = claude_blob("credman-only")
    box = machine("claude", {"CI-A": blob}, accounts={"CI-A": claude_account("a")})
    assert isinstance(box.store(), FileStore), "the default must be the file"

    credman = CredmanStore(service="Claude Code-credentials",
                           account="claude-code-user")
    assert credman.read() is None
    credman.write(blob)
    try:
        signed_in, _ = claude_status(vendor_env())
        assert not signed_in, (
            "Claude Code read Credential Manager without being told to. The "
            "rollout has reached this install: revisit the default store.")
        signed_in, _ = claude_status(
            vendor_env(CLAUDE_CODE_FORCE_WINDOWS_CREDMAN="1"))
        assert signed_in, "forced on, Claude Code should read the same entry"
    finally:
        credman.delete()


@windows_only
def test_with_credman_on_a_switch_leaves_no_stale_file_behind(machine):
    """What the vendor does itself: writing into an empty Credential Manager
    clears the file it supersedes, so nothing stale is read later."""
    env = {"CLAUDE_CODE_FORCE_WINDOWS_CREDMAN": "1"}
    blobs = {"CI-A": claude_blob("a"), "CI-B": claude_blob("b")}
    accounts = {"CI-A": claude_account("a"), "CI-B": claude_account("b")}
    box = machine("claude", blobs, env=env, accounts=accounts)
    store = box.store()
    assert isinstance(store, FallbackStore)

    # A login from before Credential Manager was switched on: in the file.
    box.seed("CI-A")
    store.primary.delete()
    store.fallback.write(blobs["CI-A"])
    signed_in, said = claude_status(vendor_env(**env))
    assert signed_in and said.get("email") == "a@example.test"

    box.switch("CI-B")
    assert store.primary.read() == blobs["CI-B"]
    assert store.fallback.read() is None
    assert box.stashed("CI-A") == blobs["CI-A"]
    signed_in, said = claude_status(vendor_env(**env))
    assert signed_in and said.get("email") == "b@example.test"


def test_switching_codex_changes_who_codex_says_is_signed_in(machine):
    blobs = {"CI-A": codex_blob("a"), "CI-B": codex_blob("b")}
    box = machine("codex", blobs)
    print("store:", box.store().describe())

    signed_in, said = codex_status(vendor_env())
    assert not signed_in, f"a clean runner must start signed out: {said}"

    box.seed("CI-A")
    listed = box.listed()
    assert listed["CI-A"]["active"] and listed["CI-A"]["email"] == "a@example.test"
    signed_in, said = codex_status(vendor_env())
    assert signed_in, f"Codex does not see the login Shambles wrote: {said}"

    box.switch("CI-B")
    assert box.store().read() == blobs["CI-B"]
    assert box.stashed("CI-A") == blobs["CI-A"]
    signed_in, said = codex_status(vendor_env())
    assert signed_in, said

    box.switch("CI-A")
    assert box.store().read() == blobs["CI-A"]
    assert box.stashed("CI-B") == blobs["CI-B"]

    box.store().delete()
    signed_in, said = codex_status(vendor_env())
    assert not signed_in, f"Codex still sees a login Shambles removed: {said}"


def test_shambles_reads_the_login_codex_itself_writes(machine):
    """The one direction Claude cannot offer without a real account.

    ``codex login --with-api-key`` stores a login with no browser and no
    server, so the vendor's own writer can be pointed at the default location
    and Shambles asked whether it finds the result there.
    """
    box = machine("codex", {})
    done = run_vendor([vendor("codex"), "login", "--with-api-key"],
                      env=vendor_env(), stdin="sk-shambles-ci-not-a-real-key\n")
    assert done.returncode == 0
    blob = box.store().read()
    assert blob is not None, "Codex wrote its login somewhere Shambles does not look"
    assert json.loads(blob)["OPENAI_API_KEY"] == "sk-shambles-ci-not-a-real-key"


# -- 4. the cases beyond a default install ------------------------------------


@pytest.fixture
def odd_home(tmp_path):
    """A home directory with a space and non-ASCII characters in its name."""
    home = tmp_path / "hôme with spaces 家"
    home.mkdir()
    return home


def test_claude_in_a_home_directory_with_spaces_and_non_ascii_characters(
        machine, odd_home):
    """Windows profile folders are named after people. A store path built by
    string concatenation, or a child process started through a shell, breaks
    on exactly this."""
    blobs = {"CI-A": claude_blob("a"), "CI-B": claude_blob("b")}
    accounts = {"CI-A": claude_account("a"), "CI-B": claude_account("b")}
    box = machine("claude", blobs, accounts=accounts, home=odd_home)
    status_env = vendor_env(**box.env)
    print("store:", box.store().describe())

    box.seed("CI-A")
    signed_in, said = claude_status(status_env)
    assert signed_in and said.get("email") == "a@example.test"
    box.switch("CI-B")
    assert box.store().read() == blobs["CI-B"]
    assert box.stashed("CI-A") == blobs["CI-A"]
    signed_in, said = claude_status(status_env)
    assert signed_in and said.get("email") == "b@example.test"
    assert (odd_home / ".shambles" / "claude" / "active").read_text(
        encoding="utf-8").strip() == "CI-B"


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Codex on Windows asks the system for the profile folder and "
           "ignores USERPROFILE, so the home cannot be relocated for it here")
def test_codex_in_a_home_directory_with_spaces_and_non_ascii_characters(
        machine, odd_home):
    blobs = {"CI-A": codex_blob("a"), "CI-B": codex_blob("b")}
    box = machine("codex", blobs, home=odd_home)
    box.seed("CI-A")
    signed_in, said = codex_status(vendor_env(**box.env))
    assert signed_in, said
    box.switch("CI-B")
    assert box.store().read() == blobs["CI-B"]
    assert (odd_home / ".codex" / "auth.json").read_bytes() == blobs["CI-B"]
    signed_in, said = codex_status(vendor_env(**box.env))
    assert signed_in, said


@pytest.mark.parametrize("trailing", ["", "/"], ids=["plain", "trailing slash"])
def test_claude_with_its_config_directory_moved(machine, tmp_path, trailing):
    """``CLAUDE_CONFIG_DIR`` moves the credentials file, and on macOS renames
    the Keychain item after a hash of the variable *as typed*.

    The trailing slash is the trap: tidy the path before hashing and Shambles
    looks in an item Claude Code never wrote. The vendor is asked, under the
    same environment, whether it sees what Shambles stored.
    """
    config = tmp_path / "claude config"
    config.mkdir()
    env = {"CLAUDE_CONFIG_DIR": str(config) + trailing}
    blobs = {"CI-A": claude_blob("a"), "CI-B": claude_blob("b")}
    box = machine("claude", blobs, env=env)
    print("store:", box.store().describe())

    signed_in, _ = claude_status(vendor_env(**env))
    assert not signed_in
    box.seed("CI-A")
    signed_in, said = claude_status(vendor_env(**env))
    assert signed_in, "Claude Code does not see the login in the moved directory"
    print("claude reports configDirectory:", said.get("configDirectory"))

    box.switch("CI-B")
    assert box.store().read() == blobs["CI-B"]
    assert box.stashed("CI-A") == blobs["CI-A"]
    signed_in, _ = claude_status(vendor_env(**env))
    assert signed_in

    # And a session *without* the variable sees none of it: the two are
    # separate logins, which is why the window shows a banner for this.
    signed_in, _ = claude_status(vendor_env())
    assert not signed_in


def test_codex_with_its_home_moved(machine, tmp_path):
    codex_home = tmp_path / "codex home"
    codex_home.mkdir()
    env = {"CODEX_HOME": str(codex_home)}
    blobs = {"CI-A": codex_blob("a"), "CI-B": codex_blob("b")}
    box = machine("codex", blobs, env=env)
    box.seed("CI-A")
    assert (codex_home / "auth.json").read_bytes() == blobs["CI-A"]
    signed_in, said = codex_status(vendor_env(**env))
    assert signed_in, said
    box.switch("CI-B")
    assert (codex_home / "auth.json").read_bytes() == blobs["CI-B"]
    signed_in, said = codex_status(vendor_env(**env))
    assert signed_in, said


def test_codex_told_to_use_the_keyring_is_refused_and_nothing_is_written(
        machine, tmp_path):
    """Codex in keyring mode does not read ``auth.json``.

    Shown from both sides. First the premise, with the vendor as judge: a
    perfectly good ``auth.json`` is on disk and Codex says "Not logged in".
    Then the consequence: Shambles refuses to switch, says why, and leaves
    every file as it found it.
    """
    codex_home = tmp_path / "codex-keyring"
    codex_home.mkdir()
    env = {"CODEX_HOME": str(codex_home)}
    blobs = {"CI-A": codex_blob("a"), "CI-B": codex_blob("b")}

    # File mode first, so the profiles and the live login exist.
    box = machine("codex", blobs, env=env)
    box.seed("CI-A")
    signed_in, said = codex_status(vendor_env(**env))
    assert signed_in, said

    (codex_home / "config.toml").write_text(
        'cli_auth_credentials_store = "keyring"\n', encoding="utf-8")
    signed_in, said = codex_status(vendor_env(**env))
    print("codex in keyring mode, auth.json present:", signed_in, "|", said)
    assert not signed_in, (
        "Codex read auth.json in keyring mode. The premise of the refusal "
        "below no longer holds: revisit it.")

    done = box.run("switch", "codex", "CI-B", "--json")
    assert done.returncode != 0
    message = json.loads(done.stdout)["error"]["message"]
    assert "keyring" in message and "auth.json" in message
    assert 'cli_auth_credentials_store = "file"' in message
    assert (codex_home / "auth.json").read_bytes() == blobs["CI-A"]
    assert box.stashed("CI-B") == blobs["CI-B"]
    assert box.paths.active_marker("codex").read_text(
        encoding="utf-8").strip() == "CI-A"

    listing = box.run("list", "--json")
    print("list in keyring mode -> exit", listing.returncode)

    # Out of keyring mode again so the fixture can clean up through the store.
    (codex_home / "config.toml").unlink()


@darwin_only
def test_a_mac_signed_in_through_the_file_is_seen_and_then_moved_to_the_keychain(
        machine):
    """Claude Code's macOS backend is the Keychain *with a plaintext fallback*.

    A login made over SSH lands in ``~/.claude/.credentials.json`` because
    the Keychain refuses the write. The vendor reads it from there while the
    Keychain is empty, and so must Shambles. A switch then goes to the
    Keychain and clears the file -- what the vendor's own next write does --
    and the vendor is asked who is signed in after each step.
    """
    blobs = {"CI-A": claude_blob("a"), "CI-B": claude_blob("b")}
    accounts = {"CI-A": claude_account("a"), "CI-B": claude_account("b")}
    box = machine("claude", blobs, accounts=accounts)
    store = box.store()
    assert isinstance(store, FallbackStore)

    box.seed("CI-A")
    store.primary.delete()
    store.fallback.write(blobs["CI-A"])
    assert store.primary.read() is None

    signed_in, said = claude_status(vendor_env())
    assert signed_in and said.get("email") == "a@example.test", (
        "Claude Code did not read the fallback file with the Keychain empty")
    assert box.store().read() == blobs["CI-A"]
    assert box.listed()["CI-A"]["active"]

    box.switch("CI-B")
    assert store.primary.read() == blobs["CI-B"]
    assert store.fallback.read() is None
    assert box.stashed("CI-A") == blobs["CI-A"]
    signed_in, said = claude_status(vendor_env())
    assert signed_in and said.get("email") == "b@example.test"


@darwin_only
def test_a_mac_process_with_no_user_variable_still_finds_the_login(machine):
    """Started by launchd or a desktop launcher, a process can have no USER.

    Claude Code then asks the system for the user name. Shambles used to
    fall straight to ``claude-code-user`` and so wrote a Keychain item the
    vendor never reads; the vendor is the judge that it no longer does.
    """
    blobs = {"CI-A": claude_blob("a"), "CI-B": claude_blob("b")}
    accounts = {"CI-A": claude_account("a"), "CI-B": claude_account("b")}
    box = machine("claude", blobs, accounts=accounts)
    box.seed("CI-A")
    box.switch("CI-B", without=("USER", "LOGNAME"))
    signed_in, said = claude_status(vendor_env())
    assert signed_in and said.get("email") == "b@example.test"
    stray = KeychainStore(service="Claude Code-credentials",
                          account="claude-code-user")
    assert stray.read() is None, "a second Keychain item was created"


# -- 5. last, because it rearranges the runner's keychains --------------------


@darwin_only
def test_a_locked_keychain_is_reported_as_locked_and_the_file_is_used(tmp_path):
    """SSH into a Mac: the Keychain will not answer, and Claude Code falls
    back to its file.

    Staged with a throwaway keychain made the only one in the search list and
    then locked. A runner has a desktop session, so macOS may ask for the
    password in a dialog nobody can see instead of refusing; when that
    happens ``security`` hangs, the test notes it and stops. It is a record
    of what happened on this runner either way, and it runs last because it
    changes which keychains are searched.
    """
    def security(*args, timeout=20):
        return subprocess.run(["security", *args], capture_output=True,
                              text=True, timeout=timeout)

    original = security("list-keychains", "-d", "user").stdout
    originals = [line.strip().strip('"') for line in original.splitlines()
                 if line.strip()]
    default = security("default-keychain", "-d", "user").stdout.strip().strip('"')
    scratch = str(tmp_path / "shambles-ci.keychain-db")
    password = "shambles-ci"
    account = os.environ.get("USER", "runner")
    service = f"Shambles CI locked {uuid.uuid4().hex[:8]}-credentials"
    store = KeychainStore(service=service, account=account)
    file_store = FileStore(tmp_path / ".credentials.json")
    layered = FallbackStore(store, file_store)

    try:
        assert security("create-keychain", "-p", password, scratch).returncode == 0
        assert security("list-keychains", "-d", "user", "-s", scratch).returncode == 0
        assert security("default-keychain", "-d", "user", "-s", scratch).returncode == 0
        security("unlock-keychain", "-p", password, scratch)

        store.write(b'{"in":"keychain"}')
        assert store.read() == b'{"in":"keychain"}'

        assert security("lock-keychain", scratch).returncode == 0
        try:
            probe = security("find-generic-password", "-a", account, "-w",
                             "-s", service, timeout=15)
        except subprocess.TimeoutExpired:
            pytest.skip("macOS asked for the keychain password in a dialog "
                        "instead of refusing; a desktop session cannot stage "
                        "the SSH case")
        print("locked keychain lookup -> exit", probe.returncode,
              "|", probe.stderr.strip()[:200])
        if probe.returncode != 36:
            pytest.skip(f"locked lookup exited {probe.returncode}, not 36; "
                        "recorded above")

        from shambles.stores.base import StoreLockedError
        with pytest.raises(StoreLockedError):
            store.read()
        with pytest.raises(StoreLockedError):
            layered.read()  # nothing in the file either: locked, not "signed out"

        file_store.write(b'{"in":"file"}')
        assert layered.read() == b'{"in":"file"}'
        layered.write(b'{"in":"file, switched"}')
        assert file_store.read() == b'{"in":"file, switched"}'
    finally:
        security("unlock-keychain", "-p", password, scratch)
        if originals:
            security("list-keychains", "-d", "user", "-s", *originals)
        if default:
            security("default-keychain", "-d", "user", "-s", default)
        security("delete-keychain", scratch)
