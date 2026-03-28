"""Action registry scaffold — consumers register their own domain-specific actions."""

from functools import lru_cache
from typing import Callable

from yaml_engine.registry import Registry

ActionFn = Callable[..., None]


@lru_cache(maxsize=1)
def get_registry() -> Registry[ActionFn]:
    return Registry("action")


register_action = get_registry().register


def execute_action(op: str, record: dict[str, object], param: object) -> None:
    """Execute an action against a record (mutates in-place)."""
    get_registry().get(op)(record, param)
