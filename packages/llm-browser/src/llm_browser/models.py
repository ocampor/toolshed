"""Pydantic models for browser session state, flow state, and flow results."""

# debt: over the 300-line rule; split the step models out.

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
from typing import Annotated, Any, ClassVar, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    PrivateAttr,
    Tag,
    TypeAdapter,
    ValidationError,
    field_validator,
    model_validator,
)

from llm_browser.behavior import BehaviorProfile, Jitter
from llm_browser.constants import (
    DEFAULT_POLL_INTERVAL_MS,
    DEFAULT_SETTLE_MS,
    DEFAULT_WAIT_TIMEOUT_MS,
    DELAY_SHAPE,
)
from llm_browser.html import SanitizeLevel
from llm_browser.iterations import IterationReport
from llm_browser.parse import ExtractField, parse_extract_spec
from llm_browser.repeat import Repeat, RepeatBlock, check_scope
from llm_browser.results import AcceptedMatch, PayloadBytes
from llm_browser.selectors import MatchRule, Selector

# --- Step types ---


CaptureMode = Literal["screenshot", "dom", "both", "none"]


WaitState = Literal[
    "attached", "detached", "visible", "hidden", "enabled", "disabled", "stable"
]

# Which way a text wait points. Text is read off ``innerText``, so "there" and
# "rendered" are the same question — the other states ask about an element.
TEXT_STATES: dict[WaitState, bool] = {
    "attached": True,
    "visible": True,
    "detached": False,
    "hidden": False,
}


def check_text_state(state: WaitState) -> bool:
    """``True`` when ``state`` means the text should be there."""
    if state not in TEXT_STATES:
        raise ValueError(
            f"state {state!r} asks about an element, not text; a text wait "
            f"takes {', '.join(TEXT_STATES)}"
        )
    return TEXT_STATES[state]


def check_text_wanted(text: str) -> str:
    """Every page renders the empty string, so a wait for it never waits."""
    if not text:
        raise ValueError("a text wait needs text to look for")
    return text


class SaveAs(BaseModel, extra="forbid"):
    """Where a ``read`` step's rows land in flow data.

    A bare name saves the whole row list. With ``field`` it saves that one
    scalar from the first row ``where`` admits — row 0 when ``where`` is empty.
    """

    name: str = Field(..., pattern=r"^[A-Za-z_]\w*$")
    field: str | None = None
    where: dict[str, Any] = {}

    @model_validator(mode="before")
    @classmethod
    def _name_shorthand(cls, data: Any) -> Any:
        return {"name": data} if isinstance(data, str) else data

    @model_validator(mode="after")
    def _where_needs_a_field(self) -> SaveAs:
        if self.where and self.field is None:
            raise ValueError("save_as `where` picks a row for `field`; name one")
        return self


def selector_ref_shorthand(data: Any) -> Any:
    """``ref: name`` is the compact way to name a selector by ref, and means
    exactly ``selector: {ref: name}`` — at step level and inside ``fields:``
    or ``read:`` alike."""
    if not isinstance(data, dict) or not isinstance(data.get("ref"), str):
        return data
    without_ref = {k: v for k, v in data.items() if k != "ref"}
    return {**without_ref, "selector": {"ref": data["ref"]}}


class TargetSpec(BaseModel, extra="allow"):
    """One entry under a step's ``fields:`` or ``read:``.

    Nothing executes these yet — they are carried for hosts that read them —
    but a ``ref:`` in one is resolved from the selector map like any other.
    """

    selector: Selector | None = None

    _shorthand = model_validator(mode="before")(selector_ref_shorthand)


