"""Attached-mode downloads against a real Chromium whose download dir is
unwritable, as on the deployed guest: the bytes must come back sha-exact
from inside the page, and nothing may land on disk."""

import hashlib
import http.server
import random
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from llm_browser.actions import execute_action
from llm_browser.drivers import patchright_download
from llm_browser.models import DownloadStep
from llm_browser.results import ErrorResult
from llm_browser.scripts import load_script
from llm_browser.session import BrowserSession

# Another process's client: its goto must not wait on our idle connection.
OTHER_CLIENT = """
import sys
from patchright.sync_api import sync_playwright
with sync_playwright() as p:
    page = p.chromium.connect_over_cdp(sys.argv[1]).contexts[0].new_page()
    page.goto(sys.argv[2], timeout=5000)
"""
SIZES_MB = (1, 15)
DATA = {mb: random.Random(mb).randbytes(mb << 20) for mb in SIZES_MB}
BUTTON = """<button aria-label="Download" onclick="
fetch('/blob.bin?mb={mb}').then(r => r.blob()).then(b => {{
  const a = document.createElement('a');
  a.href = window.URL.createObjectURL(b); a.download = 'doc.pdf'; document.body.append(a);
  a.click(); {after}
}});">Download</button>"""
# The blob URL exists before the step; the button shows once it does.
EARLY_BLOB = """<script>
fetch('/blob.bin?mb={mb}').then(r => r.blob()).then(b => {{
  const url = URL.createObjectURL(b);
  const button = document.createElement('button');
  button.setAttribute('aria-label', 'Download');
  button.onclick = () => {{
    const a = document.createElement('a');
    a.href = url; a.download = 'doc.pdf'; document.body.append(a);
    a.click(); URL.revokeObjectURL(url);
  }};
  document.body.append(button);
}});
</script>"""


def page_html(path: str, mb: int, other: str) -> str:
    if path == "/revoke.html":
        return BUTTON.format(mb=mb, after="window.URL.revokeObjectURL(a.href);")
    if path == "/early.html":
        return EARLY_BLOB.format(mb=mb)
    if path == "/frame-host.html":
        return f'<iframe id="f" src="{other}/top.html?mb={mb}"></iframe>'
    if path in ("/link.html", "/hang-link.html"):
        file = "file.pdf" if path == "/link.html" else "hang.pdf"
        return f'<a aria-label="Download" download href="/{file}?mb={mb}">Get</a>'
    return BUTTON.format(mb=mb, after="")


def handler(other: list[str]) -> type[http.server.BaseHTTPRequestHandler]:
    served_hang = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path, _, query = self.path.partition("?")
            mb = int(query.removeprefix("mb=") or 1)
            headers = {"content-type": "text/html"}
            if path == "/hang.pdf":
                if served_hang.is_set():
                    time.sleep(30)  # the in-page refetch never gets an answer
                    return
                served_hang.set()
            if path in ("/blob.bin", "/file.pdf", "/hang.pdf"):
                body = DATA[mb]
                headers = {
                    "content-type": "application/pdf",
                    "content-disposition": 'attachment; filename="file.pdf"',
                }
            else:
                body = page_html(path.removeprefix("/csp"), mb, other[0]).encode()
            if path.startswith("/csp/"):
                # blob: is not 'self', so a refetch of the page's blob is refused.
                headers["content-security-policy"] = "connect-src 'self'"
            self.send_response(200)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    return Handler


@pytest.fixture(scope="module")
def site() -> Iterator[str]:
    """The top site's url; its iframe page embeds the other site, out of process."""
    other: list[str] = []
    hosts = ("127.0.0.1", "localhost")
    servers = [http.server.ThreadingHTTPServer((h, 0), handler(other)) for h in hosts]
    for server in servers:
        threading.Thread(target=server.serve_forever, daemon=True).start()
    top, second = (f"http://{h}:{s.server_address[1]}" for h, s in zip(hosts, servers))
    other.append(second)
    yield top
    for server in servers:
        server.shutdown()


