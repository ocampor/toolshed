"""What the last run said, so ``--failed`` can rerun just that.

Written after every run, into the working directory and gitignored. That is
what makes ``--failed`` need no arguments: the loop is ``llm-browser-check``,
fix something, ``llm-browser-check --failed`` — and the rerun's rows are
merged back, so the file always describes the suite as a whole rather than
only the last handful of scenarios.
"""

import json
import warnings
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from llm_browser_conformance.runner import Result
from llm_browser_conformance.scenario import Outcome, Scenario, Section

HISTORY_FILE = Path(".llm-browser-check") / "last.json"

# ``xfail`` is in here deliberately: a known gap is the likeliest thing to be
# what you just tried to close, and a gap that closed is a failing run.
RERUN_OUTCOMES = frozenset({Outcome.FAIL, Outcome.XFAIL})

# One cell of the table: which scenario, on which driver.
Key = tuple[str, str]


def key(result: Result) -> Key:
    return (result.scenario, result.driver)


def load(path: Path = HISTORY_FILE) -> list[Result]:
    """The last run's rows, or nothing at all.

    The decoding is inside the guard, not just the parse: the file carries no
    version, so a renamed `Section`, a new `Outcome` or a rollback to an older
    install all leave rows this build cannot read. Every invocation of the CLI
    calls this, `--failed` or not, so a record that has drifted has to mean
    "start fresh" rather than a crash before any browser starts.
    """
    try:
        rows = json.loads(path.read_text())
        return [as_result(row) for row in rows]
    except FileNotFoundError:
        return []
    except (OSError, ValueError, TypeError, KeyError) as drift:
        warnings.warn(
            f"ignoring unreadable {path}: {type(drift).__name__}: {drift}",
            stacklevel=2,
        )
        return []


def as_result(row: Mapping[str, Any]) -> Result:
    return Result(
        scenario=row["scenario"],
        section=Section(row["section"]),
        driver=row["driver"],
        outcome=Outcome(row["outcome"]),
        elapsed_s=row["elapsed_s"],
        detail=row.get("detail", ""),
    )


def save(results: Iterable[Result], path: Path = HISTORY_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in results], indent=2))


def merge(previous: Iterable[Result], fresh: Sequence[Result]) -> list[Result]:
    """Fresh rows win; every cell the rerun did not visit is kept as it was."""
    revisited = {key(result) for result in fresh}
    kept = [row for row in previous if key(row) not in revisited]
    return kept + list(fresh)


def rerun_plan(
    previous: Iterable[Result],
    drivers: Sequence[str],
    scenarios: Sequence[Scenario],
) -> dict[str, list[Scenario]]:
    """Which scenarios each driver has to answer again.

    Per driver, because the drivers disagree: a scenario that only camoufox
    got wrong is not worth relaunching Chrome for.
    """
    wanted = {key(row) for row in previous if row.outcome in RERUN_OUTCOMES}
    plan = {
        driver: [s for s in scenarios if (s.name, driver) in wanted]
        for driver in drivers
    }
    return {driver: picked for driver, picked in plan.items() if picked}