class BaseStep(BaseModel):
    """Common fields shared by all step types.

    No ``selector`` here — see ``SelectorStep`` for steps that target a DOM
    element. Goto / wait / screenshot / think / eval-only steps inherit
    ``BaseStep`` directly.

    ``scope`` is written ``in:`` in a flow (``in`` is a keyword): it names the
    enclosing repeat's ``as`` and scopes this step's selector to that pass's
    element, descendants only.
    """

    model_config = ConfigDict(populate_by_name=True)

    name: str = "unnamed"
    scope: str | None = Field(None, alias="in", min_length=1)
    fields: list[TargetSpec] = []
    read: dict[str, TargetSpec] = {}
    when: list[dict[str, Any]] = []
    eval: str | None = None
    wait_after: int | None = None
    optional: bool = False
    timeout: int = 10_000
    repeat: Repeat | None = None
    # Set by ``RunFlowStep``'s after-validator on each child step in a
    # sub-flow: the parent's ``run-flow`` step name. ``None`` for
    # top-level steps. Drives ``qualified_name`` for diagnostic output
    # and retry-hint targeting.
    _parent: str | None = PrivateAttr(default=None)

    _shorthand = model_validator(mode="before")(selector_ref_shorthand)

    @property
    def qualified_name(self) -> str:
        """Slash-separated path from the parent flow's run-flow step
        down to this step. Top-level steps just return their own
        ``name``; sub-flow steps return ``"<parent>/<name>"``."""
        return f"{self._parent}/{self.name}" if self._parent else self.name


class MatchTarget(StrEnum):
    """What a step does with the elements its selector matches."""

    ONE = "one"
    MANY = "many"


def check_one_target(step: MatchFields) -> None:
    if step.expect not in (None, 1) and step.pick is None:
        raise ValueError(
            f"this action drives one element, so expect: {step.expect} needs a "
            "pick: (first, last or an index)"
        )


MATCH_CHECKS: dict[MatchTarget, Callable[[MatchFields], None]] = {
    MatchTarget.ONE: check_one_target,
}

ExpectCount = Annotated[int, Field(ge=1)] | Literal["many"]
PickChoice = Literal["first", "last"] | Annotated[int, Field(ge=0)]

DEFAULT_EXPECT: dict[MatchTarget, ExpectCount] = {
    MatchTarget.ONE: 1,
    MatchTarget.MANY: "many",
}


class MatchFields(BaseModel):
    """``expect`` is ``None`` until the flow states one — the default comes from
    ``match_target`` — so "stated" survives the ``model_dump`` round trip
    :func:`llm_browser.steps.resolve_step_templates` makes."""

    expect: ExpectCount | None = None
    pick: PickChoice | None = None

    match_target: ClassVar[MatchTarget] = MatchTarget.ONE

    @model_validator(mode="after")
    def _check_match_fields(self) -> MatchFields:
        states_a_rule = self.expect is not None or self.pick is not None
        if getattr(self, "selector", None) is None and states_a_rule:
            kind = getattr(self, "action", "this step")
            raise ValueError(
                f"{kind} without a selector matches nothing to count, so "
                "expect:/pick: do not apply"
            )
        check = MATCH_CHECKS.get(self.match_target)
        if check is not None:
            check(self)
        return self


def reject_wait_for_match_fields(data: Any) -> Any:
    """A step with no count to state: extra keys are ignored, so ``expect`` and
    ``pick`` would otherwise load and do nothing."""
    if not isinstance(data, dict):
        return data
    stated = [key for key in ("expect", "pick") if key in data]
    if stated:
        raise ValueError(
            f"wait_for waits for a state, not a count, so {'/'.join(stated)}: "
            "does not apply"
        )
    return data


def match_rule_of(step: Step) -> MatchRule | None:
    if not isinstance(step, MatchFields):
        return None
    expect = step.expect
    if expect is None:
        expect = DEFAULT_EXPECT[step.match_target]
    return MatchRule(expect=expect, pick=step.pick)


class SelectorStep(MatchFields, BaseStep):
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
    humanize: bool | None = None


FillVerify = Literal["changed", "exact"]


class FillStep(SelectorStep):
    action: Literal["fill"]
    value: str = ""
    verify: FillVerify = "changed"
    humanize: bool | None = None


class CleanStep(SelectorStep):
    action: Literal["clean"]


class TypeStep(SelectorStep):
    """``delay`` is a constant in ms, or ``[min, max]`` for a per-key jitter —
    a constant cadence is itself a fingerprint."""

    action: Literal["type"]
    value: str = ""
    delay: int | Jitter = 0
    humanize: bool | None = None

    @field_validator("delay", mode="before")
    @classmethod
    def _pair_to_jitter(cls, value: Any) -> Any:
        if not isinstance(value, (list, tuple)):
            return value
        if len(value) != 2:
            raise ValueError(DELAY_SHAPE)
        try:
            return Jitter(min_ms=value[0], max_ms=value[1])
        except ValidationError as e:
            raise ValueError(DELAY_SHAPE) from e


