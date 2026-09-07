"""Driver-level row extraction: one page evaluation, with a per-element fallback."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser.drivers.base import Driver
from llm_browser.drivers.patchright import PatchrightDriver
from llm_browser.scripts import extract_rows_js

SPEC: dict[str, dict[str, str | None]] = {
    "name": {"child_selector": "td.name", "attribute": "textContent"},
    "url": {"child_selector": "a", "attribute": "href"},
    "qty": {"child_selector": "input", "attribute": "value"},
    "id": {"child_selector": None, "attribute": "data-id"},
}


def test_playwright_extract_rows_uses_one_evaluate_all() -> None:
    locator = MagicMock()
    locator.evaluate_all.return_value = [{"name": "Alice"}]
    rows = PatchrightDriver().extract_rows(locator, SPEC)
    assert rows == [{"name": "Alice"}]
    locator.evaluate_all.assert_called_once_with(extract_rows_js(), SPEC)


class FallbackDriver(Driver):
    """Minimal driver exercising the base per-element extract_rows."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def all(self, locator: Any) -> list[Any]:
        return self.rows

    def child(self, locator: Any, selector: str) -> Any:
        return locator.children.get(selector)

    def text_content(self, locator: Any) -> str | None:
        return None if locator is None else locator.text

    def input_value(self, locator: Any) -> str:
        return "" if locator is None else locator.value

    def get_attribute(self, locator: Any, name: str) -> str | None:
        return None if locator is None else locator.attrs.get(name)

    def __getattr__(self, name: str) -> Any:  # unused abstract members
        raise NotImplementedError(name)


class FakeElement:
    def __init__(
        self,
        text: str | None = None,
        value: str = "",
        attrs: dict[str, str] | None = None,
        children: dict[str, "FakeElement"] | None = None,
    ) -> None:
        self.text = text
        self.value = value
        self.attrs = attrs or {}
        self.children = children or {}


FallbackDriver.__abstractmethods__ = frozenset()  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("name", "Alice"),
        ("url", "/alice"),
        ("qty", "3"),
        ("id", "r1"),
        ("missing", None),
    ],
)
def test_fallback_extract_rows_reads_each_attribute_kind(
    field: str, expected: str | None
) -> None:
    row = FakeElement(
        attrs={"data-id": "r1"},
        children={
            "td.name": FakeElement(text="Alice"),
            "a": FakeElement(attrs={"href": "/alice"}),
            "input": FakeElement(value="3"),
        },
    )
    spec = dict(SPEC)
    spec["missing"] = {"child_selector": "td.gone", "attribute": "textContent"}
    rows = FallbackDriver([row]).extract_rows(MagicMock(), spec)
    assert rows[0][field] == expected
