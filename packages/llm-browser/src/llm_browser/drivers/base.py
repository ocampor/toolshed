from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Callable, ClassVar

from llm_browser.behavior import Behavior, HitTest, type_chars
from llm_browser.constants import EXTRACT_PROPERTIES
from llm_browser.drivers.handle import DriverHandle
from llm_browser.results import BytesResult, HitTarget
from llm_browser.scripts import property_js


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

    Run ``llm-browser-check`` (the conformance package, in the toolshed repo) to
    validate an implementation: it drives a new driver through every rule
    above against a real headless browser and a fixture site it serves
    itself, and names what it got wrong. Anything the driver deliberately
    does not support should raise ``NotImplementedError`` so the suite
    reports it as a skip rather than a failure.
    """

    name: ClassVar[str]
    supports_reconnect: ClassVar[bool] = False
    # `role=button[name="Go"]` is Playwright's own selector syntax; everywhere
    # else it reaches `querySelectorAll` as a syntax error.
    supports_role_selector: ClassVar[bool] = False

    @abstractmethod
    def launch(
        self,
        user_data_dir: Path,
        url: str | None,
        headed: bool,
        executable_path: str | None = None,
    ) -> DriverHandle: ...

    def attach(self, cdp_url: str) -> DriverHandle:
        """Subclasses that support it (patchright) override this; others raise."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support attach; use driver='patchright'"
        )

    def attach_to_tab(self, cdp_url: str, target_id: str) -> DriverHandle:
        """Subclasses that support it (patchright) override this; others raise."""
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
        """Default no-op for drivers without a multi-page concept."""

    @abstractmethod
    def resolve(self, page: Any, selector: str) -> Any:
        """A locator for ``selector``; matching nothing yet is not an error."""

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
        hit_test: HitTest | None = None,
    ) -> HitTarget | None:
        """A driver that moves the pointer itself owns the hit test; the default never moves it."""
        self.click(locator)
        return None

    def humanized_type(
        self,
        page: Any,
        locator: Any,
        text: str,
        behavior: Behavior,
    ) -> None:
        """Native humanization owns a keystroke's shape, not its timing, so the cadence is sent key by key."""
        type_chars(lambda ch: self.type(locator, ch), text, behavior)

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

    @abstractmethod
    def goto(self, page: Any, url: str, wait_until: str) -> None: ...

    @abstractmethod
    def wait_for_load(self, page: Any, state: str, timeout_ms: int) -> None:
        """Block until the page reaches ``state`` — the only page-level wait."""

    def scroll(self, page: Any, dx: int, dy: int, locator: Any | None = None) -> None:
        """The wheel goes to whatever is under the pointer, so pass ``locator`` to aim past an inner scroller."""
        raise NotImplementedError(f"{type(self).__name__} does not support scroll")

    def is_enabled(self, locator: Any) -> bool:
        """``disabled`` for native controls, ``aria-disabled="true"`` for div-and-role widgets; nothing else is seen."""
        return (
            self.get_attribute(locator, "disabled") is None
            and self.get_attribute(locator, "aria-disabled") != "true"
        )

    def scroll_into_view(self, locator: Any) -> None:
        """Centred, not minimally scrolled: only the middle is clear of a fixed header and footer."""
        self.evaluate(locator, "(el) => el.scrollIntoView({block: 'center'})")

    @abstractmethod
    def is_visible(self, locator: Any) -> bool:
        """Abstract: a driver that skipped it would raise past the step's timeout-or-``ValueError`` contract."""

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
        self,
        locator: Any,
        spec: dict[str, dict[str, str | None]],
        exclude: Sequence[str] = (),
    ) -> list[dict[str, str | None]]:
        """The default costs a round trip per element and field; drivers that can evaluate once should override."""
        return [
            {name: self.read_field(row, field, exclude) for name, field in spec.items()}
            for row in self.all(locator)
        ]

    def read_field(
        self, row: Any, field: dict[str, str | None], exclude: Sequence[str] = ()
    ) -> str | None:
        """Same allowlist as ``js/extract_rows.js``: a listed name is a DOM property, anything else an attribute."""
        child_selector = field["child_selector"]
        target = self.child(row, child_selector) if child_selector else row
        name = field["attribute"]
        assert name is not None
        if name in EXTRACT_PROPERTIES:
            return self.read_property(target, name, exclude)
        return self.get_attribute(target, name)

    def read_property(
        self, target: Any, name: str, exclude: Sequence[str] = ()
    ) -> str | None:
        value = self.evaluate(target, property_js(name, exclude))
        return None if value is None else str(value)

    @abstractmethod
    def evaluate(self, target: Any, script: str, timeout_ms: int | None = None) -> Any:
        """The only arbitrary JS touchpoint (rule 3); a backend without a ``timeout_ms`` knob ignores it, never raises."""

    @abstractmethod
    def content(self, page: Any) -> str: ...

    @abstractmethod
    def page_url(self, page: Any) -> str: ...

    @abstractmethod
    def screenshot_bytes(self, page: Any) -> bytes:
        """Nothing is left on disk: a file-only capture API is spooled and removed."""

    def screenshot_element_bytes(self, locator: Any) -> bytes:
        """Optional: a page-only capture API raises, and conformance reports a skip."""
        raise NotImplementedError(
            f"{type(self).__name__} does not support element screenshots"
        )

    @abstractmethod
    def download_bytes(
        self, page: Any, trigger: Callable[[], None], timeout_ms: int
    ) -> BytesResult:
        """Leaves nothing on disk; no start raises ``TimeoutError``, a failed one ``ValueError`` (rule 5)."""

    @abstractmethod
    def enter_frame(self, locator: Any) -> Any: ...
