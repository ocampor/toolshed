"""Run scenarios against drivers and report what happened.

One scenario's failure never stops the run: the whole value of the table is
seeing every driver's answer to every question at once, so each check is
caught, recorded and followed by the next.

``run_scenario`` is the single verdict. Both front ends call it — the CLI
prints its ``Outcome``, the pytest wrapper translates the same one into a
pytest report — so the two can never disagree about the same run.
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
from llm_browser_conformance.server import serve_site

TEARDOWN_ROW = "session teardown"


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
    if not scenario.applies_to(ctx.driver):
        return outcome_row(
            scenario, ctx, Outcome.SKIP, start, f"does not apply to {ctx.driver}"
        )
    try:
        note = scenario.check(ctx) or ""
    except ScenarioSkipped as skipped:
        return outcome_row(scenario, ctx, Outcome.SKIP, start, str(skipped))
    except Exception as failure:  # noqa: BLE001 - one scenario never ends the run
        verdict = Outcome.XFAIL if gap else Outcome.FAIL
        return outcome_row(scenario, ctx, verdict, start, gap or one_line(failure))
    verdict = Outcome.XPASS if gap else Outcome.PASS
    detail = f"gap closed: {gap}" if gap else note
    return outcome_row(scenario, ctx, verdict, start, detail)


def outcome_row(
    scenario: Scenario, ctx: Context, verdict: Outcome, start: float, detail: str
) -> Result:
    return Result(
        scenario=scenario.name,
        section=scenario.section,
        driver=ctx.driver,
        outcome=verdict,
        elapsed_s=round(time.monotonic() - start, 3),
        detail=detail,
    )


def driver_rows(
    driver: str, scenarios: list[Scenario], verdict: Outcome, detail: str
) -> list[Result]:
    return [Result(s.name, s.section, driver, verdict, 0.0, detail) for s in scenarios]


def run_driver(
    driver: str, site_url: str, scenarios: list[Scenario], delay_ms: int
) -> list[Result]:
    """Results are kept outside the ``try``.

    A browser that will not start is a whole column of skips-turned-failures,
    but a browser that will not *stop* has already answered every question:
    a teardown error gets its own row and never rewrites finished results.
    """
    reason = unavailable(driver)
    if reason:
        return driver_rows(driver, scenarios, Outcome.SKIP, reason)
    applicable = [s for s in scenarios if s.applies_to(driver)]
    results: list[Result] = []
    try:
        with launched_session(driver) as session:
            ctx = Context(session, site_url, driver, delay_ms)
            results.extend(run_scenario(s, ctx) for s in applicable)
    except Exception as failure:  # noqa: BLE001 - a broken browser is a row, not a crash
        if not results:
            return driver_rows(
                driver, applicable, Outcome.FAIL, f"launch: {one_line(failure)}"
            )
        results.append(
            Result(
                TEARDOWN_ROW,
                Section.SESSION,
                driver,
                Outcome.FAIL,
                0.0,
                one_line(failure),
            )
        )
    return results


def run(
    drivers: list[str], scenarios: list[Scenario], delay_ms: int = DEFAULT_DELAY_MS
) -> list[Result]:
    with serve_site() as site_url:
        return [
            row
            for driver in drivers
            for row in run_driver(driver, site_url, scenarios, delay_ms)
        ]


def failed(results: list[Result]) -> bool:
    return any(r.outcome.is_failure for r in results)


# --- Reporting ---


def cell(row: Result | None) -> str:
    if row is None:
        return "-"
    if row.outcome is Outcome.PASS:
        return f"pass {row.elapsed_s:.1f}s"
    if row.outcome is Outcome.XFAIL:
        return f"xfail {row.elapsed_s:.1f}s"
    return str(row.outcome).upper() if row.outcome.is_failure else "skip"


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
        f"{driver:<12} {verdict!s:<6} {scenario_list(names)}: {detail}"
        for (driver, verdict, detail), names in grouped.items()
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
