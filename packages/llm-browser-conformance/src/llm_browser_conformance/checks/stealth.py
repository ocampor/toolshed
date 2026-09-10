"""Stealth accounting for nodriver: how much Runtime traffic a wait costs.

Driver rule 3 says JS runs in ``evaluate``, ``is_visible``, ``input_value``
and ``extract_rows`` and nowhere else, so a detector fingerprinting CDP
Runtime traffic sees nothing on the common path. That is only checkable on a
driver that speaks CDP itself, which is nodriver.
"""

import importlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from llm_browser_conformance.scenario import Context, Scenario, Section

NODRIVER = frozenset({"nodriver"})


@contextmanager
def recorded_cdp_methods() -> Iterator[list[str]]:
    """Every CDP method this process sends while the block runs.

    Hooked on ``Transaction``, which nodriver builds for each outgoing
    command: it already parses the method name off the command generator, so a
    websocket-level hook would only have to re-parse the JSON.
    """
    connection = importlib.import_module("nodriver.core.connection")
    sent: list[str] = []
    original_init = connection.Transaction.__init__

    def recording_init(self: Any, cdp_obj: Any) -> None:
        original_init(self, cdp_obj)
        sent.append(str(self.method))

    connection.Transaction.__init__ = recording_init
    try:
        yield sent
    finally:
        connection.Transaction.__init__ = original_init


def runtime_methods(sent: list[str]) -> list[str]:
    return [method for method in sent if method.startswith("Runtime.")]


def attached_polls_without_touching_the_runtime_domain(ctx: Context) -> str:
    """``attached``/``detached`` go through ``count``, a plain DOM query."""
    ctx.visit("attached.html")
    with recorded_cdp_methods() as sent:
        ctx.wait_now("#late", "attached")
        calls = runtime_methods(sent)
    # Without this the assertion below is vacuous: a hook that recorded
    # nothing would report a clean run while measuring nothing at all.
    assert sent, "no CDP traffic was recorded; the Transaction hook missed"
    assert calls == [], calls
    return f"{len(sent)} CDP calls, 0 Runtime"


def visible_costs_at_most_one_runtime_call_per_poll(ctx: Context) -> str:
    """``visible`` has no CDP predicate, so it pays one
    ``Runtime.callFunctionOn`` — but only one, and only per poll."""
    ctx.visit("visible.html")
    ticks = 0
    driver = ctx.session.driver
    original_is_visible = driver.is_visible

    def counting_is_visible(locator: Any) -> bool:
        nonlocal ticks
        ticks += 1
        return original_is_visible(locator)

    driver.is_visible = counting_is_visible  # type: ignore[method-assign]
    try:
        with recorded_cdp_methods() as sent:
            ctx.wait_now("#btn", "visible")
            calls = runtime_methods(sent)
    finally:
        del driver.is_visible
    assert sent, "no CDP traffic was recorded; the Transaction hook missed"
    assert ticks > 0
    assert len(calls) <= ticks, f"{len(calls)} Runtime calls over {ticks} polls"
    return f"{len(calls)} Runtime calls over {ticks} polls"


SCENARIOS = [
    Scenario(
        "attached sends no Runtime",
        Section.STEALTH,
        attached_polls_without_touching_the_runtime_domain,
        drivers=NODRIVER,
    ),
    Scenario(
        "visible costs one Runtime per poll",
        Section.STEALTH,
        visible_costs_at_most_one_runtime_call_per_poll,
        drivers=NODRIVER,
    ),
]
