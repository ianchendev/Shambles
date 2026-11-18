"""Claims no screen may make.

Claude Code 2.1.300 checks its login file before each request and re-reads
it when it changed, so a running session moves to the new account at its
next request. Older Claude Code versions and Codex are unconfirmed. Until
they are, no frontend says what a running session does after a switch or a
sign-in, either way.
"""

import re
from pathlib import Path

import shambles

CLAIMS = re.compile(
    r"(?:running|sessions?)\b[^.\n]{0,30}\b(?:keeps?|retains?) "
    r"(?:the |their |its )?(?:\w+ )?(?:login|token|account)"
    r"|start a new (?:session|one) to (?:pick it up|use)",
    re.IGNORECASE)


def test_no_frontend_says_what_a_running_session_does_after_a_switch():
    package = Path(shambles.__file__).resolve().parent
    found = []
    for path in sorted(package.rglob("*")):
        if path.suffix not in (".py", ".qml") or "__pycache__" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        # Joined the way Python joins adjacent literals, so a claim split
        # over two lines is still one claim.
        flat = re.sub(r'"\s*\n\s*f?"', "", text)
        for match in CLAIMS.finditer(flat):
            found.append(f"{path.relative_to(package)}: {match.group(0)!r}")
    assert found == []
