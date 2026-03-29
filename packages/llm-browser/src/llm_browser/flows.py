"""Flow runner: load YAML flows and orchestrate execution with checkpoint/resume."""

from pathlib import Path

import yaml

from llm_browser.models import Flow, FlowData, FlowResult, FlowState
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step


def load_flow(flow_path: str | Path) -> Flow:
    """Load and validate a YAML flow file."""
    raw = yaml.safe_load(Path(flow_path).read_text())
    return Flow.model_validate(raw)


class FlowRunner:
    """Runs YAML flows with checkpoint/resume support via disk persistence."""

    def __init__(self, session: BrowserSession) -> None:
        self._session = session
        self._state_file = session.session_dir / "flow_state.json"

    def run(
        self, flow_path: str | Path, data: dict[str, object]
    ) -> FlowResult:
        """Run a flow from the beginning. Pauses at first checkpoint."""
        resolved_path = str(Path(flow_path).resolve())
        flow = load_flow(resolved_path)
        flow_data = flow.validate_data(data)
        state = FlowState(flow_path=resolved_path, data=data)
        return self._execute(state, flow, flow_data)

    def resume(self, data: dict[str, object] | None = None) -> FlowResult:
        """Resume a paused flow, optionally merging new data."""
        state = self._load_state()
        if data:
            state.data.update(data)
        flow = load_flow(state.flow_path)
        flow_data = flow.validate_data(state.data)
        return self._execute(state, flow, flow_data)

    def _execute(
        self, state: FlowState, flow: Flow, flow_data: FlowData
    ) -> FlowResult:
        """Execute steps from current index until checkpoint or end."""
        while state.current_index < len(flow.steps):
            step = flow.steps[state.current_index]
            state.current_index += 1

            result = execute_step(self._session, step, flow_data)
            if result is not None:
                self._save_state(state)
                return result

        self._clear_state()
        last_name = flow.steps[-1].name if flow.steps else "end"
        return FlowResult(step=last_name, completed=True)

    def _save_state(self, state: FlowState) -> None:
        self._state_file.write_text(state.model_dump_json())

    def _load_state(self) -> FlowState:
        if not self._state_file.exists():
            raise RuntimeError("No flow to resume. Run a flow first.")
        return FlowState.model_validate_json(self._state_file.read_text())

    def _clear_state(self) -> None:
        if self._state_file.exists():
            self._state_file.unlink()