class SelectStep(SelectorStep):
    action: Literal["select"]
    value: str = ""


class CheckStep(SelectorStep):
    action: Literal["check"]
    checked: bool = True
    dispatch: bool = False


class PickStep(SelectorStep):
    action: Literal["pick"]
    value: str = ""

    match_target: ClassVar[MatchTarget] = MatchTarget.MANY


class GotoStep(BaseStep):
    action: Literal["goto"]
    url: str = Field(..., min_length=1)
    wait_until: str = "domcontentloaded"


class ScreenshotStep(MatchFields, BaseStep):
    """``path`` is a CLI instruction, not a runner one.

    The step itself always comes back as a :class:`~llm_browser.results.BytesResult`
    in ``FlowSuccess.outputs``; the library never writes a file. ``path`` is
    where ``llm-browser run`` puts those bytes — relative to ``--out-dir`` —
    and an embedding caller is free to ignore it.

    ``selector`` crops the capture to one element; left unset, the whole
    viewport is captured.
    """

    action: Literal["screenshot"]
    path: str | None = None
    selector: Selector | None = None


class ReadStep(SelectorStep):
    # ExtractField is a FieldInfo subclass (not a Pydantic model), so the
    # default schema generator can't introspect it. ``arbitrary_types_allowed``
    # tells Pydantic to skip schema generation and trust runtime-validated
    # values (set by the ``_coerce_extract`` validator below).
    model_config = ConfigDict(arbitrary_types_allowed=True)

    action: Literal["read"]

    match_target: ClassVar[MatchTarget] = MatchTarget.MANY

    extract: dict[str, ExtractField] = Field(
        default_factory=lambda: parse_extract_spec(None)
    )
    # CSS selectors dropped from the text, not from the DOM: the read happens
    # on a copy, and only for a property a descendant is part of.
    exclude: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    # CLI-only, like every other `path:` — see ScreenshotStep.
    path: str | None = None
    save_as: SaveAs | None = None

    @model_validator(mode="after")
    def _check_save_as(self) -> ReadStep:
        if self.save_as is None:
            return self
        if self.repeat is not None:
            # Each pass keeps its saves to itself, and a lone step has no
            # later step in its pass to read one.
            raise ValueError(
                "save_as on a repeated step is never visible; "
                "repeat a run-flow and save inside it"
            )
        named = set(self.save_as.where)
        if self.save_as.field is not None:
            named.add(self.save_as.field)
        unknown = sorted(named - set(self.extract))
        if unknown:
            raise ValueError(
                f"save_as names {unknown!r}, not among the extracted fields "
                f"{sorted(self.extract)!r}"
            )
        return self

    @field_validator("extract", mode="before")
    @classmethod
    def _coerce_extract(cls, v: Any) -> Any:
        # A flow writes each spec compactly ("td.name@href") or as a mapping;
        # `parse_extract_spec` is the one rule for both — and for a bare `read`
        # naming no field, which reads the row's own text as `text`.
        if v is None or v == {}:
            return parse_extract_spec(None)
        if not isinstance(v, dict):
            return v
        return parse_extract_spec(v)


class ParseStep(SelectorStep):
    """Parse rows into typed instances using a YAML schema.

    Like ``read``, but every row is validated against the schema and
    coerced to a Pydantic model. ``schema_path`` is CWD-relative or
    absolute. ``path`` is CLI-only — see :class:`ScreenshotStep`.
    """

    action: Literal["parse"]

    match_target: ClassVar[MatchTarget] = MatchTarget.MANY

    schema_path: str = Field(..., min_length=1)
    path: str | None = None


class DomStep(SelectorStep):
    action: Literal["dom"]

    match_target: ClassVar[MatchTarget] = MatchTarget.MANY

    max_depth: int = 0
    level: SanitizeLevel = SanitizeLevel.LOW
    # CLI-only, like every other `path:` — see ScreenshotStep.
    path: str | None = None


class DownloadStep(SelectorStep):
    """``path`` is a CLI instruction, not a runner one — see
    :class:`ScreenshotStep`. Left unset, ``llm-browser run`` falls back to the
    filename the server suggested.
    """

    action: Literal["download"]
    path: str | None = None


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


