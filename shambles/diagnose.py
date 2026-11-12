"""Why switching might not work on this machine, said out loud.

Shambles moves a credential between places on disk. Whether that changes who
a vendor's program signs in as depends on things outside Shambles: which
install of the program is on PATH, whether an environment variable is
supplying a login of its own, whether the vendor has been told to keep the
login somewhere else. When one of those is wrong a switch succeeds, the
window shows the new account, and nothing changes -- the failure that is
hardest to notice and most expensive to be wrong about.

Every check here is a look, never a change. Nothing is written, no vendor
program is started, and no credential is read beyond asking a store whether
it holds one.

The findings are plain data so that any frontend can show them; ``shambles
doctor`` is merely the first to.
"""

import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import ShamblesError
from .providers import spec as specmod
from .stores import FallbackStore, UnsupportedStore

#: Switching will not take effect, or cannot be done at all.
PROBLEM = "problem"
#: Switching works, but something here will surprise somebody.
WARNING = "warning"
#: How this machine is set up. Not a fault.
INFO = "info"

#: Variables that make a vendor sign in from the environment instead of from
#: its stored login. Each is a (variable, what it does) pair; the lists come
#: from the vendors' own documentation and source, see docs/token-storage.md.
AUTH_OVERRIDES = {
    "claude": (
        ("ANTHROPIC_API_KEY", "an API key"),
        ("ANTHROPIC_AUTH_TOKEN", "a bearer token"),
        ("CLAUDE_CODE_OAUTH_TOKEN", "a long-lived token"),
        ("CLAUDE_CODE_USE_BEDROCK", "Amazon Bedrock"),
        ("CLAUDE_CODE_USE_VERTEX", "Google Vertex AI"),
        ("CLAUDE_CODE_USE_FOUNDRY", "Microsoft Foundry"),
        ("ANTHROPIC_PROFILE", "a named Anthropic profile"),
    ),
    "codex": (
        ("CODEX_ACCESS_TOKEN", "an access token"),
        ("CODEX_API_KEY", "an API key (in 'codex exec')"),
        ("OPENAI_FEDERATION_RULE_ID", "workload identity"),
        ("OPENAI_IDENTITY_TOKEN_FILE", "workload identity"),
    ),
}


@dataclass(frozen=True)
class Finding:
    level: str
    provider: str | None
    #: Stable, for scripts and tests. The message is for people.
    code: str
    message: str


def is_wsl(env=None, *, proc_version="/proc/version") -> bool:
    """Whether this is Linux running under the Windows Subsystem for Linux."""
    env = os.environ if env is None else env
    if env.get("WSL_DISTRO_NAME") or env.get("WSL_INTEROP"):
        return True
    try:
        return "microsoft" in Path(proc_version).read_text(
            encoding="utf-8", errors="replace").lower()
    except OSError:
        return False


def is_windows_binary_under_wsl(path: str | None) -> bool:
    """Whether ``path`` is a Windows program reached through WSL interop.

    WSL puts the Windows PATH on the end of its own, so ``claude`` can
    resolve to ``/mnt/c/Users/.../claude.exe`` when nothing is installed
    inside the distribution. That program keeps its login in the Windows
    profile, which is a different machine as far as Shambles is concerned.
    """
    if not path:
        return False
    text = str(path)
    lowered = text.lower()
    if lowered.endswith((".exe", ".cmd", ".bat", ".ps1")):
        return True
    parts = Path(text).parts
    return len(parts) > 2 and parts[1] == "mnt" and len(parts[2]) == 1


def diagnose(paths, providers, *, platform=sys.platform, env=None,
             which=None, wsl=None) -> list[Finding]:
    """Everything worth saying about this machine, most serious first."""
    env = os.environ if env is None else env
    which = shutil.which if which is None else which
    wsl = is_wsl(env) if wsl is None and platform.startswith("linux") else bool(wsl)
    found: list[Finding] = []

    if wsl:
        found.append(Finding(
            INFO, None, "wsl",
            "This is WSL. Shambles here manages the Claude Code and Codex "
            "installed inside this Linux distribution. The ones installed on "
            "Windows itself keep a separate login, which only Shambles for "
            "Windows can switch."))

    for provider in providers:
        found.extend(_provider_findings(paths, provider, platform=platform,
                                        env=env, which=which, wsl=wsl))

    order = {PROBLEM: 0, WARNING: 1, INFO: 2}
    return sorted(found, key=lambda f: order[f.level])


