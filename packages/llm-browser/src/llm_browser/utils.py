"""Shared utilities for browser field interaction."""

from playwright.sync_api import Page

from llm_browser.scripts import load_js


def field_selector(field: dict[str, object]) -> tuple[str, str]:
    """Extract element ID and CSS selector from a field dict."""
    el_id = str(field["id"])
    return el_id, f'[id="{el_id}"]'


def js_clear_field(page: Page, el_id: str, focus: bool = False) -> None:
    """Clear a field's value via JS and dispatch input event."""
    page.evaluate(load_js("clear_field"), {"id": el_id, "focus": focus})
