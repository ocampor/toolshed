"""Generic registry for named items (conditions, actions, params, etc.)."""

from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class Registry(Generic[T]):
    """A named registry of items with decorator and direct registration."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.store: dict[str, T] = {}

    def register(self, name: str, item: T | None = None) -> T | Callable[[T], T]:
        """Register an item by name. Use as decorator or direct call.

        As decorator: @registry.register("name")
        Direct call:  registry.register("name", item)
        """
        if item is not None:
            self.store[name] = item
            return item

        def decorator(fn: T) -> T:
            self.store[name] = fn
            return fn
        return decorator

    def get(self, name: str) -> T:
        """Return the item for name, raising ValueError if not found."""
        item = self.store.get(name)
        if item is None:
            raise ValueError(f"Unknown {self.label}: {name!r}")
        return item

    def __contains__(self, name: str) -> bool:
        return name in self.store