def _provider_findings(paths, provider, *, platform, env, which, wsl):
    name = provider.display_name
    found = []

    # -- where the login is kept ------------------------------------------
    try:
        store = provider.store(home=paths.home, platform=platform)
    except (ShamblesError, KeyError, ValueError) as exc:
        found.append(Finding(PROBLEM, provider.id, "store_unavailable", str(exc)))
        store = None

    if isinstance(store, UnsupportedStore):
        found.append(Finding(PROBLEM, provider.id, "store_unsupported",
                             store.reason))
    elif store is not None:
        found.append(Finding(
            INFO, provider.id, "store",
            f"{name} keeps its login in {store.describe()}."))
        if isinstance(store, FallbackStore):
            try:
                in_primary = store.primary.read() is not None
                in_file = store.fallback.read() is not None
            except ShamblesError as exc:
                found.append(Finding(WARNING, provider.id, "store_locked",
                                     str(exc)))
            else:
                if in_file and not in_primary:
                    found.append(Finding(
                        INFO, provider.id, "store_fallback_in_use",
                        f"{name}'s login is currently in the file, not in "
                        f"{store.primary.describe()}. That is where "
                        f"{name} puts it when the secure store refuses a "
                        "write, for example over SSH. Shambles reads it "
                        "from there, as the vendor does."))

    # -- which program is on PATH -----------------------------------------
    binary = provider.login_binary()
    location = which(binary)
    if location is None:
        found.append(Finding(
            WARNING, provider.id, "vendor_missing",
            f"'{binary}' is not on PATH. Switching between accounts already "
            f"saved still works, but Shambles runs '{binary}' to sign a new "
            "account in, so none can be added until it is installed."))
    elif wsl and is_windows_binary_under_wsl(location):
        found.append(Finding(
            PROBLEM, provider.id, "vendor_is_windows_install",
            f"'{binary}' on PATH is the Windows install ({location}), reached "
            f"from inside WSL. It keeps its login in your Windows profile, "
            f"not in this Linux home, so switching here will not change who "
            f"it signs in as. Install {name} inside WSL, or run Shambles for "
            "Windows to manage the Windows install."))

    # -- a login supplied by the environment ------------------------------
    for variable, what in AUTH_OVERRIDES.get(provider.id, ()):
        if env.get(variable):
            found.append(Finding(
                PROBLEM, provider.id, "auth_override",
                f"{variable} is set, so {name} signs in with {what} from the "
                "environment and ignores its stored login. Switching "
                "accounts will appear to do nothing in any program started "
                f"with that variable. Unset {variable} to use Shambles."))

    # -- a relocated configuration directory ------------------------------
    block = provider.spec.get("config_dir") or {}
    variable = block.get("env")
    raw = env.get(variable, "") if variable else ""
    if raw:
        directory = Path(raw)
        if not directory.is_absolute():
            found.append(Finding(
                PROBLEM, provider.id, "config_dir_relative",
                f"{variable} is '{raw}', which is not an absolute path. "
                f"{name} resolves it against whatever directory it is "
                "started in, so Shambles cannot tell which login it means."))
        elif block.get("strict") and not directory.is_dir():
            found.append(Finding(
                PROBLEM, provider.id, "config_dir_missing",
                f"{variable} points at {raw}, which does not exist. {name} "
                "refuses to start until it does."))
        else:
            default = specmod.expand(block.get("default", ""), home=paths.home)
            found.append(Finding(
                WARNING, provider.id, "config_dir_override",
                f"{variable} is set to {raw}. In this shell Shambles and "
                f"{name} both use that directory instead of {default}. A "
                f"program started without the variable -- VS Code opened "
                "from the desktop, for one -- uses the default directory "
                "and a separate login, which a switch made here does not "
                "touch."))
    return found


def render(findings) -> str:
    """The findings as text, for a terminal."""
    if not findings:
        return "Nothing to report.\n"
    labels = {PROBLEM: "PROBLEM", WARNING: "WARNING", INFO: "info"}
    blocks = []
    for finding in findings:
        head = labels[finding.level]
        if finding.provider:
            head += f" [{finding.provider}]"
        blocks.append(f"{head}\n" + "\n".join(
            f"  {line}" for line in finding.message.splitlines()))
    problems = sum(1 for f in findings if f.level == PROBLEM)
    summary = ("No problems found." if not problems else
               f"{problems} problem{'s' if problems != 1 else ''} found: "
               "switching will not work as expected until fixed.")
    return "\n\n".join(blocks) + f"\n\n{summary}\n"
