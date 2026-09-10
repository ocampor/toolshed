"""Running a fixture flow and reading what it produced.

Step scenarios drive the library the way a caller does — a YAML flow on a
launched session — so the assertions are about ``FlowSuccess.outputs`` and
``FlowError.step``, not about driver primitives.
"""

from typing import Any

from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowSuccess

from llm_browser_conformance.scenario import Context


def run(ctx: Context, page: str, flow: str, **data: object) -> FlowSuccess | FlowError:
    ctx.visit(page)
    result = run_flow(ctx.session, ctx.flow(flow), data)
    assert isinstance(result, FlowSuccess | FlowError), result
    return result


def expect_success(
    ctx: Context, page: str, flow: str, **data: object
) -> dict[str, object]:
    result = run(ctx, page, flow, **data)
    assert isinstance(result, FlowSuccess), f"{result.step}: {result.data}"
    return result.outputs


def expect_failure(ctx: Context, page: str, flow: str, **data: object) -> FlowError:
    result = run(ctx, page, flow, **data)
    assert isinstance(result, FlowError), f"expected a failure, got {result.outputs}"
    return result


def error_message(failure: FlowError) -> str:
    """``FlowError.data`` is the ``ErrorResult`` the failing action returned."""
    return str(getattr(failure.data, "message", failure.data))


def texts(outputs: dict[str, object], step: str) -> list[str | None]:
    """The ``text`` field of every row a ``read`` step produced."""
    rows: Any = outputs[step]
    return [None if row is None else row["text"] for row in rows]


def one_text(outputs: dict[str, object], step: str) -> str | None:
    values = texts(outputs, step)
    assert len(values) == 1, f"{step} matched {len(values)} elements"
    return values[0]
