import contextlib
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from llm_browser.flows import run_flow
from llm_browser.models import Flow, FlowError, FlowSuccess
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


def expect_flow_success(ctx: Context, flow: Flow, **data: object) -> dict[str, object]:
    """For a check that splits a fixture flow into separately timed halves."""
    result = run_flow(ctx.session, flow, data)
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
    rows: Any = outputs[step]
    return [None if row is None else row["text"] for row in rows]


def one_text(outputs: dict[str, object], step: str) -> str | None:
    values = texts(outputs, step)
    assert len(values) == 1, f"{step} matched {len(values)} elements"
    return values[0]


def file_stats(directory: Path) -> list[tuple[str, int, int]]:
    """Stats, not names: the likeliest regression overwrites a file that already existed."""
    if not directory.exists():
        return []
    return sorted(
        (path.name, path.stat().st_size, path.stat().st_mtime_ns)
        for path in directory.iterdir()
        if path.is_file()
    )


def artifact_snapshot(session: BrowserSession) -> list[tuple[str, int, int]]:
    """Top level only: ``user-data/`` is the live profile the browser writes constantly."""
    return file_stats(session.session_dir)


def cwd_snapshot() -> list[tuple[str, int, int]]:
    return file_stats(Path.cwd())


@contextlib.contextmanager
def wrote_nothing(ctx: Context) -> Iterator[None]:
    before_session = artifact_snapshot(ctx.session)
    before_cwd = cwd_snapshot()
    yield
    assert artifact_snapshot(ctx.session) == before_session, "wrote into session dir"
    assert cwd_snapshot() == before_cwd, "wrote into the working directory"
