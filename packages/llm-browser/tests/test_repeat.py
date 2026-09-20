"""The repeat block: its sources, its element scoping, its report, its rerun."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

from llm_browser.cli import authored_subflows, parse_only
from llm_browser.flows import run_flow
from llm_browser.models import Flow, FlowError, FlowSuccess
from llm_browser.selectors import ScopedSelector
from tests.flow_helpers import run_flow_file


def write_flow(
    tmp_path: Path, steps: list[dict[str, Any]], name: str = "flow.yaml", **rest: Any
) -> Path:
    path = tmp_path / name
    path.write_text(yaml.dump({"steps": steps, **rest}))
    return path


def grab(**extra: Any) -> dict[str, Any]:
    return {"name": "grab", "action": "dom", "selector": "#panel", **extra}


def block(**extra: Any) -> dict[str, Any]:
    """``as_`` spells the block's ``as:``, which Python will not take."""
    bind = extra.pop("as_", "code")
    return {
        "name": "each",
        "action": "repeat",
        "as": bind,
        "steps": [grab(selector="#p-{{ code }}")],
        **extra,
    }


# --- block form ---


def test_the_block_form_is_the_modifier_form(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    """Same flow, written both ways: one engine, one set of outputs."""
    sugared = write_flow(tmp_path, [block(over="codes")], params=["codes"])
    hand_written = write_flow(
        tmp_path,
        [
            {
                "name": "each",
                "action": "run-flow",
                "repeat": {"over": "codes", "as": "code"},
                "flow": {"steps": [grab(selector="#p-{{ code }}")]},
            }
        ],
        name="modifier.yaml",
        params=["codes"],
    )
    data = {"codes": ["a", "b"]}
    from_block = run_flow_file(mock_session, sugared, data)
    from_modifier = run_flow_file(mock_session, hand_written, data)
    assert isinstance(from_block, FlowSuccess)
    assert isinstance(from_modifier, FlowSuccess)
    assert list(from_block.outputs) == ["each/grab[0]", "each/grab[1]"]
    assert from_block.outputs == from_modifier.outputs
    assert from_block.iterations == from_modifier.iterations


def test_an_inline_list_needs_no_param(tmp_path: Path, mock_session: MagicMock) -> None:
    path = write_flow(tmp_path, [block(over=["a", "b", "c"])])
    result = run_flow_file(mock_session, path, {})
    assert isinstance(result, FlowSuccess)
    assert [call.args[0] for call in mock_session.dom.call_args_list] == [
        "#p-a",
        "#p-b",
        "#p-c",
    ]


@pytest.mark.parametrize(
    ("step", "message"),
    [
        (block(), "exactly one of `over` or `over_selector`"),
        (
            block(over="codes", over_selector="tr"),
            "exactly one of `over` or `over_selector`",
        ),
        (block(over="codes", steps=[]), "at least 1 item"),
        (
            block(
                over="codes", steps=[{"name": "n", "action": "run-flow", "flow": {}}]
            ),
            "may not be a `run-flow`",
        ),
        (
            block(over="codes", steps=[{"name": "n", "action": "repeat"}]),
            "may not be a `run-flow`",
        ),
        (
            block(
                over="codes",
                steps=[grab(repeat={"over": "inner", "as": "one"})],
            ),
            "may not be a `run-flow`",
        ),
        (
            block(over="codes", steps=[grab(**{"in": "code"})]),
            "not inside a repeat over `over_selector`",
        ),
        (
            block(over_selector="tr", steps=[grab(**{"in": "other"})]),
            "the repeat binds 'code'",
        ),
        (
            block(
                over_selector="tr",
                steps=[{"name": "n", "action": "think", "in": "code"}],
            ),
            "names no selector",
        ),
        (grab(**{"in": "row"}), "not inside a repeat"),
    ],
)
def test_a_repeat_is_rejected_at_load(step: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Flow.model_validate({"params": ["codes"], "steps": [step]})


# --- on_error and the report ---


def test_skip_keeps_the_passes_around_the_failed_one(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    mock_session.dom.side_effect = ["one", TimeoutError("never rendered"), "three"]
    path = write_flow(
        tmp_path, [block(over="codes", on_error="skip")], params=["codes"]
    )
    result = run_flow_file(mock_session, path, {"codes": ["a", "b", "c"]})
    assert isinstance(result, FlowSuccess)
    assert list(result.outputs) == ["each/grab[0]", "each/grab[2]"]
    assert [s.name for s in result.skipped] == ["each[1]"]


def test_a_failed_pass_is_reported_in_full(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    mock_session.dom.side_effect = ["one", TimeoutError("never rendered")]
    path = write_flow(
        tmp_path, [block(over="codes", on_error="skip")], params=["codes"]
    )
    result = run_flow_file(mock_session, path, {"codes": ["a", "b"]})
    assert isinstance(result, FlowSuccess)
    report = result.iterations["each"]
    assert (report.total, report.ok, report.over) == (2, 1, "codes")
    [failure] = report.failed
    assert failure.index == 1
    assert failure.item == "b"
    assert failure.step == "each/grab[1]"
    assert failure.error == "TimeoutError"
    assert failure.message == "never rendered"
    assert failure.selector == repr("#p-b")
    assert failure.hint is not None
    assert failure.url == "https://example.test/page"
    assert failure.screenshot is not None


def test_stop_is_the_default_and_still_reports_the_failure(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    mock_session.dom.side_effect = ["one", TimeoutError("never rendered")]
    path = write_flow(tmp_path, [block(over="codes")], params=["codes"])
    result = run_flow_file(mock_session, path, {"codes": ["a", "b", "c"]})
    assert isinstance(result, FlowError)
    assert result.step == "each/grab[1]"
    assert list(result.outputs) == ["each/grab[0]"]
    report = result.iterations["each"]
    assert (report.total, report.ok) == (3, 1)
    assert [f.index for f in report.failed] == [1]


def test_a_repeat_with_nothing_to_do_reports_zero(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    mock_session.parse_elements.return_value = []
    path = write_flow(tmp_path, [block(over_selector="tr.athing")])
    result = run_flow_file(mock_session, path, {})
    assert isinstance(result, FlowSuccess)
    assert result.iterations["each"].total == 0


# --- over_selector and `in:` ---


def element_rows(*texts: str) -> list[dict[str, str]]:
    return [{"text": text} for text in texts]


def test_a_pass_binds_the_elements_snippet_and_index(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    mock_session.parse_elements.return_value = element_rows("  Alpha\n row ", "Beta")
    path = write_flow(
        tmp_path,
        [
            block(
                over_selector="tr.athing",
                as_="row",
                steps=[grab(selector="#{{ row }}-{{ row_index }}")],
            )
        ],
    )
    run_flow_file(mock_session, path, {})
    assert [call.args[0] for call in mock_session.dom.call_args_list] == [
        "#Alpha row-0",
        "#Beta-1",
    ]


def test_in_scopes_a_read_to_its_own_element(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    mock_session.parse_elements.side_effect = [
        element_rows("row one", "row two"),
        [{"title": "one"}],
        [{"title": "two"}],
    ]
    path = write_flow(
        tmp_path,
        [
            block(
                over_selector="tr.athing",
                as_="row",
                steps=[
                    {
                        "name": "title",
                        "action": "read",
                        "in": "row",
                        "selector": ".titleline a",
                    }
                ],
            )
        ],
    )
    result = run_flow_file(mock_session, path, {})
    assert isinstance(result, FlowSuccess)
    assert list(result.outputs) == ["each/title[0]", "each/title[1]"]
    scoped = [call.args[0] for call in mock_session.parse_elements.call_args_list[1:]]
    assert scoped == [
        ScopedSelector(root="tr.athing", index=0, inner=".titleline a"),
        ScopedSelector(root="tr.athing", index=1, inner=".titleline a"),
    ]


def test_a_scoped_read_that_finds_nothing_fails_its_pass(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    mock_session.parse_elements.side_effect = [element_rows("row one"), []]
    path = write_flow(
        tmp_path,
        [
            block(
                over_selector="tr.athing",
                as_="row",
                on_error="skip",
                steps=[
                    {"name": "title", "action": "read", "in": "row", "selector": "a"}
                ],
            )
        ],
    )
    result = run_flow_file(mock_session, path, {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {}
    [failure] = result.iterations["each"].failed
    assert "read found nothing at tr.athing[0] a" in failure.message


# --- rerun ---


@pytest.mark.parametrize(
    ("step", "data", "items", "only", "not_run", "expected_type"),
    [
        # A list param reruns by data; `skip` runs every pass, so none is left.
        (
            block(over="codes", on_error="skip"),
            {"codes": ["a", "b"]},
            ["b"],
            {},
            [],
            FlowSuccess,
        ),
        # `stop` never reached c and d, and they belong to the rerun too.
        (
            block(over="codes"),
            {"codes": ["a", "b", "c", "d"]},
            ["b", "c", "d"],
            {},
            [2, 3],
            FlowError,
        ),
        # Only an index addresses an inline list entry.
        (
            block(over=["a", "b"], on_error="skip"),
            {},
            None,
            {"each": [1]},
            [],
            FlowSuccess,
        ),
        (
            block(over=["a", "b", "c", "d"]),
            {},
            None,
            {"each": [1, 2, 3]},
            [2, 3],
            FlowError,
        ),
    ],
)
def test_the_rerun_hint_names_every_unfinished_pass(
    tmp_path: Path,
    mock_session: MagicMock,
    step: dict[str, Any],
    data: dict[str, object],
    items: list[str] | None,
    only: dict[str, list[int]],
    not_run: list[int],
    expected_type: type,
) -> None:
    mock_session.dom.side_effect = ["one", TimeoutError("never rendered")]
    path = write_flow(tmp_path, [step], params=list(data))
    result = run_flow_file(mock_session, path, data)
    assert isinstance(result, expected_type)
    assert result.retry_hint is not None
    assert result.retry_hint.only == only
    assert result.retry_hint.failed_step == "each"
    assert result.retry_hint.flow_path == str(path.resolve())
    assert result.iterations["each"].not_run == not_run
    if items is not None:
        assert result.retry_hint.data["codes"] == items


def test_a_clean_run_carries_no_retry_hint(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    path = write_flow(tmp_path, [block(over=["a"])])
    result = run_flow_file(mock_session, path, {})
    assert isinstance(result, FlowSuccess)
    assert result.retry_hint is None


def test_only_runs_the_passes_it_names(tmp_path: Path, mock_session: MagicMock) -> None:
    """The indices are the original ones, so a rerun's outputs line up with
    the run they came from."""
    path = write_flow(tmp_path, [block(over=["a", "b", "c"])])
    flow = Flow.model_validate(yaml.safe_load(path.read_text()))
    result = run_flow(mock_session, flow, {}, only={"each": [1, 2]})
    assert isinstance(result, FlowSuccess)
    assert list(result.outputs) == ["each/grab[1]", "each/grab[2]"]
    assert [call.args[0] for call in mock_session.dom.call_args_list] == [
        "#p-b",
        "#p-c",
    ]


def nested_repeat_flow(on_error: str = "skip") -> dict[str, Any]:
    """A repeating step inside a hand-written `run-flow` — the one nesting the
    block form rejects, and the one whose report has to reach the parent."""
    return {
        "name": "outer",
        "action": "run-flow",
        "flow": {
            "steps": [
                grab(
                    selector="#p-{{ code }}",
                    repeat={"over": "codes", "as": "code", "on_error": on_error},
                )
            ]
        },
    }


def test_a_repeat_loops_a_saved_read(tmp_path: Path, mock_session: MagicMock) -> None:
    """`save_as` (#61) feeds `over` (#60): any list in flow data loops."""
    mock_session.parse_elements.return_value = [{"href": "a.html"}, {"href": "b.html"}]
    path = write_flow(
        tmp_path,
        [
            {
                "name": "books",
                "action": "read",
                "selector": "h3 a",
                "extract": {"href": "@href"},
                "save_as": "books",
            },
            block(
                over="books",
                as_="book",
                steps=[
                    {
                        "name": "open",
                        "action": "goto",
                        "url": "https://x/{{ book.href }}",
                    }
                ],
            ),
        ],
    )
    result = run_flow_file(mock_session, path, {})
    assert isinstance(result, FlowSuccess)
    assert [call.args[0] for call in mock_session.goto.call_args_list] == [
        "https://x/a.html",
        "https://x/b.html",
    ]
    assert result.iterations["each"].total == 2


def test_a_repeating_step_inside_a_subflow_reports_and_hints(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    mock_session.dom.side_effect = ["one", TimeoutError("never rendered"), "three"]
    path = write_flow(tmp_path, [nested_repeat_flow()], params=["codes"])
    result = run_flow_file(mock_session, path, {"codes": ["a", "b", "c"]})
    assert isinstance(result, FlowSuccess)
    report = result.iterations["outer/grab"]
    assert (report.total, report.ok) == (3, 2)
    [failure] = report.failed
    assert (failure.index, failure.item, failure.step) == (1, "b", "outer/grab[1]")
    assert failure.message == "never rendered"
    assert result.retry_hint is not None
    assert result.retry_hint.data["codes"] == ["b"]
    # `--from` resumes the top-level step, not the child that failed.
    assert result.retry_hint.failed_step == "outer"


def test_only_reaches_a_repeating_step_inside_a_subflow(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    """`only` is keyed the way a report is: the step's qualified name."""
    path = write_flow(tmp_path, [nested_repeat_flow()], params=["codes"])
    flow = Flow.model_validate(yaml.safe_load(path.read_text()))
    result = run_flow(
        mock_session, flow, {"codes": ["a", "b", "c"]}, only={"outer/grab": [2]}
    )
    assert isinstance(result, FlowSuccess)
    assert list(result.outputs) == ["outer/grab[2]"]
    assert result.iterations["outer/grab"].total == 1


def test_a_stopped_subflow_still_hands_its_report_up(
    tmp_path: Path, mock_session: MagicMock
) -> None:
    mock_session.dom.side_effect = ["one", TimeoutError("never rendered")]
    path = write_flow(tmp_path, [nested_repeat_flow(on_error="stop")], params=["codes"])
    result = run_flow_file(mock_session, path, {"codes": ["a", "b", "c"]})
    assert isinstance(result, FlowError)
    report = result.iterations["outer/grab"]
    assert [f.index for f in report.failed] == [1]
    assert report.not_run == [2]


def test_authored_subflows_does_not_count_a_desugared_block() -> None:
    document = {"steps": [block(over=["a"]), {"action": "run-flow", "flow": {}}]}
    assert authored_subflows(document) == 1


@pytest.mark.parametrize(
    ("specs", "expected"),
    [
        ((), None),
        (("each=1",), {"each": [1]}),
        (("each=1,3", "other=0"), {"each": [1, 3], "other": [0]}),
    ],
)
def test_only_is_parsed_from_the_command_line(
    specs: tuple[str, ...], expected: dict[str, list[int]] | None
) -> None:
    assert parse_only(specs) == expected


@pytest.mark.parametrize("spec", ["each", "each=", "=1", "each=x"])
def test_a_malformed_only_is_an_argument_error(spec: str) -> None:
    with pytest.raises(Exception, match="--only"):
        parse_only((spec,))
