"""``save_as``: a read's rows become flow data for the steps after it."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from llm_browser.flows import load_flow_document, run_flow
from llm_browser.models import FlowError, FlowSuccess

PAGER = [
    {"href": "page-1.html", "label": "previous"},
    {"href": "page-3.html", "label": "next"},
]
EXTRACT = {"href": {"attribute": "href"}, "label": {"attribute": "textContent"}}


def _read(save_as: Any, **extra: Any) -> dict[str, Any]:
    return {
        "name": "links",
        "action": "read",
        "selector": "a",
        "extract": EXTRACT,
        "save_as": save_as,
        **extra,
    }


def _goto(url: str, **extra: Any) -> dict[str, Any]:
    return {"name": "open", "action": "goto", "url": url, **extra}


def _dom(path: str) -> dict[str, Any]:
    return {"name": "page", "action": "dom", "selector": "#main", "path": path}


def _run(session: MagicMock, steps: list[dict[str, Any]], **data: object) -> Any:
    session.parse_elements.return_value = PAGER
    flow = load_flow_document({"params": list(data), "steps": steps})
    return run_flow(session, flow, data)


def _urls(session: MagicMock) -> list[str]:
    return [call.args[0] for call in session.goto.call_args_list]


# --- what a save binds ---


@pytest.mark.parametrize(
    ("save_as", "template", "url"),
    [
        ("links", "{{ links.1.href }}", "page-3.html"),
        ({"name": "first", "field": "href"}, "{{ first }}", "page-1.html"),
        (
            {"name": "nxt", "field": "href", "where": {"label": "next"}},
            "{{ nxt }}",
            "page-3.html",
        ),
    ],
)
def test_a_later_template_reads_the_saved_value(
    mock_session: MagicMock, save_as: Any, template: str, url: str
) -> None:
    result = _run(mock_session, [_read(save_as), _goto(f"https://x/{template}")])
    assert isinstance(result, FlowSuccess)
    assert _urls(mock_session) == [f"https://x/{url}"]
    assert result.outputs["links"] == PAGER


@pytest.mark.parametrize(
    ("save_as", "rows", "message"),
    [
        ({"name": "v", "field": "href"}, [], "row 0 of 0 rows has no 'href'"),
        (
            {"name": "v", "field": "href"},
            [{"href": None, "label": "a"}, {"href": "b.html", "label": "b"}],
            "row 0 of 2 rows has no 'href'",
        ),
        (
            {"name": "v", "field": "href", "where": {"label": "last"}},
            PAGER,
            "where {'label': 'last'}",
        ),
    ],
)
def test_a_scalar_no_row_yields_fails_the_step(
    mock_session: MagicMock, save_as: Any, rows: list[Any], message: str
) -> None:
    mock_session.parse_elements.return_value = rows
    flow = load_flow_document({"steps": [_read(save_as), _goto("https://x/{{ v }}")]})
    result = run_flow(mock_session, flow, {})
    assert isinstance(result, FlowError)
    assert result.step == "links"
    assert message in str(result.data)
    mock_session.goto.assert_not_called()


def test_when_reads_a_saved_scalar(mock_session: MagicMock) -> None:
    save_as = {"name": "label", "field": "label"}
    when = [{"field": "label", "op": "eq", "value": "next"}]
    steps = [_read(save_as), _goto("https://x/a", when=when)]
    result = _run(mock_session, steps)
    assert isinstance(result, FlowSuccess)
    assert [s.name for s in result.skipped] == ["open"]


def test_a_skipped_read_saves_nothing(mock_session: MagicMock) -> None:
    when = [{"field": "wanted", "op": "is_truthy"}]
    steps = [
        _read({"name": "v", "field": "href"}, when=when),
        _goto("https://x/{{ v }}"),
    ]
    result = _run(mock_session, steps, wanted=False)
    assert isinstance(result, FlowSuccess)
    assert _urls(mock_session) == ["https://x/{{ v }}"]


# --- repeat over a saved list ---


def _each(steps: list[dict[str, Any]], over: str = "links") -> dict[str, Any]:
    return {
        "name": "each",
        "action": "run-flow",
        "repeat": {"over": over, "as": "item"},
        "flow": {"steps": steps},
    }


def test_repeat_runs_one_pass_per_saved_row(mock_session: MagicMock) -> None:
    steps = [_read("links"), _each([_goto("https://x/{{ item.href }}")])]
    result = _run(mock_session, steps)
    assert isinstance(result, FlowSuccess)
    assert _urls(mock_session) == ["https://x/page-1.html", "https://x/page-3.html"]


def test_a_saved_list_with_no_rows_runs_no_passes(mock_session: MagicMock) -> None:
    mock_session.parse_elements.return_value = []
    steps = [_read("links"), _each([_goto("https://x/{{ item.href }}")])]
    result = run_flow(mock_session, load_flow_document({"steps": steps}), {})
    assert isinstance(result, FlowSuccess)
    assert result.outputs == {"links": []}
    mock_session.goto.assert_not_called()


def test_a_save_inside_a_pass_stays_in_that_pass(mock_session: MagicMock) -> None:
    inner = {**_read({"name": "mine", "field": "href"}), "name": "inner"}
    steps = [
        _each([inner, _goto("https://x/{{ mine }}")], over="codes"),
        {**_goto("https://x/after/{{ mine }}"), "name": "after"},
    ]
    result = _run(mock_session, steps, codes=["a", "b"])
    assert isinstance(result, FlowSuccess)
    assert _urls(mock_session) == [
        "https://x/page-1.html",
        "https://x/page-1.html",
        "https://x/after/{{ mine }}",
    ]


def test_a_saved_value_feeds_a_sub_flow_data_binding(mock_session: MagicMock) -> None:
    child = {
        "name": "child",
        "action": "run-flow",
        "data": {"target": "{{ next_href }}"},
        "flow": {"steps": [_goto("https://x/{{ target }}")]},
    }
    save_as = {"name": "next_href", "field": "href", "where": {"label": "next"}}
    result = _run(mock_session, [_read(save_as), child])
    assert isinstance(result, FlowSuccess)
    assert _urls(mock_session) == ["https://x/page-3.html"]


def test_a_dotted_path_to_nothing_fails_the_pass_it_is_in(
    mock_session: MagicMock,
) -> None:
    steps = [_read("links"), _each([_goto("https://x/{{ item.nope }}")])]
    result = _run(mock_session, steps)
    assert isinstance(result, FlowError)
    assert result.step == "each/open[0]"
    assert "'item.nope' resolves to nothing" in str(result.data)
    assert list(result.outputs) == ["links"]


# --- load-time rejections ---


@pytest.mark.parametrize(
    ("document", "message"),
    [
        (
            {"params": ["links"], "steps": [_read("links")]},
            "shadows a param or another save_as",
        ),
        (
            {"steps": [_read("links"), {**_read("links"), "name": "again"}]},
            "shadows a param or another save_as",
        ),
        (
            {"steps": [_read("links"), _each([{**_read("links"), "name": "in"}])]},
            "in sub-flow 'each' shadows",
        ),
        (
            {"params": ["codes"], "steps": [_each([_read("item")], over="codes")]},
            "in sub-flow 'each' shadows",
        ),
        (
            {"steps": [_goto("https://x/{{ links.0.href }}"), _read("links")]},
            "uses ['links'] before the step that saves it",
        ),
        (
            {"steps": [_each([_goto("https://x/{{ item }}")]), _read("links")]},
            "uses ['links'] before the step that saves it",
        ),
        (
            {"steps": [_read("links", selector="#{{ links }}")]},
            "uses ['links'] before the step that saves it",
        ),
        (
            {"steps": [_read({"name": "v", "field": "title"})]},
            "not among the extracted fields",
        ),
        (
            {"steps": [_read({"name": "v", "field": "href", "where": {"x": "1"}})]},
            "not among the extracted fields",
        ),
        ({"steps": [_read({"name": "v", "where": {"label": "next"}})]}, "name one"),
        ({"steps": [_read("not a name")]}, "String should match pattern"),
        (
            {
                "params": ["codes"],
                "steps": [_read("links", repeat={"over": "codes", "as": "code"})],
            },
            "save_as on a repeated step is never visible",
        ),
        (
            {
                "params": ["codes"],
                "steps": [_read("item"), _each([_goto("https://x/a")], over="codes")],
            },
            "binds ['item'] as its repeat item",
        ),
        (
            {
                "params": ["codes"],
                "steps": [
                    _read("item_index"),
                    _each([_goto("https://x/a")], over="codes"),
                ],
            },
            "binds ['item_index'] as its repeat item",
        ),
        (
            {
                "params": ["codes"],
                "steps": [
                    _read("item"),
                    {**_goto("https://x/a"), "repeat": {"over": "codes", "as": "item"}},
                ],
            },
            "binds ['item'] as its repeat item",
        ),
        (
            {"steps": [_read("links"), _dom("out/{{ links }}.html")]},
            "names ['links'] in a path:",
        ),
        (
            {"steps": [_read("links"), _each([_dom("out/{{ links }}.html")])]},
            "names ['links'] in a path:",
        ),
    ],
)
def test_load_rejects(document: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        load_flow_document(document)
    assert message in str(excinfo.value)
