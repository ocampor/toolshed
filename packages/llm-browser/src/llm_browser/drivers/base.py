"""The driver contract: one abstract base every browser backend implements.

A Driver owns both lifecycle (launch/connect/close) and interactions
(click/fill/type/navigate/read). Splitting these onto one class keeps
plug-and-play simple: subclass Driver, implement every abstract method.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Callable, ClassVar

from llm_browser.behavior import Behavior, BehaviorRuntime
from llm_browser.constants import EXTRACT_PROPERTIES
from llm_browser.drivers.handle import DriverHandle
from llm_browser.results import BytesResult


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

    Run ``llm-browser-check`` from ``packages/llm-browser-conformance`` to
    validate an implementation: it drives a new driver through every rule
    above against a real headless browser and a fixture site it serves
    itself, and names what it got wrong. Anything the driver deliberately
    does not support should raise ``NotImplementedError`` so the suite
    reports it as a skip rather than a failure.
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
        """Humanized click — rule 2; the default fits a natively humanized click."""
        self.click(locator)

    def humanized_type(
        self,
        page: Any,
        locator: Any,
        text: str,
        behavior: Behavior,
        runtime: BehaviorRuntime,
    ) -> None:
        """Humanized type — rule 2; the default fits a natively humanized type."""
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
        """Fire a synthetic (``isTrusted=false``) DOM event — rule 2's escape hatch."""

    # --- Navigation / waiting ---

    @abstractmethod
    def goto(self, page: Any, url: str, wait_until: str) -> None: ...

    @abstractmethod
    def wait_for_load(self, page: Any, state: str, timeout_ms: int) -> None:
        """Block until the page reaches ``state`` — the only page-level wait."""

    def scroll(self, page: Any, dx: int, dy: int, locator: Any | None = None) -> None:
        """Scroll by a mouse-wheel delta, over ``locator`` when one is given.

        A wheel event goes to whatever is under the pointer, so a page whose
        centre holds an inner scroller (a transcript, a virtualised table, a
        map) scrolls *that* unless the caller says what it meant.
        """
        raise NotImplementedError(f"{type(self).__name__} does not support scroll")

    @abstractmethod
    def is_visible(self, locator: Any) -> bool:
        """Whether the first match is rendered right now; ``False`` for a miss.

        Abstract rather than defaulted: a driver that skipped it would raise
        past the step's timeout-or-``ValueError`` contract and abort the flow.
        """

    # --- Read / capture ---

    @abstractmethod
    def text_content(self, locator: Any) -> str | None:
        """The first match's text as it reads right now; ``None`` for a miss."""

    @abstractmethod
    def input_value(self, locator: Any) -> str: ...

    @abstractmethod
    def get_attribute(self, locator: Any, name: str) -> str | None: ...

    @abstractmethod
    def count(self, locator: Any) -> int:
        """How many elements match *right now* — no waiting, no cache."""

    @abstractmethod
    def first(self, locator: Any) -> Any:
        """The first match, lazily: it must survive the element going away."""

    @abstractmethod
    def nth(self, locator: Any, index: int) -> Any:
        """The ``index``-th match, re-resolvable after the page swaps the node."""

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
        """Read one ``spec`` field off one row element.

        The same rule ``js/extract_rows.js`` applies, off the same allowlist:
        a name in it is a DOM property, anything else an HTML attribute.
        """
        child_selector = field["child_selector"]
        target = self.child(row, child_selector) if child_selector else row
        name = field["attribute"]
        assert name is not None
        if name in EXTRACT_PROPERTIES:
            return self.read_property(target, name)
        return self.get_attribute(target, name)

    def read_property(self, target: Any, name: str) -> str | None:
        """``el[name]`` as text; ``None`` when the element or the value is."""
        value = self.evaluate(target, f"(el) => el.{name}")
        return None if value is None else str(value)

    @abstractmethod
    def evaluate(self, target: Any, script: str) -> Any:
        """Run user-supplied JS against a page or element — the JS touchpoint
        of rule 3, and the only one that is arbitrary."""

    @abstractmethod
    def content(self, page: Any) -> str: ...

    @abstractmethod
    def page_url(self, page: Any) -> str: ...

    @abstractmethod
    def screenshot_bytes(self, page: Any) -> bytes:
        """The page as PNG bytes.

        Nothing is left on disk: a backend whose capture API can only write a
        file spools it to a temporary directory and removes it on the way
        out.
        """

    def screenshot_element_bytes(self, locator: Any) -> bytes:
        """One element as PNG bytes, cropped to its box.

        Same no-disk rule as :meth:`screenshot_bytes`. Optional: a backend
        whose capture API is page-only raises, and the conformance suite
        reports a skip.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not support element screenshots"
        )

    @abstractmethod
    def download_bytes(
        self, page: Any, trigger: Callable[[], None], timeout_ms: int
    ) -> BytesResult:
        """Run ``trigger``, wait up to ``timeout_ms`` for the download it
        starts, and return its bytes.

        Nothing is left on disk: a backend whose API can only download to a
        file reads that file back and removes it before returning. A download
        that never starts raises ``TimeoutError``; one that starts and then
        fails raises ``ValueError`` — both are step results, per rule 5.

        The payload is held whole in memory. There is no size ceiling here,
        deliberately: a caller that fetches something large should expect to
        hold it, and to hold ~4/3 of it again if it dumps the result to JSON.
        """

    @abstractmethod
    def enter_frame(self, locator: Any) -> Any: ...