@pytest.fixture(scope="module")
def chrome() -> Iterator[tuple[str, Path]]:
    from patchright.sync_api import sync_playwright

    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    if not Path(executable).exists():
        pytest.skip("no patchright chromium installed")
    profile = Path(tempfile.mkdtemp(prefix="llmb-dl-profile-"))
    # The loopback iframe needs LocalNetworkAccessChecks off; test-only.
    process = subprocess.Popen(
        [
            executable,
            "--headless=new",
            "--remote-debugging-port=0",
            f"--user-data-dir={profile}",
            "--no-first-run",
            "--disable-features=LocalNetworkAccessChecks",
            "about:blank",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    port_file = profile / "DevToolsActivePort"
    for _ in range(100):
        if port_file.exists() and port_file.read_text().strip():
            break
        time.sleep(0.1)
    port = port_file.read_text().split()[0]
    try:
        yield f"http://127.0.0.1:{port}", profile
    finally:
        process.kill()
        process.wait()
        shutil.rmtree(profile, ignore_errors=True)


@pytest.fixture
def session(chrome: tuple[str, Path], tmp_path: Path) -> Iterator[BrowserSession]:
    session = BrowserSession(state_dir=tmp_path, driver="patchright")
    session.attach(chrome[0])
    # Stand in for Playwright pointing the guest at a dir it cannot write.
    cdp = session.get_page().context.browser.new_browser_cdp_session()
    behavior = {"behavior": "allowAndName", "downloadPath": "/nonexistent/dl"}
    cdp.send("Browser.setDownloadBehavior", behavior)
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def nothing_on_disk(chrome: tuple[str, Path]) -> Iterator[None]:
    started = time.time()
    before = written(chrome[1], started)
    yield
    assert written(chrome[1], started) == before


def written(profile: Path, since: float) -> set[Path]:
    temp = Path(tempfile.gettempdir())
    artifacts = {p for d in temp.glob("playwright-artifacts-*") for p in d.rglob("*")}
    names = {"doc.pdf", "file.pdf"}
    spooled = {
        p for p in profile.rglob("*") if p.name in names or p.suffix == ".crdownload"
    }
    downloads = Path.home() / "Downloads"
    recent = {p for p in downloads.glob("*") if p.stat().st_mtime >= since}
    return artifacts | spooled | recent


CASES = {
    "a top-frame blob": ("/top.html", 1, False),
    "a top-frame blob, sliced": ("/top.html", 15, False),
    "b cross-origin iframe blob": ("/frame-host.html", 1, True),
    "c revoked right after the click": ("/revoke.html", 1, False),
    "c made before the step, revoked on the click": ("/early.html", 1, False),
    "d direct link": ("/link.html", 1, False),
    "blob under CSP connect-src 'self'": ("/csp/top.html", 1, False),
}


@pytest.mark.parametrize(("path", "mb", "in_frame"), CASES.values(), ids=list(CASES))
@pytest.mark.usefixtures("nothing_on_disk")
def test_attached_download_is_read_in_page(
    session: BrowserSession, site: str, path: str, mb: int, in_frame: bool
) -> None:
    page = session.get_page()
    page.goto(f"{site}{path}?mb={mb}")
    scope = page.frame_locator("#f") if in_frame else page
    button = scope.locator('[aria-label="Download"]')
    button.wait_for()
    result = session.driver.download_bytes(page, button.click, 10000)
    assert hashlib.sha256(result.content).digest() == hashlib.sha256(DATA[mb]).digest()


@pytest.mark.parametrize("path", ["/revoke.html", "/early.html", "/csp/top.html"])
def test_these_blobs_need_the_keep_blob_script(
    session: BrowserSession, site: str, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    monkeypatch.setattr(patchright_download, "keep_blobs", lambda page: None)
    page = session.get_page()
    page.goto(f"{site}{path}?mb=1")
    page.locator('[aria-label="Download"]').wait_for()
    click = page.locator('[aria-label="Download"]').click
    with pytest.raises(ValueError, match="did not complete"):
        session.driver.download_bytes(page, click, 10000)


def test_a_download_in_another_tab_is_not_ours(
    session: BrowserSession, site: str
) -> None:
    page = session.get_page()
    page.goto(f"{site}/top.html")
    other = page.context.new_page()
    try:
        other.goto(f"{site}/top.html")
        click = other.locator('[aria-label="Download"]').click
        with pytest.raises(ValueError, match="outside this tab"):
            session.driver.download_bytes(page, click, 3000)
    finally:
        other.close()


def test_an_idle_session_does_not_stall_other_clients(
    session: BrowserSession, site: str, chrome: tuple[str, Path]
) -> None:
    """An init script would leave a context-wide route that only an active
    sync call services, hanging every other client's navigation."""
    page = session.get_page()
    page.goto(f"{site}/top.html")
    button = page.locator('[aria-label="Download"]')
    session.driver.download_bytes(page, button.click, 10000)
    other_client = subprocess.run(
        [sys.executable, "-c", OTHER_CLIENT, chrome[0], f"{site}/top.html"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert other_client.returncode == 0, other_client.stderr[-500:]


def test_a_transfer_past_the_deadline_fails_the_step(
    session: BrowserSession, site: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(patchright_download, "DOWNLOAD_SLICE_BYTES", 1024)
    session.get_page().goto(f"{site}/top.html?mb=15")
    step = DownloadStep(
        name="s", action="download", selector='[aria-label="Download"]', timeout=2000
    )
    result = execute_action(session, step)
    assert isinstance(result, ErrorResult)
    assert "transfer exceeded" in result.message


def test_a_hung_refetch_times_out_within_the_step(
    session: BrowserSession, site: str
) -> None:
    session.get_page().goto(f"{site}/hang-link.html")
    step = DownloadStep(
        name="s", action="download", selector='[aria-label="Download"]', timeout=3000
    )
    started = time.monotonic()
    result = execute_action(session, step)
    assert isinstance(result, ErrorResult)
    assert "transfer exceeded" in result.message
    assert time.monotonic() - started < 5


def test_the_keep_blob_script_wraps_a_document_once(
    session: BrowserSession, site: str
) -> None:
    """Every download step evaluates the script again in the same document;
    a revoke must still happen once, and only after the deferral."""
    page = session.get_page()
    page.goto(f"{site}/top.html")
    page.evaluate(FAKE_REVOKE_AND_TIMERS, isolated_context=False)
    for _ in range(2):
        page.evaluate(load_script("keep_blobs"), isolated_context=False)
    revokes = page.evaluate(REVOKE_THEN_FIRE_TIMERS, isolated_context=False)
    assert revokes == {"at_call": 0, "after_timers": 1}


FAKE_REVOKE_AND_TIMERS = """() => {
  window.revoked = [];
  window.timers = [];
  URL.revokeObjectURL = (url) => window.revoked.push(url);
  window.setTimeout = (callback) => window.timers.push(callback);
}"""
# One round of timers: a double wrap would need two to reach the real revoke.
REVOKE_THEN_FIRE_TIMERS = """() => {
  URL.revokeObjectURL("blob:x");
  const at_call = window.revoked.length;
  window.timers.splice(0).forEach((callback) => callback());
  return { at_call, after_timers: window.revoked.length };
}"""
