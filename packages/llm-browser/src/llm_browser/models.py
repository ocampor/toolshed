"""Pydantic models for browser session state, flow state, and flow results."""

from typing import Any

from pydantic import BaseModel


class Field(BaseModel, extra="allow"):
    """A single form field to fill."""

    type: str
    id: str


class Condition(BaseModel, extra="allow"):
    """A when-clause condition."""

    field: str
    op: str


class Step(BaseModel, extra="allow"):
    """A single step in a YAML flow."""

    name: str = "unnamed"
    fields: list[dict[str, Any]] = []
    when: list[dict[str, Any]] = []
    action: str | None = None
    selector: str | None = None
    eval: str | None = None
    wait_after: int | None = None
    checkpoint: bool = False


class Param(BaseModel):
    """A declared flow parameter with type and optional default."""

    type: str = "str"
    required: bool = True
    default: object = None


class FlowData(BaseModel, extra="allow"):
    """Validated flow runtime data built from declared params."""

    def to_template_dict(self) -> dict[str, object]:
        """Convert to dict for template resolution."""
        return {k: v for k, v in self.model_dump().items() if v is not None}


class Flow(BaseModel):
    """A complete YAML flow definition."""

    params: list[str | dict[str, Any]] = []
    steps: list[Step]

    def validate_data(self, data: dict[str, object]) -> FlowData:
        """Validate data against declared params, apply defaults, return FlowData."""
        from llm_browser.params import validate_flow_params

        return validate_flow_params(self.params, data)


class SessionResult(BaseModel):
    """Result returned by session operations (launch, close, status)."""

    status: str
    url: str | None = None
    cdp_url: str | None = None
    screenshot: str | None = None


class SessionInfo(BaseModel):
    """Persisted browser session info for CDP reconnection."""

    pid: int
    cdp_url: str
    user_data_dir: str


class FlowState(BaseModel):
    """Persisted flow execution state for checkpoint/resume."""

    flow_path: str
    data: dict[str, object] = {}
    current_index: int = 0


class FlowResult(BaseModel):
    """Result returned when a flow pauses at a checkpoint or completes."""

    step: str
    data: object = None
    screenshot: str | None = None
    completed: bool = False
