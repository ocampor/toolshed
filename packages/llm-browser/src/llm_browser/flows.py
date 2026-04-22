"""Flow runner: load YAML flows and orchestrate execution with checkpoint/resume."""

from pathlib import Path
from typing import Any

import yaml

from llm_browser.models import (
    Flow,
    FlowData,
    FlowResult,
    FlowState,
    Step,
    validate_step,
)
from llm_browser.selector_map import load_selector_map, resolve_refs
from llm_browser.session import BrowserSession
from llm_browser.steps import execute_step


def load_flow(flow_path: str | Path) -> Flow:
    """Load and validate a YAML flow file."""
    raw = yaml.safe_load(Path(flow_path).read_text())
    return Flow.model_validate(raw)


def resolve_step_refs(step: Step, selector_map: dict[str, dict[str, Any]]) -> Step:
    """Resolve selector-map references in a step, returning a new Step."""
    raw = step.model_dump(exclude_none=True)
    resolved = resolve_refs(raw, selector_map)
    return validate_step(resolved)


class FlowRunner:
    """Runs YAML flows with checkpoint/resume support via disk persistence."""

    def __init__(
        self,
        session: BrowserSession,
        selector_map_path: Path | None = None,
    ) -> None:
        self._session = session
        self._state_file = session.session_dir / "flow_state.json"
        self._selector_map: dict[str, dict[str, Any]] | None = None
        if selector_map_path and selector_map_path.exists():
            self._selector_map = load_selector_map(selector_map_path)

    def run(self, flow_path: str | Path, data: dict[str, object]) -> FlowResult:
        """Run a flow from the beginning. Pauses at first checkpoint."""
        resolved_path = str(Path(flow_path).resolve())
        flow = load_flow(resolved_path)
        self._require_resumable_if_checkpointed(flow, resolved_path)
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

    def _execute(self, state: FlowState, flow: Flow, flow_data: FlowData) -> FlowResult:
        """Execute steps from current index until checkpoint or end."""
        while state.current_index < len(flow.steps):
            step = self._prepare_step(flow.steps[state.current_index])
            state.current_index += 1

            result = execute_step(self._session, step, flow_data)
            if result is not None:
                self._save_state(state)
                return result

        self._clear_state()
        last_name = flow.steps[-1].name if flow.steps else "end"
        return FlowResult(step=last_name, completed=True)

    def _require_resumable_if_checkpointed(self, flow: Flow, flow_path: str) -> None:
        """Refuse flows with checkpoints on sessions that can't survive Python exit.

        Checkpoints persist flow state to disk and return control to the
        caller, who later reinvokes ``resume`` — typically in a new process.
        If the browser dies with this process, resume will have nothing to
        reconnect to. Attach-mode patchright is the supported path.
        """
        if not any(s.checkpoint for s in flow.steps):
            return
        info = self._session._load_state()
        if info is None:
            return  # session not open yet; let execute_step raise the real error
        handle = self._session._handle_from_state(info)
        if self._session.driver.can_resume_across_processes(handle):
            return
        raise RuntimeError(
            f"Flow {flow_path!r} contains a checkpoint but the current session "
            f"(driver={info.driver}, mode={info.mode}) cannot be resumed across "
            "Python processes. Use attach mode (session.attach(cdp_url)) or "
            "remove the checkpoint to run the flow end-to-end in one process."
        )

    def _prepare_step(self, step: Step) -> Step:
        """Resolve selector-map references if a selector map is loaded."""
        if self._selector_map:
            return resolve_step_refs(step, self._selector_map)
        return step

    def _save_state(self, state: FlowState) -> None:
        self._state_file.write_text(state.model_dump_json())

    def _load_state(self) -> FlowState:
        if not self._state_file.exists():
            raise RuntimeError("No flow to resume. Run a flow first.")
        return FlowState.model_validate_json(self._state_file.read_text())

    def _clear_state(self) -> None:
        if self._state_file.exists():
            self._state_file.unlink()
