"""Frames: entering a child document and driving it.

``enter_frame`` is optional in the driver contract, so a driver without it
skips rather than fails — that is the difference the table has to show.
"""

from typing import Any

from llm_browser_conformance.scenario import Context, Scenario, Section


def enter_frame_or_skip(ctx: Context, selector: str = "#frame") -> Any:
    try:
        return ctx.session.frame(selector)
    except NotImplementedError as exc:
        raise ctx.skip(str(exc)) from exc


def click_inside_an_iframe(ctx: Context) -> None:
    ctx.visit("iframe.html")
    frame = enter_frame_or_skip(ctx)
    button = ctx.session.driver.first(ctx.session.driver.resolve(frame, "#child-btn"))
    ctx.session.driver.click(button)
    assert ctx.session.driver.text_content(button) == "clicked"


SCENARIOS = [
    Scenario(
        "iframe click",
        Section.FRAMES,
        click_inside_an_iframe,
        covers=frozenset({"session:frame"}),
    ),
]
