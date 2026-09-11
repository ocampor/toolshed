"""The fixture site, served from this process on a random loopback port.

Everything the suite needs is in ``site/``; nothing reaches the public
internet, so a run is reproducible on a laptop, in CI and inside a sandbox.
The two dynamic routes are ``/redirect``, because a 302 cannot be expressed as
a static file, and ``/slow-resource``, because a file served instantly cannot
hold a page's ``load`` event open.
"""

import base64
import functools
import http.server
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs

SITE_DIR = Path(__file__).parent / "site"


REDIRECT_PATH = "/redirect"
REDIRECT_TARGET = "/redirect-target.html"

SLOW_RESOURCE_PATH = "/slow-resource"
# The same default every fixture page uses for ``?delay=``.
SLOW_RESOURCE_DEFAULT_DELAY_MS = 1_500
# A 1x1 transparent PNG: the smallest body a browser will treat as an image,
# so what the page waits for is the delay and not the transfer.
SLOW_RESOURCE_BODY = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQ"
    "DwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def requested_delay_ms(query: str) -> int:
    values = parse_qs(query).get("delay")
    if not values:
        return SLOW_RESOURCE_DEFAULT_DELAY_MS
    return int(values[0])


class SiteHandler(http.server.SimpleHTTPRequestHandler):
    """Static files, plus a 302 and a deliberately slow image."""

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path == SLOW_RESOURCE_PATH:
            self.serve_slow_resource(query)
            return
        if path == REDIRECT_PATH:
            target = f"{REDIRECT_TARGET}?{query}" if query else REDIRECT_TARGET
            self.send_response(302)
            self.send_header("Location", target)
            self.end_headers()
            return
        super().do_GET()

    def serve_slow_resource(self, query: str) -> None:
        """Sleep first, then answer — a page embedding this cannot fire
        ``load`` before ``?delay=`` has passed."""
        time.sleep(requested_delay_ms(query) / 1000)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(SLOW_RESOURCE_BODY)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(SLOW_RESOURCE_BODY)
        except (BrokenPipeError, ConnectionResetError):
            # A page that navigated away while we were sleeping is the normal
            # end of this route, not an error worth a traceback on stderr.
            return

    def log_message(self, format: str, *args: object) -> None:
        """The stdlib handler's per-request stderr line would drown the table."""


@contextmanager
def serve_site() -> Iterator[str]:
    """Yield the base URL of the fixture site for as long as the block runs."""
    handler = functools.partial(SiteHandler, directory=str(SITE_DIR))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
