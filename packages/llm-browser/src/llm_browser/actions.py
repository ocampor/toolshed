"""Action registry: extensible step action handlers."""

from functools import lru_cache
from typing import Callable

from playwright.sync_api import Page

from yaml_engine.registry import Registry

from llm_browser.models import Step

ActionHandler = Callable[[Page, Step], None]


@lru_cache(maxsize=1)
def get_registry() -> Registry[ActionHandler]:
    return Registry("action")


register_action = get_registry().register


def execute_action(page: Page, step: Step) -> None:
    """Dispatch a step's action to the appropriate handler."""
    if step.action is None:
        return
    get_registry().get(step.action)(page, step)


@register_action("click")
def action_click(page: Page, step: Step) -> None:
    page.click(step.selector)


@register_action("dismiss_modal")
def action_dismiss_modal(page: Page, step: Step) -> None:
    selector = step.selector or ".modal.fade.in, .modal.show"
    if page.query_selector(selector):
        btn = page.query_selector(f"{selector} button")
        if btn:
            btn.click()