class PressStep(MatchFields, BaseStep):
    action: Literal["press"]
    # Optional: when None, press the focused element via ``press_focused``.
    selector: Selector | None = None
    key: str = Field(..., min_length=1)


def check_settle_budget(state: WaitState, settle: int, timeout: int) -> None:
    """A ``stable`` wait needs room for the settle window inside its budget.

    ``TextSettled`` cannot confirm "held still for ``settle``" before
    ``settle`` has passed, so a smaller ``timeout`` times out even on text
    that never changed — a misleading failure for what is a misconfiguration.
    """
    if state == "stable" and settle >= timeout:
        raise ValueError(
            f"settle ({settle}ms) must be less than timeout ({timeout}ms) "
            "for state 'stable'"
        )


class WaitForStep(BaseStep):
    """Poll until ``selector`` reaches ``state``, or fail the step.

    The one wait: four states answer "is the element there yet" and ``stable``
    answers "has its text stopped changing" — for streaming content (LLM chat
    replies, progressive lists, a recalculating total). ``timeout`` is the
    whole budget; ``interval`` is the nominal gap between polls, jittered;
    ``settle`` is how long the text has to hold still, and applies to
    ``stable`` only.

    ``text`` waits on the page's rendered text instead — a landmark a selector
    cannot name — scoped to ``selector`` when both are given, substring unless
    ``exact``. ``value`` waits on what the ``selector`` field holds, matched the
    same way; ``state`` does not apply to it.
    """

    action: Literal["wait_for"]
    selector: Selector | None = None
    text: str | None = None
    value: str | None = None
    exact: bool = False
    state: WaitState = "attached"
    timeout: int = Field(DEFAULT_WAIT_TIMEOUT_MS, ge=0)
    # Bounded here so a typo fails at flow load with a field-named error,
    # rather than mid-poll as a ``Jitter`` ValueError ``optional`` would eat.
    interval: int = Field(DEFAULT_POLL_INTERVAL_MS, gt=0)
    settle: int = Field(DEFAULT_SETTLE_MS, gt=0)

    _no_match_fields = model_validator(mode="before")(reject_wait_for_match_fields)

    @model_validator(mode="after")
    def _check_target_and_budget(self) -> "WaitForStep":
        if self.selector is None and self.text is None:
            raise ValueError("wait_for needs a selector or text")
        if self.value is not None and (self.selector is None or self.text is not None):
            raise ValueError("wait_for value needs a selector, and no text")
        if self.text is not None:
            check_text_wanted(self.text)
            check_text_state(self.state)
        check_settle_budget(self.state, self.settle, self.timeout)
        return self


class EvalStep(BaseStep):
    """Step with no browser action (eval-only, wait)."""

    action: None = None


class RunFlowStep(BaseStep):
    """Compose another flow inline as a single step.

    ``flow`` is the child flow itself. A reference string is inlined by
    :func:`llm_browser.flow_pipeline.resolve_flow` before validation, so an
    unresolved reference is a validation error.

    Sub-flows are leaf-only: a child may not itself contain ``run-flow``
    steps — ``SubFlow``'s validator enforces that.
    """

    action: Literal["run-flow"]
    flow: SubFlow | str
    data: dict[str, Any] = {}

    @model_validator(mode="after")
    def _reject_unresolved_reference(self) -> RunFlowStep:
        if isinstance(self.flow, str):
            raise ValueError(
                f"unresolved sub-flow {self.flow}: "
                "resolve it through a FlowRepository first"
            )
        # Qualified names (diagnostics, retry hints) need every child step to
        # know which run-flow step it came from.
        for child in self.flow.steps:
            child._parent = self.name
            check_scope(child, self.repeat)
        return self


def _step_discriminator(v: Any) -> str:
    action = v.get("action") if isinstance(v, dict) else getattr(v, "action", None)
    if action is None:
        return "eval"
    return str(action)


