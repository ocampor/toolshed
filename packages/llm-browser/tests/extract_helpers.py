"""Rows a typed read sees and returns, shared by the read and explore tests."""

from unittest.mock import MagicMock

from llm_browser.constants import META_KEY
from llm_browser.session import BrowserSession


def serve_rows(session: BrowserSession, rows: list[dict[str, str | None]]) -> None:
    locator = MagicMock()
    locator.evaluate_all.return_value = rows
    session._page.locator.return_value = locator  # type: ignore[union-attr]


# What a typed read returns for CARDS, and so what explore must preview.
CARDS = [
    {".price": "MN 48,500", ".label": "Casa 3 rec"},
    {".price": "Consultar precio", ".label": "Casa"},
]
CARD_EXTRACT = {
    "price": {
        "child_selector": ".price",
        "pattern": r"([\d,]+)",
        "type": "int",
        "required": True,
    },
    "rooms": {"child_selector": ".label", "pattern": r"(\d+) baños"},
}
TYPED_CARDS = [
    {"price": 48500, "rooms": None},
    {
        "price": None,
        "rooms": None,
        META_KEY: {
            "incomplete": True,
            "reasons": [
                r"price: required, no match for pattern '([\\d,]+)' in 'Consultar precio'"
            ],
        },
    },
]
