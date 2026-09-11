"""``llm-browser-check``: run the conformance suite and report the table."""

import sys

import click

from llm_browser_conformance import history
from llm_browser_conformance.drivers import CONFORMANCE_DRIVERS, installed_drivers
from llm_browser_conformance.gaps import known_gaps_document
from llm_browser_conformance.runner import (
    Result,
    as_json,
    failed,
    format_table,
    full_plan,
    run,
)
from llm_browser_conformance.scenario import DEFAULT_DELAY_MS, Scenario
from llm_browser_conformance.scenarios import select


@click.command()
@click.option(
    "--driver",
    "drivers",
    multiple=True,
    type=click.Choice(CONFORMANCE_DRIVERS),
    help="Driver to check; repeatable. Default: every installed driver.",
)
@click.option(
    "--only",
    "only",
    multiple=True,
    metavar="SUBSTRING",
    help="Run just the scenarios whose name contains SUBSTRING; repeatable.",
)
@click.option(
    "--failed",
    "only_failed",
    is_flag=True,
    help="Rerun only what failed or xfailed last time, per driver.",
)
@click.option("--json", "as_json_output", is_flag=True, help="Machine-readable report.")
@click.option(
    "--gaps",
    "print_gaps",
    is_flag=True,
    help="Print docs/known-gaps.md as the scenarios define it, and exit.",
)
@click.option(
    "--delay",
    "delay_ms",
    default=DEFAULT_DELAY_MS,
    show_default=True,
    metavar="MS",
    help="How long the fixture pages take to change. Raise it on a slow machine.",
)
def main(
    drivers: tuple[str, ...],
    only: tuple[str, ...],
    only_failed: bool,
    as_json_output: bool,
    print_gaps: bool,
    delay_ms: int,
) -> None:
    """Run every conformance scenario against one or all installed drivers.

    Exits non-zero if any scenario failed, or if a driver's known gap has
    closed — a stale gap table is a lie about what the drivers do. A selection
    that matches nothing exits 2 before any browser starts: a run that checked
    nothing must never read as success.

    Every run records its outcomes, so ``--failed`` can pick the work back up
    where it left off; its rows are merged into that record rather than
    replacing it.
    """
    if print_gaps:
        click.echo(known_gaps_document(), nl=False)
        return
    selected = list(drivers) or installed_drivers()
    if not selected:
        raise click.UsageError(
            "no drivers installed; run `uv sync --all-extras` or pass --driver"
        )
    scenarios = select(only)
    if not scenarios:
        raise click.UsageError(f"--only matched no scenarios: {', '.join(only)}")
    previous = history.load()
    plan = (
        rerun_plan_or_exit(previous, selected, scenarios)
        if only_failed
        else full_plan(selected, scenarios)
    )
    results = run(plan, delay_ms)
    history.save(history.merge(previous, results) if only_failed else results)
    columns = list(plan)
    report = (
        as_json(results, columns, delay_ms)
        if as_json_output
        else format_table(results, columns)
    )
    click.echo(report)
    sys.exit(1 if failed(results) else 0)


def rerun_plan_or_exit(
    previous: list[Result], drivers: list[str], scenarios: list[Scenario]
) -> dict[str, list[Scenario]]:
    """Nothing to rerun is success; nothing to rerun *from* is a usage error."""
    if not previous:
        raise click.UsageError(
            "no recorded run to reread; run `llm-browser-check` first"
        )
    plan = history.rerun_plan(previous, drivers, scenarios)
    if not plan:
        click.echo("nothing failed in the last run")
        sys.exit(0)
    return plan
