"""The fixture site, served from this process on a random loopback port.

Everything the suite needs is in ``site/``; nothing reaches the public
internet, so a run is reproducible on a laptop, in CI and inside a sandbox.
"""

import functools
import http.server
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SITE_DIR = Path(__file__).parent / "site"


class SiteHandler(http.server.SimpleHTTPRequestHandler):
    """The stdlib static handler, quietened."""

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
