"""Pydantic models for browser session state, flow state, and flow results."""

from typing import Annotated, Any, Literal

from pydantic import BaseModel, Discriminator, Tag, TypeAdapter

from llm_browser.selectors import Selector


class Field(BaseModel, extra="allow"):
    """A single form field to fill."""

    type: str
    id: str


class Condition(BaseModel, extra="allow"):
    """A when-clause condition."""

    field: str
    op: str


# --- Step types ---


CaptureMode = Literal["screenshot", "dom", "both"]


class BaseStep(BaseModel):
    """Common fields shared by all step types."""

    name: str = "unnamed"
    fields: list[dict[str, Any]] = []
    when: list[dict[str, Any]] = []
    selector: Selector | None = None
    eval: str | None = None
    wait_after: int | None = None
    checkpoint: bool = False


class ClickStep(BaseStep):
    action: Literal["click"]
    dispatch: bool = False


class FillStep(BaseStep):
    action: Literal["fill"]
    value: str = ""


class TypeStep(BaseStep):
    action: Literal["type"]
    value: str = ""
    delay: int = 0


class SelectStep(BaseStep):
    action: Literal["select"]
    value: str = ""


class CheckStep(BaseStep):
    action: Literal["check"]
    checked: bool = True


class PickStep(BaseStep):
    action: Literal["pick"]
    value: str = ""


class GotoStep(BaseStep):
    action: Literal["goto"]
    url: str = ""
    wait_until: str = "domcontentloaded"


class WaitStep(BaseStep):
    action: Literal["wait"]
    state: str = "domcontentloaded"
    timeout: int = 10_000


class ScreenshotStep(BaseStep):
    action: Literal["screenshot"]


class ReadStep(BaseStep):
    action: Literal["read"]
    extract: dict[str, dict[str, str]] = {}


class DomStep(BaseStep):
    action: Literal["dom"]
    max_depth: int = 0


class DownloadStep(BaseStep):
    action: Literal["download"]
    path: str = ""


class ThinkStep(BaseStep):
    action: Literal["think"]
    min_ms: int = 500
    max_ms: int = 2000


class EvalStep(BaseStep):
    """Step with no browser action (eval-only, wait, checkpoint)."""

    action: None = None


KNOWN_ACTIONS = frozenset(
    {
        "click",
        "fill",
        "type",
        "select",
        "check",
        "pick",
        "goto",
        "wait",
        "screenshot",
        "read",
        "dom",
        "download",
        "think",
    }
)


def _step_discriminator(v: Any) -> str:
    action = v.get("action") if isinstance(v, dict) else getattr(v, "action", None)
    if action is None:
        return "eval"
    return str(action)


Step = Annotated[
    Annotated[ClickStep, Tag("click")]
    | Annotated[FillStep, Tag("fill")]
    | Annotated[TypeStep, Tag("type")]
    | Annotated[SelectStep, Tag("select")]
    | Annotated[CheckStep, Tag("check")]
    | Annotated[PickStep, Tag("pick")]
    | Annotated[GotoStep, Tag("goto")]
    | Annotated[WaitStep, Tag("wait")]
    | Annotated[ScreenshotStep, Tag("screenshot")]
    | Annotated[ReadStep, Tag("read")]
    | Annotated[DomStep, Tag("dom")]
    | Annotated[DownloadStep, Tag("download")]
    | Annotated[ThinkStep, Tag("think")]
    | Annotated[EvalStep, Tag("eval")],
    Discriminator(_step_discriminator),
]

_step_adapter: TypeAdapter[Step] = TypeAdapter(Step)


def validate_step(data: dict[str, Any]) -> Step:
    """Validate a raw dict into the appropriate Step subtype."""
    return _step_adapter.validate_python(data)


# --- Other models ---


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
    dom: str | None = None
    completed: bool = False
