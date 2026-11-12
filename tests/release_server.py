"""A directory served over HTTP from a process of its own.

The installer tests need something that stands in for GitHub Releases. The
server is a separate process, never a thread inside pytest, and that is
deliberate: a thread that runs Python can be the one the garbage collector
picks to clean up after earlier tests, and Tk objects may only be destroyed
on the thread that made them. On macOS a server thread that collected what
the window tests left behind first hung the download it was serving and then
aborted the whole run.

Run as a script it serves ``argv[1]`` on a free port and prints the port.
"""

import contextlib
import http.server
import subprocess
import sys
from pathlib import Path


class Handler(http.server.SimpleHTTPRequestHandler):
    # What raw.githubusercontent.com sends for a script. PowerShell decides
    # whether `irm` hands back text or bytes from this.
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map,
                      ".ps1": "text/plain; charset=utf-8",
                      ".sh": "text/plain; charset=utf-8"}

    def log_message(self, *args, **kwargs):
        pass


@contextlib.contextmanager
def serve(root):
    """Serve ``root`` until the block ends; yields ``http://127.0.0.1:<port>``."""
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), str(root)],
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, text=True)
    try:
        port = process.stdout.readline().strip()
        if not port.isdigit():
            raise RuntimeError(f"the release server did not start: {port!r}")
        yield f"http://127.0.0.1:{port}"
    finally:
        process.kill()
        process.wait(timeout=10)
        process.stdout.close()


def main(root):
    def handler(*args, **kwargs):
        return Handler(*args, directory=root, **kwargs)

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    print(server.server_address[1], flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main(sys.argv[1])
