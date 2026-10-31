from typing import Callable, Generic, TypeVar, overload

T = TypeVar("T")


class Registry(Generic[T]):
    def __init__(self, label: str) -> None:
        self.label = label
        self.store: dict[str, T] = {}

    @overload
    def register(self, name: str, item: T) -> T: ...

    @overload
    def register(self, name: str) -> Callable[[T], T]: ...

    def register(self, name: str, item: T | None = None) -> T | Callable[[T], T]:
        if item is not None:
            self.store[name] = item
            return item

        def decorator(fn: T) -> T:
            self.store[name] = fn
            return fn

        return decorator

    def get(self, name: str) -> T:
        """Raises ``ValueError`` for an unknown name."""
        item = self.store.get(name)
        if item is None:
            raise ValueError(f"Unknown {self.label}: {name!r}")
        return item

    def __contains__(self, name: str) -> bool:
        return name in self.store
