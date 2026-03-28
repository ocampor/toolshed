"""Generic registry for named callables (conditions, actions, etc.)."""

from typing import Callable, Generic, TypeVar

F = TypeVar("F", bound=Callable[..., object])


class Registry(Generic[F]):
    """A named registry of callables with a decorator for registration."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.store: dict[str, F] = {}

    def register(self, name: str) -> Callable[[F], F]:
        """Decorator: register a callable under the given name."""
        def decorator(fn: F) -> F:
            self.store[name] = fn
            return fn
        return decorator

    def get(self, name: str) -> F:
        """Return the callable for name, raising ValueError if not found."""
        fn = self.store.get(name)
        if fn is None:
            raise ValueError(f"Unknown {self.label}: {name!r}")
        return fn

    def __contains__(self, name: str) -> bool:
        return name in self.store
