"""Run scenarios against drivers and report what happened.

One scenario's failure never stops the run: the whole value of the table is
seeing every driver's answer to every question at once, so each check is
caught, recorded and followed by the next.
"""

import json
import time
import traceback
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from llm_browser_conformance.drivers import launched_session, unavailable
from llm_browser_conformance.scenario import (
    DEFAULT_DELAY_MS,
    Context,
    Outcome,
    Scenario,
    ScenarioSkipped,
    Section,
)
from llm_browser_conformance.scenarios import select
from llm_browser_conformance.server import serve_site


@dataclass(frozen=True)
class Result:
    scenario: str
    section: Section
    driver: str
    outcome: Outcome
    elapsed_s: float
    detail: str = ""


def one_line(error: BaseException) -> str:
    """The message plus the line that raised it — a bare ``assert`` says
    nothing on its own, and the table is all the reader gets."""
    text = str(error) or type(error).__name__
    summary = text.strip().splitlines()[0][:160]
    frames = traceback.extract_tb(error.__traceback__)
    if not frames:
        return summary
    origin = frames[-1]
    return f"{summary} [{Path(origin.filename).name}:{origin.lineno} {origin.line}]"


def run_scenario(scenario: Scenario, ctx: Context) -> Result:
    """A known gap inverts the verdict: failing is expected, passing is news."""
    gap = scenario.gap_for(ctx.driver)
    start = time.monotonic()
    try:
        note = scenario.check(ctx) or ""
    except ScenarioSkipped as skipped:
        return result(scenario, ctx, Outcome.SKIP, start, str(skipped))
    except Exception as failure:  # noqa: BLE001 - one scenario never ends the run
        outcome = Outcome.XFAIL if gap else Outcome.FAIL
        return result(scenario, ctx, outcome, start, gap or one_line(failure))
    outcome = Outcome.XPASS if gap else Outcome.PASS
    return result(scenario, ctx, outcome, start, f"gap closed: {gap}" if gap else note)


def result(
    scenario: Scenario, ctx: Context, outcome: Outcome, start: float, detail: str
) -> Result:
    return Result(
        scenario=scenario.name,
        section=scenario.section,
        driver=ctx.driver,
        outcome=outcome,
        elapsed_s=round(time.monotonic() - start, 3),
        detail=detail,
    )


def skipped_driver(driver: str, scenarios: list[Scenario], reason: str) -> list[Result]:
    return [
        Result(s.name, s.section, driver, Outcome.SKIP, 0.0, reason)
        for s in scenarios
        if s.applies_to(driver)
    ]


def run_driver(
    driver: str, site_url: str, scenarios: list[Scenario], delay_ms: int
) -> list[Result]:
    reason = unavailable(driver)
    if reason:
        return skipped_driver(driver, scenarios, reason)
    applicable = [s for s in scenarios if s.applies_to(driver)]
    try:
        with launched_session(driver) as session:
            ctx = Context(session, site_url, driver, delay_ms)
            return [run_scenario(s, ctx) for s in applicable]
    except Exception as failure:  # noqa: BLE001 - a browser that will not start is a row, not a crash
        return [
            Result(
                s.name,
                s.section,
                driver,
                Outcome.FAIL,
                0.0,
                f"launch: {one_line(failure)}",
            )
            for s in applicable
        ]


def run(
    drivers: list[str], only: tuple[str, ...] = (), delay_ms: int = DEFAULT_DELAY_MS
) -> list[Result]:
    scenarios = select(only)
    with serve_site() as site_url:
        return [
            result
            for driver in drivers
            for result in run_driver(driver, site_url, scenarios, delay_ms)
        ]


def failed(results: list[Result]) -> bool:
    return any(r.outcome.is_failure for r in results)


# --- Reporting ---


def cell(result: Result | None) -> str:
    if result is None:
        return "-"
    if result.outcome is Outcome.PASS:
        return f"pass {result.elapsed_s:.1f}s"
    if result.outcome is Outcome.XFAIL:
        return f"xfail {result.elapsed_s:.1f}s"
    return str(result.outcome).upper() if result.outcome.is_failure else "skip"


def format_table(results: list[Result], drivers: list[str]) -> str:
    by_key = {(r.scenario, r.driver): r for r in results}
    rows = list(dict.fromkeys((r.section, r.scenario) for r in results))
    label_width = max((len(name) for _, name in rows), default=8) + 2
    widths = [max(len(d), 11) + 2 for d in drivers]
    lines = [
        "".ljust(label_width) + "".join(d.ljust(w) for d, w in zip(drivers, widths))
    ]
    section: Section | None = None
    for row_section, name in rows:
        if row_section is not section:
            section = row_section
            lines.append(f"[{section}]")
        cells = (cell(by_key.get((name, d))) for d in drivers)
        lines.append(
            name.ljust(label_width) + "".join(c.ljust(w) for c, w in zip(cells, widths))
        )
    lines.append("")
    lines.extend(notes(results))
    return "\n".join(lines)


def notes(results: list[Result]) -> list[str]:
    """Every non-passing row, spelled out — a table cell cannot carry a why.

    Grouped by the reason: a browser that would not start says so once, with
    the scenarios it took down, instead of once per row.
    """
    grouped: dict[tuple[str, Outcome, str], list[str]] = {}
    for r in results:
        if r.outcome is Outcome.PASS or not r.detail:
            continue
        grouped.setdefault((r.driver, r.outcome, r.detail), []).append(r.scenario)
    lines = [
        f"{driver:<12} {outcome!s:<6} {scenario_list(names)}: {detail}"
        for (driver, outcome, detail), names in grouped.items()
    ]
    return ["details:", *lines] if lines else []


def scenario_list(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{len(names)} scenarios"


def as_json(results: list[Result], drivers: list[str], delay_ms: int) -> str:
    payload: dict[str, Any] = {
        "drivers": drivers,
        "delay_ms": delay_ms,
        "ok": not failed(results),
        "results": [asdict(r) for r in results],
    }
    return json.dumps(payload, indent=2, default=str)
