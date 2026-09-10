"""Async CDP doubles shared by the nodriver and driver-contract tests."""

from typing import Any


class FakeElement:
    def __init__(self, visible: bool) -> None:
        self.visible = visible

    async def apply(self, script: str) -> bool:
        return self.visible


class DetachedElement:
    """A handle whose node the page already removed: CDP reads on it fail."""

    async def apply(self, script: str) -> bool:
        raise RuntimeError("Could not find node with given id")


class FakeTab:
    """Serves each queued query result in turn, repeating the last one."""

    def __init__(self, results: list[Any]) -> None:
        self.results = results
        self.select_all_calls: list[str] = []
        self.query_calls: list[str] = []

    async def query_selector_all(self, selector: str) -> list[Any]:
        self.query_calls.append(selector)
        found = self.next_result()
        if found is None:
            return []
        return found if isinstance(found, list) else [found]

    async def select_all(self, selector: str, timeout: float = 10) -> list[Any]:
        """Real nodriver retries in here — 500ms and a `Target.getTargets` per
        cycle — so no read on the wait path may reach this method at all."""
        self.select_all_calls.append(selector)
        return await self.query_selector_all(selector)

    def next_result(self) -> Any:
        return self.results.pop(0) if len(self.results) > 1 else self.results[0]
