"""Field type handlers for browser form automation.

Each handler takes a Playwright page and a field dict (from YAML),
executes the appropriate browser actions, and returns.
"""

import time
from functools import lru_cache
from typing import Callable

from playwright.sync_api import Page

from yaml_engine.registry import Registry

from llm_browser.scripts import load_js
from llm_browser.utils import field_selector, js_clear_field

FieldHandler = Callable[[Page, dict[str, object]], None]


@lru_cache(maxsize=1)
def get_registry() -> Registry[FieldHandler]:
    return Registry("field type")


register_field = get_registry().register


def execute_field(page: Page, field: dict[str, object]) -> None:
    """Dispatch a field dict to the appropriate handler."""
    get_registry().get(str(field["type"]))(page, field)


@register_field("text")
def fill_text(page: Page, field: dict[str, object]) -> None:
    """Fill a text input: click, optionally clear, then type."""
    el_id, selector = field_selector(field)
    if field.get("clear_first"):
        js_clear_field(page, el_id)
    page.click(selector)
    page.fill(selector, str(field["value"]))


@register_field("autocomplete")
def fill_autocomplete(page: Page, field: dict[str, object]) -> None:
    """Fill an autocomplete: JS clear -> click -> type search -> click option."""
    el_id, selector = field_selector(field)
    if field.get("clear_js", True):
        js_clear_field(page, el_id, focus=True)
    page.click(selector)
    page.type(selector, str(field["search"]), delay=50)
    time.sleep(1)  # wait for dropdown
    page.click(f"text={field['option']}")
    time.sleep(0.5)


@register_field("select")
def fill_select(page: Page, field: dict[str, object]) -> None:
    """Set a <select> dropdown value."""
    _, selector = field_selector(field)
    page.select_option(selector, str(field["value"]))


@register_field("checkbox")
def fill_checkbox(page: Page, field: dict[str, object]) -> None:
    """Set a checkbox, using UI click for DOM events when needed."""
    el_id, selector = field_selector(field)
    checked = bool(field.get("checked", True))
    current = page.evaluate(load_js("get_checked"), el_id)
    if current != checked:
        if field.get("ui_click", False):
            page.click(selector)
        else:
            page.evaluate(load_js("set_checked"), {"id": el_id, "checked": checked})
