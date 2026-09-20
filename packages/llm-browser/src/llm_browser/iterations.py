"""What every pass of a repeating step did: counts, and each failure in full."""

from pydantic import BaseModel

from llm_browser.results import ErrorResult, PayloadBytes


class FailedPass(BaseModel):
    """One pass that failed, with everything needed to heal it and rerun.

    ``item`` is the list value or the element's text snippet; ``step`` is the
    qualified name of the inner step that failed; ``url`` is the page as it was
    then.
    """

    index: int
    item: object = None
    step: str
    error: str = ""
    message: str = ""
    selector: str | None = None
    hint: str | None = None
    url: str = ""
    screenshot: PayloadBytes | None = None


class IterationReport(BaseModel):
    """One repeating step's passes. ``total: 0`` is reported, never silent.

    ``over`` names the list param the passes came from, so a rerun knows to
    resend data rather than indices; it is ``None`` for an inline list or an
    ``over_selector``. ``not_run`` holds the passes a stopped loop never
    reached, which a rerun wants alongside the failed one.
    """

    total: int = 0
    ok: int = 0
    over: str | None = None
    failed: list[FailedPass] = []
    not_run: list[int] = []


def failed_pass(
    index: int,
    item: object,
    step: str,
    detail: object,
    url: str,
    screenshot: bytes | None,
) -> FailedPass:
    """``detail`` is the pass's ``FlowError.data`` — an ``ErrorResult`` for
    every failure an action produced, and stringified for anything else."""
    if not isinstance(detail, ErrorResult):
        return FailedPass(
            index=index,
            item=item,
            step=step,
            message=str(detail),
            url=url,
            screenshot=screenshot,
        )
    return FailedPass(
        index=index,
        item=item,
        step=step,
        error=detail.error,
        message=detail.message,
        selector=detail.selector,
        hint=detail.hint,
        url=url,
        screenshot=screenshot,
    )
