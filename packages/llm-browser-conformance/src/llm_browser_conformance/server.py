"""Loopback only, so runs are reproducible offline; dynamic routes are what a static file cannot express."""

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

# The popup-download routes, named after the portal shape they came from: a
# button opens an ``.action`` URL in a new tab, which 302s to the file itself.
PRINT_ACTION_PATH = "/billtax/print.action"
ATTACH_ACTION_PATH = "/billtax/attach.action"
INLINE_PDF_PATH = "/billtax/downloadFile.action"
ATTACHMENT_PDF_PATH = "/attach.pdf"

INLINE_PDF_FILENAME = "ComprobanteSATDPA.pdf"
ATTACHMENT_PDF_FILENAME = "attach.pdf"

REDIRECTS = {
    REDIRECT_PATH: REDIRECT_TARGET,
    PRINT_ACTION_PATH: INLINE_PDF_PATH,
    ATTACH_ACTION_PATH: ATTACHMENT_PDF_PATH,
}

PDF_DISPOSITIONS = {
    INLINE_PDF_PATH: f'inline; filename="{INLINE_PDF_FILENAME}"',
    ATTACHMENT_PDF_PATH: f'attachment; filename="{ATTACHMENT_PDF_FILENAME}"',
}

# Every download scenario asserts on this prefix.
PDF_MAGIC = b"%PDF"

# One page, valid enough for a viewer to open: a browser that rejected the
# file would never start the download the scenarios are about.
PDF_BODY = (SITE_DIR / "receipt.pdf").read_bytes()

# Long enough that the file lands after the tab that asked for it has opened,
# short enough to cost the suite nothing.
PDF_DELAY_S = 0.3

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
    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        if path == SLOW_RESOURCE_PATH:
            self.serve_slow_resource(query)
            return
        if path in REDIRECTS:
            self.serve_redirect(REDIRECTS[path], query)
            return
        if path in PDF_DISPOSITIONS:
            self.serve_pdf(PDF_DISPOSITIONS[path])
            return
        super().do_GET()

    def do_POST(self) -> None:
        """The body is drained, or a later POST fixture would desync a kept-alive connection."""
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.do_GET()

    def serve_redirect(self, target: str, query: str) -> None:
        self.send_response(302)
        self.send_header("Location", f"{target}?{query}" if query else target)
        self.end_headers()

    def serve_pdf(self, disposition: str) -> None:
        """Answer late, so the file arrives after the tab that asked for it."""
        time.sleep(PDF_DELAY_S)
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header("Content-Length", str(len(PDF_BODY)))
        self.send_header("Content-Disposition", disposition)
        self.end_headers()
        self.wfile.write(PDF_BODY)

    def serve_slow_resource(self, query: str) -> None:
        """Sleeps first, so a page embedding this cannot fire ``load`` before ``?delay=``."""
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
