"""The driver contract: one abstract base every browser backend implements.

A Driver owns both lifecycle (launch/connect/close) and interactions
(click/fill/type/navigate/read). Splitting these onto one class keeps
plug-and-play simple: subclass Driver, implement every abstract method.
"""

import tempfile
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, ClassVar

from llm_browser.behavior import Behavior, BehaviorRuntime
from llm_browser.drivers.handle import DriverHandle


class Driver(ABC):
    """Base class for browser drivers. Owns lifecycle + interactions.

    Everything above a driver — ``llm_browser.waits``, ``BrowserSession``, the
    flow actions — is written against these rules rather than any one browser
    API, so a new driver holds to them:

    1. Only ``wait_for_load`` may block on the DOM. ``resolve``, ``count``,
       ``first``, ``nth``, ``all``, ``is_visible`` and ``text_content``
       answer about the page as it is right now and report a miss as empty,
       ``False`` or ``None`` — never a retry, never a raise for "not there
       yet". Waiting is ``llm_browser.waits``' job, on a deadline the caller
       owns.
    2. Input must be trusted events — OS-level or CDP ``Input.*`` — never
       synthetic DOM events. ``dispatch_event`` is the one explicit opt-in.
       ``humanized_click`` and ``humanized_type`` are that same trusted input
       paced like a person's, and they stay on the driver because the how is
       backend-specific: the Playwright family draws a jittered mouse path
       through ``page.mouse``, while nodriver leaves both defaulted because
       its native CDP click already moves a real cursor. Whether to reach for
       them is ``BrowserSession``'s call, not a caller's.
    3. JS runs in ``evaluate``, ``is_visible``, ``input_value`` and
       ``extract_rows``, nowhere else. The rest stays on the DOM, Input and
       Page domains, so a detector watching Runtime traffic sees none of it
       on the common path.
    4. Locators are opaque handles and may be lazy; ``first`` and ``nth``
       carry enough (selector plus index) to be re-resolved, or a node the
       page replaced is never seen to change.
    5. Timeouts are milliseconds, and an expired one raises the builtin
       ``TimeoutError``.
    """

    name: ClassVar[str]
    supports_reconnect: ClassVar[bool] = False

    # --- Lifecycle ---

    @abstractmethod
    def launch(
        self,
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle: ...

    def attach(self, cdp_url: str) -> DriverHandle:
        """Attach to an already-running Chromium over CDP.

        Subclasses that support it (patchright) override this. Others raise.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support attach; use driver='patchright'"
        )

    def attach_to_tab(self, cdp_url: str, target_id: str) -> DriverHandle:
        """Attach to one existing tab, addressed by its CDP target id.

        Subclasses that support it (patchright) override this. Others raise.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support attach; use driver='patchright'"
        )

    @abstractmethod
    def page(self, handle: DriverHandle) -> Any: ...

    @abstractmethod
    def close(self, handle: DriverHandle) -> None: ...

    @abstractmethod
    def status(self, handle: DriverHandle) -> bool: ...

    @abstractmethod
    def latest_tab(self, handle: DriverHandle) -> Any: ...

    def close_other_tabs(self, handle: DriverHandle, keep: Any) -> None:
        """Close every tab in the current context except ``keep``.

        Default no-op for drivers without a multi-page concept.
        """

    # --- Selector resolution ---

    @abstractmethod
    def resolve(self, page: Any, selector: str) -> Any:
        """A locator for ``selector``; matching nothing yet is not an error."""

    # --- Interactions ---

    @abstractmethod
    def click(self, locator: Any, *, dispatch: bool = False) -> None: ...

    @abstractmethod
    def fill(self, locator: Any, text: str) -> None: ...

    @abstractmethod
    def type(self, locator: Any, text: str, *, delay_ms: int = 0) -> None: ...

    def humanized_click(
        self,
        page: Any,
        locator: Any,
        behavior: Behavior,
        runtime: BehaviorRuntime,
    ) -> None:
        """Humanized click — rule 2. Default falls back to plain click(), which
        is right for a driver whose native click is already humanized
        (nodriver's element.click, Camoufox with humanize=True). Drivers that
        need to draw the path themselves override it; see
        ``behavior.humanized_click`` for the Playwright-family one.
        """
        self.click(locator)

    def humanized_type(
        self,
        page: Any,
        locator: Any,
        text: str,
        behavior: Behavior,
        runtime: BehaviorRuntime,
    ) -> None:
        """Humanized type — rule 2. Default falls back to plain type().
        Override to use behavior.humanized_type or a driver-native path.
        """
        self.type(locator, text)

    @abstractmethod
    def press(self, locator: Any, key: str) -> None: ...

    @abstractmethod
    def press_focused(self, page: Any, key: str) -> None: ...

    @abstractmethod
    def select_option(self, locator: Any, value: str) -> None: ...

    @abstractmethod
    def set_checked(self, locator: Any, checked: bool) -> None: ...

    @abstractmethod
    def dispatch_event(self, locator: Any, event: str) -> None:
        """Fire a synthetic (``isTrusted=false``) DOM event — the opt-in
        escape hatch from rule 2, for overlays real input cannot reach."""

    # --- Navigation / waiting ---

    @abstractmethod
    def goto(self, page: Any, url: str, wait_until: str) -> None: ...

    @abstractmethod
    def wait_for_load(self, page: Any, state: str, timeout_ms: int) -> None:
        """Block until the page reaches ``state`` — the only page-level wait."""

    def scroll(self, page: Any, dx: int, dy: int) -> None:
        """Scroll the page by a mouse-wheel delta.

        Subclasses backed by a wheel-capable API override this.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support scroll")

    @abstractmethod
    def is_visible(self, locator: Any) -> bool:
        """Whether the first match is rendered right now; False if nothing matches.

        A single read, including for a handle whose node the page already
        detached. It is what the Python-side explicit wait in
        ``llm_browser.waits`` polls. Abstract rather than defaulted because
        there is no honest fallback — a driver that skipped it would raise
        past ``execute_action``'s timeout-or-ValueError contract and abort the
        flow instead of failing the step.
        """

    # --- Read / capture ---

    @abstractmethod
    def text_content(self, locator: Any) -> str | None:
        """The first match's text as it reads right now; ``None`` for a miss.

        The ``stable`` wait polls this, so it may not wait for an element to
        turn up — "nothing there" is an answer, not a reason to block.
        """

    @abstractmethod
    def input_value(self, locator: Any) -> str: ...

    @abstractmethod
    def get_attribute(self, locator: Any, name: str) -> str | None: ...

    @abstractmethod
    def count(self, locator: Any) -> int:
        """How many elements match *right now* — no waiting, no cache.

        A poll tick that blocks inside the driver makes the poll loop's own
        deadline meaningless, and one that reads a cache never sees the page
        change. A caller that needs the element to be there waits for it
        first, through ``BrowserSession.wait_for_element``.
        """

    @abstractmethod
    def first(self, locator: Any) -> Any:
        """The first match, lazily: it must survive the element going away."""

    @abstractmethod
    def nth(self, locator: Any, index: int) -> Any:
        """The ``index``-th match, carrying selector and index so a wait can
        re-resolve this same match after the page swaps the node."""

    @abstractmethod
    def all(self, locator: Any) -> list[Any]: ...

    @abstractmethod
    def child(self, locator: Any, selector: str) -> Any: ...

    def extract_rows(
        self, locator: Any, spec: dict[str, dict[str, str | None]]
    ) -> list[dict[str, str | None]]:
        """Read every field of ``spec`` off every element matched by ``locator``.

        ``spec`` maps a field name to ``{"child_selector": ..., "attribute": ...}``.
        The default walks the matched elements from Python — one transport
        round-trip per element and field. Drivers that can run a function over
        all matches in one page evaluation should override.
        """
        return [
            {name: self.read_field(row, field) for name, field in spec.items()}
            for row in self.all(locator)
        ]

    def read_field(self, row: Any, field: dict[str, str | None]) -> str | None:
        """Read one ``spec`` field off one row element."""
        child_selector = field["child_selector"]
        target = self.child(row, child_selector) if child_selector else row
        attribute = field["attribute"]
        if attribute == "textContent":
            return self.text_content(target)
        if attribute == "value":
            return self.input_value(target)
        assert attribute is not None
        return self.get_attribute(target, attribute)

    @abstractmethod
    def evaluate(self, target: Any, script: str) -> Any:
        """Run user-supplied JS against a page or element — the JS touchpoint
        of rule 3, and the only one that is arbitrary."""

    @abstractmethod
    def content(self, page: Any) -> str: ...

    @abstractmethod
    def page_url(self, page: Any) -> str: ...

    @abstractmethod
    def screenshot(self, page: Any, path: Path) -> None: ...

    def screenshot_bytes(self, page: Any) -> bytes:
        """The page as PNG bytes. The default writes a temp file and reads it
        back, for drivers whose screenshot API can only write one."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "screenshot.png"
            self.screenshot(page, path)
            return path.read_bytes()

    @abstractmethod
    def expect_download(
        self, page: Any, trigger: Callable[[], None], output: Path
    ) -> Path: ...

    @abstractmethod
    def enter_frame(self, locator: Any) -> Any: ...