Step = Annotated[
    Annotated[ClickStep, Tag("click")]
    | Annotated[FillStep, Tag("fill")]
    | Annotated[CleanStep, Tag("clean")]
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

    # A sub-flow's steps are checked by the ``run-flow`` step that owns them:
    # the repeat they sit in is that step's, which they cannot see from here.
    checks_scopes: ClassVar[bool] = True

    params: list[str | dict[str, Any]] = []
    steps: list[Step]

    @model_validator(mode="before")
    @classmethod
    def _desugar_repeat_blocks(cls, data: Any) -> Any:
        if not isinstance(data, dict) or not isinstance(data.get("steps"), list):
            return data
        steps = [
            RepeatBlock.model_validate(step).desugared()
            if isinstance(step, dict) and step.get("action") == "repeat"
            else step
            for step in data["steps"]
        ]
        return {**data, "steps": steps}

    @model_validator(mode="after")
    def _enforce_step_scopes(self) -> Flow:
        if self.checks_scopes:
            for step in self.steps:
                check_scope(step, step.repeat)
        return self

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

    @model_validator(mode="after")
    def _check_saved_names(self) -> Flow:
        from llm_browser.save_as import check_saved_names

        check_saved_names(self)
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

    checks_scopes: ClassVar[bool] = False

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

    ``only`` restricts a repeating step to the passes that failed, keyed by
    step name — what ``run_flow(only=…)`` and ``run --only`` take. A repeat
    over a list *param* gets the failed items back in ``data`` instead, since
    a rerun renumbers them from zero.
    """

    flow_path: str = ""
    data: dict[str, object]
    failed_step: str
    error: str
    only: dict[str, list[int]] = {}


class SkippedStep(BaseModel):
    """A step the run passed over: its qualified name and why.

    Both kinds of skip land here — a ``when:`` predicate that did not hold,
    and an ``optional:`` step whose action failed — so "nothing matched" stops
    being indistinguishable from "it ran".
    """

    name: str
    reason: str


class MatchWarning(AcceptedMatch):
    step: str


def match_warning(step: str, accepted: AcceptedMatch) -> MatchWarning:
    # The splat cannot drift: every ``AcceptedMatch`` field is a
    # ``MatchWarning`` field.
    return MatchWarning(step=step, **accepted.model_dump())


class FlowSuccess(BaseModel):
    """Returned by ``run_flow`` when a flow ran to completion.

    Carries the name of the last step run (or ``"end"`` for an empty
    flow) — mostly informational.

    ``outputs`` holds every step result the flow produced, keyed by qualified
    step name: rows for ``read`` / ``parse``, text for ``dom``, and a
    :class:`~llm_browser.results.BytesResult` for ``screenshot`` / ``download``.
    Bytes stay bytes; ``model_dump(mode="json")`` base64-encodes them.

    ``skipped`` names every step the run passed over, in the order it did, and
    ``warnings`` every step that ran on a match count its ``expect`` did not
    ask for.

    ``behavior`` names the humanization profile the run actually ran under —
    ``"custom"`` when a knob differs from both presets, ``None`` on a sub-flow
    result, which the parent run stamps on its way out.

    ``iterations`` reports every repeating step that ran, keyed by step name;
    ``retry_hint`` is set only when a pass failed and ``on_error: skip`` kept
    the run going.
    """

    step: str
    outputs: dict[str, object] = {}
    skipped: list[SkippedStep] = []
    warnings: list[MatchWarning] = []
    behavior: BehaviorProfile | None = None
    iterations: dict[str, IterationReport] = {}
    retry_hint: RetryHint | None = None


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
    the same way as :attr:`FlowSuccess.outputs`; ``behavior`` names the run's
    humanization profile the same way as :attr:`FlowSuccess.behavior`.

    ``screenshot`` and ``dom`` are the failing page itself, in memory: PNG
    bytes and sanitized HTML text, controlled by ``BrowserSession(capture=)``.
    Nothing is written — ``model_dump(mode="json")`` base64-encodes the PNG
    and validating that back decodes it, so the model round-trips, and a
    caller that wants files writes them.
    """

    step: str
    data: object = None
    screenshot: PayloadBytes | None = None
    dom: str | None = None
    human_needed: bool = False
    retry_hint: RetryHint | None = None
    outputs: dict[str, object] = {}
    skipped: list[SkippedStep] = []
    warnings: list[MatchWarning] = []
    behavior: BehaviorProfile | None = None
    iterations: dict[str, IterationReport] = {}


# Public type alias: callers that don't care which arm they got can use
# ``FlowResult`` as the return type and switch on ``isinstance``.
FlowResult = FlowSuccess | FlowError
