"""Pydantic models for browser session state, flow state, and flow results."""

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    Tag,
    TypeAdapter,
    field_validator,
)

from llm_browser.parse import ExtractField
from llm_browser.selectors import Selector

# --- Step types ---


CaptureMode = Literal["screenshot", "dom", "both"]


class BaseStep(BaseModel):
    """Common fields shared by all step types.

    No ``selector`` here — see ``SelectorStep`` for steps that target a DOM
    element. Goto / wait / screenshot / think / eval-only steps inherit
    ``BaseStep`` directly.
    """

    name: str = "unnamed"
    fields: list[dict[str, Any]] = []
    when: list[dict[str, Any]] = []
    eval: str | None = None
    wait_after: int | None = None
    checkpoint: bool = False
    optional: bool = False
    timeout: int = 10_000


class SelectorStep(BaseStep):
    """Base for steps that operate on a DOM element. Selector is required."""

    selector: Selector


# Steps that target a DOM element inherit from ``SelectorStep`` (selector
# required). Steps that don't (goto / wait / screenshot / think) inherit
# ``BaseStep``. ``PressStep`` is special: it can target a selector or fall back
# to the focused element via ``press_focused``, so it overrides the field with
# an optional one.


class ClickStep(SelectorStep):
    action: Literal["click"]
    dispatch: bool = False


class FillStep(SelectorStep):
    action: Literal["fill"]
    value: str = ""


class TypeStep(SelectorStep):
    action: Literal["type"]
    value: str = ""
    delay: int = 0


class SelectStep(SelectorStep):
    action: Literal["select"]
    value: str = ""


class CheckStep(SelectorStep):
    action: Literal["check"]
    checked: bool = True


class PickStep(SelectorStep):
    action: Literal["pick"]
    value: str = ""


class GotoStep(BaseStep):
    action: Literal["goto"]
    url: str = Field(..., min_length=1)
    wait_until: str = "domcontentloaded"


class ScreenshotStep(BaseStep):
    action: Literal["screenshot"]


class ReadStep(SelectorStep):
    # ExtractField is a FieldInfo subclass (not a Pydantic model), so the
    # default schema generator can't introspect it. ``arbitrary_types_allowed``
    # tells Pydantic to skip schema generation and trust runtime-validated
    # values (set by the ``_coerce_extract`` validator below).
    model_config = ConfigDict(arbitrary_types_allowed=True)

    action: Literal["read"]
    extract: dict[str, ExtractField] = {}

    @field_validator("extract", mode="before")
    @classmethod
    def _coerce_extract(cls, v: Any) -> Any:
        # YAML loads `extract` as a plain dict; coerce nested dicts into
        # ExtractField.
        if not isinstance(v, dict):
            return v
        return {
            k: spec if isinstance(spec, ExtractField) else ExtractField(**spec)
            for k, spec in v.items()
        }


class ParseStep(SelectorStep):
    """Parse rows into typed instances using a YAML schema.

    Like ``read``, but every row is validated against the schema and
    coerced to a Pydantic model. ``schema_path`` is CWD-relative or
    absolute (same convention as ``download.path``).
    """

    action: Literal["parse"]
    schema_path: str = Field(..., min_length=1)


class DomStep(SelectorStep):
    action: Literal["dom"]
    max_depth: int = 0


class DownloadStep(SelectorStep):
    action: Literal["download"]
    path: str = Field(..., min_length=1)


class ThinkStep(BaseStep):
    action: Literal["think"]
    min_ms: int = 500
    max_ms: int = 2000


class PressStep(BaseStep):
    action: Literal["press"]
    # Optional: when None, press the focused element via ``press_focused``.
    selector: Selector | None = None
    key: str = Field(..., min_length=1)


class WaitStep(SelectorStep):
    """Wait until ``selector``'s text stops changing for ``quiet_ms``.

    Designed for streaming content (LLM chat replies, progressive lists);
    page-level load events should use ``goto``'s ``wait_until`` arg instead.
    """

    action: Literal["wait"]
    quiet_ms: int = 1500
    timeout_s: float = 180.0


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
        "parse",
        "dom",
        "download",
        "think",
        "press",
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
    | Annotated[ScreenshotStep, Tag("screenshot")]
    | Annotated[ReadStep, Tag("read")]
    | Annotated[ParseStep, Tag("parse")]
    | Annotated[DomStep, Tag("dom")]
    | Annotated[DownloadStep, Tag("download")]
    | Annotated[ThinkStep, Tag("think")]
    | Annotated[PressStep, Tag("press")]
    | Annotated[WaitStep, Tag("wait")]
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

    pid: int | None = None
    cdp_url: str = ""
    user_data_dir: str = ""
    driver: str = "patchright"
    mode: Literal["launched", "attached"] = "launched"


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
