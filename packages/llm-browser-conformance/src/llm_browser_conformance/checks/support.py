"""Running a fixture flow and reading what it produced.

Step scenarios drive the library the way a caller does — a YAML flow on a
launched session — so the assertions are about ``FlowSuccess.outputs`` and
``FlowError.step``, not about driver primitives.
"""

import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from llm_browser.flows import run_flow
from llm_browser.models import FlowError, FlowSuccess
from llm_browser.session import BrowserSession

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


def file_stats(directory: Path) -> list[tuple[str, int, int]]:
    """Every top-level file in ``directory``, with the stats that would change
    if something rewrote one.

    Name alone is not enough: a flow's ``path:`` values are relative names, so
    the likeliest regression is a runner *overwriting* a file that was already
    there, which a set of names cannot see. A directory that does not exist
    yet has no files, which is the same answer as an empty one.
    """
    if not directory.exists():
        return []
    return sorted(
        (path.name, path.stat().st_size, path.stat().st_mtime_ns)
        for path in directory.iterdir()
        if path.is_file()
    )


def artifact_snapshot(session: BrowserSession) -> list[tuple[str, int, int]]:
    """The files the session has in its own dir.

    Only the top level: ``user-data/`` is the live profile and the browser
    writes into it constantly.
    """
    return file_stats(session.session_dir)


def cwd_snapshot() -> list[tuple[str, int, int]]:
    return file_stats(Path.cwd())


@contextlib.contextmanager
def wrote_nothing(ctx: Context) -> Iterator[None]:
    """The library never writes output files, so neither the session dir nor
    the working directory may gain or change one while the body runs."""
    before_session = artifact_snapshot(ctx.session)
    before_cwd = cwd_snapshot()
    yield
    assert artifact_snapshot(ctx.session) == before_session, "wrote into session dir"
    assert cwd_snapshot() == before_cwd, "wrote into the working directory"
