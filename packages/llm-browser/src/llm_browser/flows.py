"""Stage two of the flow pipeline (a resolved document in, a validated ``Flow``
out) and the entry point to stage three: run it, redacted, with a retry hint.
Neither stage touches the filesystem — every ``run-flow`` reference is inlined
by :mod:`llm_browser.flow_pipeline` first."""

from collections.abc import Iterable, Mapping
from typing import Any

from llm_browser.behavior import Behavior, profile
from llm_browser.flow_passes import unindexed
from llm_browser.flow_pipeline import parse_flow_yaml
from llm_browser.flow_runner import run_loaded_flow
from llm_browser.iterations import IterationReport
from llm_browser.models import (
    Flow,
    FlowError,
    FlowResult,
    FlowSuccess,
    RetryHint,
)
from llm_browser.redact import clean_secrets, redacting_logs, redact_secrets
from llm_browser.selector_map import SelectorMap
from llm_browser.session import BrowserSession


def load_flow_text(text: str) -> Flow:
    return load_flow_document(parse_flow_yaml(text))


def load_flow_document(document: Mapping[str, Any]) -> Flow:
    return Flow.model_validate(document)


def with_flow_path(result: FlowResult, flow_path: str) -> FlowResult:
    """Fill ``retry_hint.flow_path`` for a flow that came from a file — an
    ``on_error: skip`` run carries one on its success, too."""
    if result.retry_hint is None:
        return result
    hint = result.retry_hint.model_copy(update={"flow_path": flow_path})
    return result.model_copy(update={"retry_hint": hint})


def run_flow(
    session: BrowserSession,
    flow: Flow,
    data: dict[str, object],
    *,
    from_step: str | None = None,
    redact: Iterable[str] = (),
    behavior: Behavior | None = None,
    selector_map: SelectorMap | None = None,
    only: dict[str, list[int]] | None = None,
) -> FlowResult:
    """``from_step`` does not propagate into sub-flows; children always run
    top-to-bottom. ``redact`` scrubs every text the result carries — outputs,
    the error, and the failure DOM; binary payloads are left as they are.

    ``behavior`` is this run's humanization default: every step takes it
    unless it sets its own ``humanize``. It is carried down to each step
    rather than written onto the session, so the session a caller passed in
    comes back out of the run exactly as it went in.

    ``selector_map`` supplies every ``ref:`` selector the flow names, its
    sub-flows' included, as each step runs; check with
    :func:`~llm_browser.selector_map.missing_selectors` first, because a ref
    the map lacks raises
    :class:`~llm_browser.selector_map.MissingSelectorsError` mid-run.

    ``only`` restricts a repeating step to the passes whose indices it names,
    keyed by step name — what a previous run's ``retry_hint.only`` carries.
    Outputs keep the original indices."""
    secrets = clean_secrets(redact)
    with redacting_logs(secrets):
        result = run_loaded_flow(
            session,
            flow,
            data,
            from_step=from_step,
            behavior=behavior,
            selector_map=selector_map,
            only=only,
        )
    ran_as = profile(behavior if behavior is not None else session.behavior)
    iterations = redact_secrets(result.iterations, secrets)
    clean_data = redact_secrets(data, secrets)
    if isinstance(result, FlowSuccess):
        return FlowSuccess(
            step=result.step,
            outputs=redact_secrets(result.outputs, secrets),
            skipped=redact_secrets(result.skipped, secrets),
            warnings=redact_secrets(result.warnings, secrets),
            behavior=ran_as,
            iterations=iterations,
            retry_hint=rerun_hint(iterations, clean_data),
        )
    # `result.step` is qualified and names the failing `repeat` pass; the
    # first segment without its index is the top-level step name, which is
    # what ``--from`` operates on — a pass cannot be resumed on its own.
    failed_step = unindexed(result.step.split("/", 1)[0])[0]
    error = redact_secrets(str(result.data), secrets)
    return FlowError(
        step=result.step,
        data=redact_secrets(result.data, secrets),
        outputs=redact_secrets(result.outputs, secrets),
        skipped=redact_secrets(result.skipped, secrets),
        warnings=redact_secrets(result.warnings, secrets),
        screenshot=result.screenshot,
        dom=redact_secrets(result.dom, secrets),
        human_needed=result.human_needed,
        retry_hint=rerun_hint(iterations, clean_data, failed_step, error)
        or RetryHint(data=clean_data, failed_step=failed_step, error=error),
        behavior=ran_as,
        iterations=iterations,
    )


def rerun_hint(
    iterations: dict[str, IterationReport],
    data: dict[str, object],
    failed_step: str = "",
    error: str = "",
) -> RetryHint | None:
    """How to run the unfinished passes again, or ``None`` when none failed.

    A stopped loop leaves the passes after the failing one unrun, and they
    belong to the rerun as much as the failure does. A repeat over a list param
    gets those items back in ``data``; every other source gets their indices in
    ``only``, since only an index addresses an inline list entry or a matched
    element. A run that survived its failures names no step or error of its
    own, so the first failing step stands in for both.
    """
    failing = {name: report for name, report in iterations.items() if report.failed}
    if not failing:
        return None
    retry_data = dict(data)
    only: dict[str, list[int]] = {}
    for name, report in failing.items():
        if report.over is None:
            only[name] = rerun_indices(report)
        else:
            retry_data[report.over] = rerun_items(report, data)
    first_name, first_report = next(iter(failing.items()))
    return RetryHint(
        data=retry_data,
        failed_step=failed_step or unindexed(first_name.split("/", 1)[0])[0],
        error=error or first_report.failed[0].message,
        only=only,
    )


def rerun_indices(report: IterationReport) -> list[int]:
    """Every pass the run did not finish, in the order it would run them."""
    return sorted([failure.index for failure in report.failed] + report.not_run)


def rerun_items(report: IterationReport, data: dict[str, object]) -> list[object]:
    """The same passes as items. An unrun pass left no record of its item, so
    it is read back out of the list the run was given, which its index keys."""
    items = {failure.index: failure.item for failure in report.failed}
    source = data.get(str(report.over))
    if isinstance(source, list):
        items |= {i: source[i] for i in report.not_run if i < len(source)}
    return [items[index] for index in sorted(items)]
