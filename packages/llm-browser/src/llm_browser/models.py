"""Pydantic models for browser session state, flow state, and flow results."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    PrivateAttr,
    Tag,
    TypeAdapter,
    field_validator,
    model_validator,
)

from llm_browser.behavior import Jitter
from llm_browser.constants import DEFAULT_POLL_INTERVAL_MS, DEFAULT_WAIT_TIMEOUT_MS
from llm_browser.parse import ExtractField
from llm_browser.selectors import Selector

# --- Step types ---


CaptureMode = Literal["screenshot", "dom", "both"]

WaitState = Literal["attached", "detached", "visible", "hidden"]


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
    optional: bool = False
    timeout: int = 10_000
    # Set by ``RunFlowStep``'s after-validator on each child step in a
    # sub-flow: the parent's ``run-flow`` step name. ``None`` for
    # top-level steps. Drives ``qualified_name`` for diagnostic output
    # and retry-hint targeting.
    _parent: str | None = PrivateAttr(default=None)

    @model_validator(mode="before")
    @classmethod
    def _resolve_selector_refs(cls, data: Any, info: Any) -> Any:
        """Replace ``ref:`` with ``selector:`` (and the field/read
        variants) from ``info.context["selector_map"]`` before pydantic
        does field-level validation. Without this, ``ref:`` is an
        unknown field that pydantic silently drops, leaving SelectorStep
        subtypes to fail with "selector required".

        No-op when the input isn't a dict (programmatic construction
        from a Step instance) or when no selector map is in context.
        """
        if not isinstance(data, dict):
            return data
        ctx = info.context if info is not None else None
        selector_map = ctx.get("selector_map") if ctx else None
        if selector_map is None:
            return data
        from llm_browser.selector_map import resolve_refs

        return resolve_refs(data, selector_map)

    @property
    def qualified_name(self) -> str:
        """Slash-separated path from the parent flow's run-flow step
        down to this step. Top-level steps just return their own
        ``name``; sub-flow steps return ``"<parent>/<name>"``."""
        return f"{self._parent}/{self.name}" if self._parent else self.name


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
    path: str | None = None


class ReadStep(SelectorStep):
    # ExtractField is a FieldInfo subclass (not a Pydantic model), so the
    # default schema generator can't introspect it. ``arbitrary_types_allowed``
    # tells Pydantic to skip schema generation and trust runtime-validated
    # values (set by the ``_coerce_extract`` validator below).
    model_config = ConfigDict(arbitrary_types_allowed=True)

    action: Literal["read"]
    extract: dict[str, ExtractField] = {}
    path: str | None = None

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
    path: str | None = None


class DomStep(SelectorStep):
    action: Literal["dom"]
    max_depth: int = 0
    path: str | None = None


class DownloadStep(SelectorStep):
    action: Literal["download"]
    path: str = Field(..., min_length=1)


class ThinkStep(BaseStep):
    action: Literal["think"]
    min_ms: int = 500
    max_ms: int = 2000


class ScrollStep(BaseStep):
    """Mouse-wheel scroll: ``times`` ticks of ``delta`` px, paced by ``pause``."""

    action: Literal["scroll"]
    delta: int = 600
    times: int = 1
    pause: Jitter = Jitter(min_ms=300, max_ms=1200)


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


class WaitForStep(SelectorStep):
    """Poll until ``selector`` reaches ``state``, or fail the step.

    The explicit wait: it answers "is the element there yet", where ``wait``
    answers "has the element's text stopped changing". ``timeout`` is the
    whole budget; ``interval`` is the nominal gap between polls, jittered.
    """

    action: Literal["wait_for"]
    state: WaitState = "attached"
    # Bounded here so a typo fails at flow load with a field-named error,
    # rather than mid-poll as a ``Jitter`` ValueError ``optional`` would eat.
    timeout: int = Field(DEFAULT_WAIT_TIMEOUT_MS, ge=0)
    interval: int = Field(DEFAULT_POLL_INTERVAL_MS, gt=0)


class EvalStep(BaseStep):
    """Step with no browser action (eval-only, wait)."""

    action: None = None


class RunFlowStep(BaseStep):
    """Compose another flow inline as a single step.

    Sub-flows are leaf-only: a flow referenced by ``run-flow`` may
    not itself contain ``run-flow`` steps. ``SubFlow``'s validators
    enforce this at parse time.

    ``subflow`` can be supplied directly (tests, programmatic construction)
    or resolved from ``flow`` by an after-validator, per the validation
    context — see :func:`llm_browser.subflows.subflow_text`.
    """

    action: Literal["run-flow"]
    flow: str = Field(..., min_length=1)
    data: dict[str, Any] = {}
    subflow: SubFlow | None = None

    @model_validator(mode="after")
    def _resolve_subflow_from_context(self, info: Any) -> RunFlowStep:
        # Already resolved (programmatic construction, explicit `subflow:`
        # in the YAML) — still tag children with our name so qualified
        # names work for the retry hint. Otherwise load + validate the
        # referenced child YAML.
        if self.subflow is None:
            import yaml

            from llm_browser.subflows import subflow_text

            ctx = info.context if info is not None else None
            if not ctx or ctx.get("in_subflow"):
                # One level deep already: leave it unresolved so ``SubFlow``'s
                # leaf-only validator reports the nesting instead of recursing
                # into (possibly cyclic) grandchildren.
                return self
            text = subflow_text(self.flow, ctx)
            if text is None:
                return self
            self.subflow = SubFlow.model_validate(
                yaml.safe_load(text), context={**ctx, "in_subflow": True}
            )
        for child in self.subflow.steps:
            child._parent = self.name
        return self


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
        "wait_for",
        "screenshot",
        "read",
        "parse",
        "run-flow",
        "dom",
        "download",
        "think",
        "scroll",
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
    | Annotated[ScrollStep, Tag("scroll")]
    | Annotated[PressStep, Tag("press")]
    | Annotated[WaitStep, Tag("wait")]
    | Annotated[WaitForStep, Tag("wait_for")]
    | Annotated[RunFlowStep, Tag("run-flow")]
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

    @model_validator(mode="after")
    def _enforce_unique_step_names(self) -> Flow:
        """Step names act as identifiers (used by ``--from`` for
        partial re-runs). Reject duplicates within the same flow."""
        from collections import Counter

        counts = Counter(s.name for s in self.steps)
        duplicates = sorted(name for name, count in counts.items() if count > 1)
        if duplicates:
            raise ValueError(
                f"duplicate step names {duplicates!r}; "
                "names must be unique within a flow."
            )
        return self

    def validate_data(self, data: dict[str, object]) -> FlowData:
        """Validate data against declared params, apply defaults, return FlowData."""
        from llm_browser.params import validate_flow_params

        return validate_flow_params(self.params, data)


class SubFlow(Flow):
    """A flow eligible for inclusion via ``run-flow``.

    Top-level flows use ``Flow`` and may freely contain ``run-flow``
    steps. A flow being included as a child is leaf-only: it cannot
    itself contain ``run-flow`` steps (cycle prevention).

    Validating a YAML file as ``SubFlow`` rather than ``Flow`` enforces
    this at parse time, which means linters/CI can catch malformed
    children without running the browser.
    """

    @model_validator(mode="after")
    def _enforce_subflow_constraints(self) -> SubFlow:
        nested = next((s for s in self.steps if isinstance(s, RunFlowStep)), None)
        if nested is not None:
            raise ValueError(
                f"Sub-flow contains a `run-flow` step ({nested.name!r}); "
                "nested sub-flows are not allowed."
            )
        return self


# Resolve forward refs: RunFlowStep references SubFlow (defined later) for
# the `subflow` field. With `from __future__ import annotations`, this
# rebuild reads `SubFlow` from this module's globals after the class
# exists.
RunFlowStep.model_rebuild()


class PageProbe(BaseModel):
    """What one in-page probe saw: credential prompt, bot challenge, text.

    ``selector_text`` is the probed element's text, ``None`` when no selector
    was asked for or nothing matched.
    """

    password_visible: bool = False
    challenge: bool = False
    text: str = ""
    selector_text: str | None = None


class SessionResult(BaseModel):
    """Result returned by session operations (launch, close, status)."""

    status: str
    url: str | None = None
    cdp_url: str | None = None
    target_id: str | None = None
    screenshot: str | None = None


class SessionInfo(BaseModel):
    """Persisted browser session info for CDP reconnection."""

    pid: int | None = None
    cdp_url: str = ""
    user_data_dir: str = ""
    driver: str = "patchright"
    mode: Literal["launched", "attached"] = "launched"
    target_id: str | None = None


class RetryHint(BaseModel):
    """Information for re-running a failed flow.

    Attached to a :class:`FlowError` by ``run_flow``. Tells the caller
    what data to pass and which step to resume at via ``--from``.

    ``flow_path`` is empty unless ``run_flow_file`` filled it in.
    """

    flow_path: str = ""
    data: dict[str, object]
    failed_step: str
    error: str


class FlowSuccess(BaseModel):
    """Returned by ``run_flow`` when a flow ran to completion.

    Carries the name of the last step run (or ``"end"`` for an empty
    flow) — mostly informational.

    ``outputs`` holds every ``read`` / ``parse`` / ``dom`` result, keyed by
    qualified step name; screenshots stay on disk and never land here.
    """

    step: str
    outputs: dict[str, object] = {}


class FlowError(BaseModel):
    """Returned by ``run_flow`` when a flow stopped at a failing step.

    ``step`` is the *innermost* step name where the failure happened
    (deep inside a sub-flow, if applicable) — useful for diagnostics.
    ``retry_hint`` is the top-level recovery breadcrumb (the parent
    step name, suitable for ``--from``); set by ``run_flow``.

    ``human_needed`` is the failing page's verdict from
    :func:`llm_browser.probe.human_needed` — retrying won't help until
    someone logs in or clears the challenge.

    ``outputs`` holds the results collected before the failing step, keyed
    the same way as :attr:`FlowSuccess.outputs`.
    """

    step: str
    data: object = None
    screenshot: str | None = None
    dom: str | None = None
    human_needed: bool = False
    retry_hint: RetryHint | None = None
    outputs: dict[str, object] = {}


# Public type alias: callers that don't care which arm they got can use
# ``FlowResult`` as the return type and switch on ``isinstance``.
FlowResult = FlowSuccess | FlowError
