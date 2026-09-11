"""The run command is what puts a flow's results on disk."""

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from llm_browser.cli import main
from llm_browser.models import FlowError, FlowResult, FlowSuccess
from llm_browser.results import BytesResult, ErrorResult

PNG = b"\x89PNG\r\n\x1a\nfake"

FLOW_YAML = """
steps:
  - name: shot
    action: screenshot
    path: captures/page.png
  - name: grab
    action: download
    selector: "#dl"
  - name: rows
    action: read
    selector: tr
    path: out/rows.json
  - name: snap
    action: dom
    selector: "#main"
"""

OUTPUTS: dict[str, object] = {
    "shot": BytesResult(name="shot.png", content=PNG, media_type="image/png"),
    "grab": BytesResult(name="report.csv", content=b"a,b\n", media_type="text/csv"),
    "rows": [{"title": "hello"}],
    "snap": "<p>hello</p>",
}


@pytest.fixture
def cli_run(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Any:
    """Invoke ``run`` on a flow whose result is handed in, in a scratch CWD."""
    monkeypatch.setattr("llm_browser.cli.build_session", _stub_session)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "flow.yml").write_text(FLOW_YAML)

    def invoke(result: FlowResult, *args: str) -> tuple[Any, Path]:
        monkeypatch.setattr("llm_browser.cli.run_cli_flow", lambda *a, **k: result)
        outcome = CliRunner().invoke(main, ["run", "--flow", "flow.yml", *args])
        return outcome, tmp_path

    return invoke


def _stub_session(**kwargs: object) -> Any:
    from unittest.mock import MagicMock

    from llm_browser.session import BrowserSession

    session = MagicMock(spec=BrowserSession)
    session.session_dir = Path("session")
    return session


def payload(outcome: Any) -> dict[str, Any]:
    return json.loads(outcome.stdout)  # type: ignore[no-any-return]


def test_declared_paths_receive_their_output(cli_run: Any) -> None:
    outcome, cwd = cli_run(FlowSuccess(step="snap", outputs=dict(OUTPUTS)))
    assert outcome.exit_code == 0
    assert (cwd / "captures" / "page.png").read_bytes() == PNG
    assert json.loads((cwd / "out" / "rows.json").read_text()) == [{"title": "hello"}]


def test_bytes_without_a_path_land_under_their_own_name(cli_run: Any) -> None:
    _outcome, cwd = cli_run(FlowSuccess(step="snap", outputs=dict(OUTPUTS)))
    assert (cwd / "report.csv").read_bytes() == b"a,b\n"


def test_out_dir_roots_every_written_path(cli_run: Any) -> None:
    _outcome, cwd = cli_run(
        FlowSuccess(step="snap", outputs=dict(OUTPUTS)), "--out-dir", "artifacts"
    )
    assert (cwd / "artifacts" / "captures" / "page.png").read_bytes() == PNG
    assert (cwd / "artifacts" / "report.csv").exists()


def test_written_bytes_are_reported_as_paths_not_base64(cli_run: Any) -> None:
    outcome, _cwd = cli_run(FlowSuccess(step="snap", outputs=dict(OUTPUTS)))
    outputs = payload(outcome)["outputs"]
    assert outputs["shot"] == str(Path("captures/page.png").resolve())
    assert outputs["grab"] == str(Path("report.csv").resolve())


def test_text_output_without_a_path_stays_in_the_json(cli_run: Any) -> None:
    outcome, cwd = cli_run(FlowSuccess(step="snap", outputs=dict(OUTPUTS)))
    assert payload(outcome)["outputs"]["snap"] == "<p>hello</p>"
    assert not (cwd / "snap.html").exists()


def _failure() -> FlowError:
    return FlowError(
        step="shot",
        data=ErrorResult(error="TimeoutError", message="nope", step_name="shot"),
        screenshot=PNG,
        dom="<html>failed</html>",
    )


def test_failure_captures_go_to_the_capture_dir(cli_run: Any) -> None:
    outcome, cwd = cli_run(_failure(), "--capture-dir", "diagnostics")
    assert outcome.exit_code == 1
    assert (cwd / "diagnostics" / "screenshot.png").read_bytes() == PNG
    assert (cwd / "diagnostics" / "dom.html").read_text() == "<html>failed</html>"


def test_failure_json_reports_the_capture_paths(cli_run: Any) -> None:
    outcome, cwd = cli_run(_failure(), "--capture-dir", "diagnostics")
    reported = payload(outcome)
    assert reported["screenshot"] == str(cwd / "diagnostics" / "screenshot.png")
    assert reported["dom"] == str(cwd / "diagnostics" / "dom.html")


def test_captures_default_to_the_session_dir(cli_run: Any) -> None:
    _outcome, cwd = cli_run(_failure())
    assert (cwd / "session" / "screenshot.png").read_bytes() == PNG


def test_a_step_named_screenshot_keeps_its_own_path(cli_run: Any) -> None:
    """The failure captures are keyed ``screenshot`` / ``dom`` at the top
    level; a step of the same name must not inherit their paths."""
    failure = _failure()
    failure.outputs["screenshot"] = BytesResult(name="step.png", content=PNG)
    outcome, cwd = cli_run(failure, "--capture-dir", "diagnostics")
    reported = payload(outcome)
    assert reported["outputs"]["screenshot"] == str(cwd / "step.png")
    assert reported["screenshot"] == str(cwd / "diagnostics" / "screenshot.png")
