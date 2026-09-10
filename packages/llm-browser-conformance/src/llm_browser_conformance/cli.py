"""``llm-browser-check``: run the conformance suite and report the table."""

import sys

import click

from llm_browser_conformance.drivers import CONFORMANCE_DRIVERS, installed_drivers
from llm_browser_conformance.gaps import known_gaps_document
from llm_browser_conformance.runner import as_json, failed, format_table, run
from llm_browser_conformance.scenario import DEFAULT_DELAY_MS
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
    as_json_output: bool,
    print_gaps: bool,
    delay_ms: int,
) -> None:
    """Run every conformance scenario against one or all installed drivers.

    Exits non-zero if any scenario failed, or if a driver's known gap has
    closed — a stale gap table is a lie about what the drivers do. A selection
    that matches nothing exits 2 before any browser starts: a run that checked
    nothing must never read as success.
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
    results = run(selected, scenarios, delay_ms)
    report = (
        as_json(results, selected, delay_ms)
        if as_json_output
        else format_table(results, selected)
    )
    click.echo(report)
    sys.exit(1 if failed(results) else 0)
